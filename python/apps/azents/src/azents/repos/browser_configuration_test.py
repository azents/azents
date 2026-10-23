"""Migrated PostgreSQL browser intents, leases and exact Runner result fencing."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from azents_runtime_control.browser_configuration import (
    BrowserConfigurationStatus,
    BrowserImplementation,
)
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence

from azents.core.browser_configuration import BrowserConfigurationDenial
from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationDocument,
    RuntimeConfigurationStateStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_admin import RDBAgentAdmin
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.browser_configuration import BrowserConfigurationRepository
from azents.repos.runtime_profile.data import RuntimeConfigurationDesiredStateWrite
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.runtime.control_protocol.grpc.state_sinks_test import _create_runtime


@dataclass(frozen=True)
class Fixture:
    repository: BrowserConfigurationRepository
    agent_id: str
    workspace_id: str
    admin_id: str
    runtime_id: str
    now: datetime


async def fixture(manager: SessionManager[WriteSession]) -> Fixture:
    profiles = RuntimeProfileRepository()
    now = datetime.now(UTC)
    async with manager() as session:
        runtime_id = await _create_runtime(session, "browser-choice")
        runtime = await session.read_session.get(RDBAgentRuntime, runtime_id)
        assert runtime is not None and runtime.runtime_provider_resource_id is not None
        agent = await session.read_session.get(RDBAgent, runtime.agent_id)
        assert agent is not None
        user = await UserRepository().create(
            session, UserCreate(email="browser-choice@example.test")
        )
        member = RDBWorkspaceUser(
            workspace_id=agent.workspace_id,
            user_id=user.id,
            name="Browser admin",
            role=WorkspaceUserRole.MEMBER,
        )
        session.write_session.add(member)
        await session.write_session.flush()
        session.write_session.add(
            RDBAgentAdmin(agent_id=agent.id, workspace_user_id=member.id)
        )
        runtime.desired_state = RuntimeDesiredState.RUNNING
        runtime.desired_generation = 1
        runtime.provider_observed_state = RuntimeProviderObservedState.RUNNING
        runtime.provider_observed_generation = 1
        runtime.runner_state = RuntimeRunnerState.READY
        runtime.runner_generation = 7
        agent.browser_enabled = True
        state = await profiles.overwrite_desired_configuration_state(
            session,
            write=RuntimeConfigurationDesiredStateWrite(
                runtime_id=runtime.id,
                status=RuntimeConfigurationStateStatus.READY,
                target_generation=1,
                digest="d" * 64,
                document=RuntimeConfigurationDocument(
                    schema_version=1,
                    source_trace={},
                    provider_id=runtime.runtime_provider_resource_id,
                    provider_capability_revision_id=None,
                    infrastructure_profile_id="a" * 32,
                    infrastructure_profile_version=1,
                    workspace_runtime_profile_id="b" * 32,
                    workspace_runtime_profile_version=1,
                    agent_selection_version=1,
                    required_capabilities=(),
                    missing_capabilities=(),
                    resolved_configuration={"schema_version": 1},
                ),
                reason_code=None,
            ),
        )
        assert state is not None and state.desired.digest is not None
        evidence = RuntimeConfigurationEvidence(
            state.desired.sequence, state.desired.digest, 1
        )
        runtime.configuration_sequence = state.desired.sequence
        await session.write_session.flush()
        assert await profiles.record_provider_configuration_evidence(
            session,
            runtime_id=runtime.id,
            provider_id=runtime.runtime_provider_resource_id,
            evidence=evidence,
            acknowledged_at=now,
        )
        applied = await profiles.record_runner_configuration_evidence(
            session,
            runtime_id=runtime.id,
            provider_id=runtime.runtime_provider_resource_id,
            evidence=evidence,
            observed_at=now,
        )
        assert applied is not None and applied.applied is not None
        await session.write_session.commit()
        agent_id, workspace_id, admin_id = agent.id, agent.workspace_id, member.id
    return Fixture(
        BrowserConfigurationRepository(manager, manager, profiles),
        agent_id,
        workspace_id,
        admin_id,
        runtime_id,
        now + timedelta(seconds=1),
    )


async def test_browser_writes_preserve_unrelated_agent_policy_evidence(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    item = await fixture(rdb_session_manager)

    async def policy_evidence() -> datetime:
        async with rdb_session_manager() as session:
            return (
                await session.read_session.execute(
                    sa.select(RDBAgent.updated_at).where(RDBAgent.id == item.agent_id)
                )
            ).scalar_one()

    original = await policy_evidence()
    current = await item.repository.read(item.agent_id)
    assert current is not None
    saved = await item.repository.replace(
        agent_id=item.agent_id,
        workspace_id=item.workspace_id,
        workspace_user_id=item.admin_id,
        expected_intent_id=current.intent_id,
        implementation=BrowserImplementation.CAMOUFOX,
        retry=False,
        now=item.now,
    )
    assert saved.success and saved.value.intent_id != current.intent_id
    assert await policy_evidence() == original
    claim = await item.repository.claim_due(
        agent_id=item.agent_id,
        now=item.now,
        lease_until=item.now + timedelta(minutes=1),
    )
    assert claim is not None
    assert await policy_evidence() == original
    await item.repository.defer(claim, item.now)
    assert await policy_evidence() == original
    now = item.now + timedelta(seconds=6)
    recovered = await item.repository.claim_due(
        agent_id=item.agent_id, now=now, lease_until=now + timedelta(minutes=1)
    )
    assert recovered is not None
    assert await item.repository.finish(
        recovered,
        BrowserConfigurationStatus(
            recovered.intent_id, recovered.implementation, "ready", None
        ),
        now,
    )
    assert await policy_evidence() == original


async def test_workspace_owner_can_save_without_explicit_agent_admin(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    item = await fixture(rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.delete(RDBAgentAdmin).where(
                RDBAgentAdmin.agent_id == item.agent_id,
                RDBAgentAdmin.workspace_user_id == item.admin_id,
            )
        )
        await session.write_session.commit()
    current = await item.repository.read(item.agent_id)
    assert current is not None
    args = {
        "agent_id": item.agent_id,
        "workspace_id": item.workspace_id,
        "workspace_user_id": item.admin_id,
        "expected_intent_id": current.intent_id,
        "implementation": BrowserImplementation.CAMOUFOX,
        "retry": False,
        "now": item.now,
    }
    denied = await item.repository.replace(**args)
    assert not denied.success
    assert denied.error is BrowserConfigurationDenial.ADMIN_REQUIRED
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBWorkspaceUser)
            .where(RDBWorkspaceUser.id == item.admin_id)
            .values(role=WorkspaceUserRole.OWNER)
        )
        await session.write_session.commit()
    saved = await item.repository.replace(**args)
    assert saved.success and saved.value.requested is BrowserImplementation.CAMOUFOX


async def test_defaults_and_authorized_exact_intent_save(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    item = await fixture(rdb_session_manager)
    current = await item.repository.read(item.agent_id)
    assert current is not None and current.requested is BrowserImplementation.PATCHRIGHT
    assert current.state == "applying" and len(current.intent_id) == 32
    denied = await item.repository.replace(
        agent_id=item.agent_id,
        workspace_id=item.workspace_id,
        workspace_user_id="0" * 32,
        expected_intent_id=current.intent_id,
        implementation=BrowserImplementation.CAMOUFOX,
        retry=False,
        now=item.now,
    )
    assert (
        not denied.success and denied.error is BrowserConfigurationDenial.ADMIN_REQUIRED
    )
    changed = await item.repository.replace(
        agent_id=item.agent_id,
        workspace_id=item.workspace_id,
        workspace_user_id=item.admin_id,
        expected_intent_id=current.intent_id,
        implementation=BrowserImplementation.CAMOUFOX,
        retry=False,
        now=item.now,
    )
    assert changed.success and changed.value.intent_id != current.intent_id
    stale = await item.repository.replace(
        agent_id=item.agent_id,
        workspace_id=item.workspace_id,
        workspace_user_id=item.admin_id,
        expected_intent_id=current.intent_id,
        implementation=BrowserImplementation.PATCHRIGHT,
        retry=False,
        now=item.now,
    )
    assert not stale.success and stale.error is BrowserConfigurationDenial.STALE_INTENT
    same = await item.repository.replace(
        agent_id=item.agent_id,
        workspace_id=item.workspace_id,
        workspace_user_id=item.admin_id,
        expected_intent_id=changed.value.intent_id,
        implementation=BrowserImplementation.CAMOUFOX,
        retry=False,
        now=item.now,
    )
    assert same.success and same.value.intent_id == changed.value.intent_id


async def test_claim_supersession_lost_lease_and_generation_fence(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    item = await fixture(rdb_session_manager)
    claim = await item.repository.claim_due(
        agent_id=item.agent_id,
        now=item.now,
        lease_until=item.now + timedelta(seconds=10),
    )
    assert claim is not None
    assert (
        await item.repository.claim_due(
            agent_id=item.agent_id,
            now=item.now,
            lease_until=item.now + timedelta(seconds=10),
        )
        is None
    )
    assert (
        await item.repository.current_intent(item.runtime_id, 7, require_ready=True)
        is None
    )
    newer = await item.repository.replace(
        agent_id=item.agent_id,
        workspace_id=item.workspace_id,
        workspace_user_id=item.admin_id,
        expected_intent_id=claim.intent_id,
        implementation=BrowserImplementation.CAMOUFOX,
        retry=False,
        now=item.now,
    )
    assert newer.success
    assert not await item.repository.finish(
        claim,
        BrowserConfigurationStatus(
            claim.intent_id, claim.implementation, "ready", None
        ),
        item.now,
    )
    next_claim = await item.repository.claim_due(
        agent_id=item.agent_id,
        now=item.now,
        lease_until=item.now + timedelta(seconds=10),
    )
    assert next_claim is not None and next_claim.intent_id == newer.value.intent_id
    assert not await item.repository.finish(
        next_claim,
        BrowserConfigurationStatus(
            next_claim.intent_id, next_claim.implementation, "ready", None
        ),
        item.now + timedelta(seconds=11),
    )
    recovered = await item.repository.claim_due(
        agent_id=item.agent_id,
        now=item.now + timedelta(seconds=11),
        lease_until=item.now + timedelta(seconds=30),
    )
    assert recovered is not None and recovered.claim_id != next_claim.claim_id
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == item.runtime_id)
            .values(runner_generation=8)
        )
        await session.write_session.commit()
    assert not await item.repository.claim_current(
        recovered, item.now + timedelta(seconds=12)
    )
    assert not await item.repository.finish(
        recovered,
        BrowserConfigurationStatus(
            recovered.intent_id, recovered.implementation, "ready", None
        ),
        item.now + timedelta(seconds=12),
    )


async def test_ready_failure_retry_and_offline_projection(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    item = await fixture(rdb_session_manager)
    claim = await item.repository.claim_due(
        agent_id=item.agent_id,
        now=item.now,
        lease_until=item.now + timedelta(minutes=1),
    )
    assert claim is not None
    assert await item.repository.finish(
        claim,
        BrowserConfigurationStatus(
            claim.intent_id, claim.implementation, "ready", None
        ),
        item.now,
    )
    assert (
        await item.repository.current_intent(item.runtime_id, 7, require_ready=True)
        == claim.intent_id
    )
    assert (
        await item.repository.claim_due(
            agent_id=item.agent_id,
            now=item.now,
            lease_until=item.now + timedelta(minutes=1),
        )
        is None
    )
    current = await item.repository.read(item.agent_id)
    assert current is not None and current.applied is BrowserImplementation.PATCHRIGHT
    changed = await item.repository.replace(
        agent_id=item.agent_id,
        workspace_id=item.workspace_id,
        workspace_user_id=item.admin_id,
        expected_intent_id=claim.intent_id,
        implementation=BrowserImplementation.CAMOUFOX,
        retry=False,
        now=item.now,
    )
    assert changed.success
    next_claim = await item.repository.claim_due(
        agent_id=item.agent_id,
        now=item.now,
        lease_until=item.now + timedelta(minutes=1),
    )
    assert next_claim is not None
    assert await item.repository.finish(
        next_claim,
        BrowserConfigurationStatus(
            next_claim.intent_id,
            next_claim.implementation,
            "failed",
            "browser_unavailable",
        ),
        item.now,
    )
    assert (
        await item.repository.current_intent(item.runtime_id, 7, require_ready=True)
        is None
    )
    assert (
        await item.repository.claim_due(
            agent_id=item.agent_id,
            now=item.now,
            lease_until=item.now + timedelta(minutes=1),
        )
        is None
    )
    retry = await item.repository.replace(
        agent_id=item.agent_id,
        workspace_id=item.workspace_id,
        workspace_user_id=item.admin_id,
        expected_intent_id=next_claim.intent_id,
        implementation=BrowserImplementation.CAMOUFOX,
        retry=True,
        now=item.now,
    )
    assert retry.success and retry.value.intent_id != next_claim.intent_id
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == item.runtime_id)
            .values(desired_state=RuntimeDesiredState.STOPPED)
        )
        await session.write_session.commit()
    offline = await item.repository.read(item.agent_id)
    assert (
        offline is not None
        and offline.state == "offline"
        and offline.requested is BrowserImplementation.CAMOUFOX
    )
    assert (
        await item.repository.claim_due(
            agent_id=item.agent_id,
            now=item.now,
            lease_until=item.now + timedelta(minutes=1),
        )
        is None
    )
