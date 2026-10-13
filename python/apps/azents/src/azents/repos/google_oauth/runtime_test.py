"""Real PostgreSQL current Session generation and grant-renewal compare fences."""

import dataclasses
import datetime
from typing import NamedTuple
from unittest.mock import Mock

import pytest
import sqlalchemy as sa

from azents.core.enums import AgentSessionRunState
from azents.core.google_oauth import (
    GoogleConnectionStatus,
    GoogleTokens,
)
from azents.core.google_system_setting import (
    GoogleApplicationRegistration,
    GoogleApplicationSecrets,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.toolkit import RDBAgentToolkit, RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.google_oauth.management_test import _google, _review, _settings
from azents.repos.google_oauth.runtime import GoogleRuntimeRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_option_dicts,
)


class RuntimeHarness(NamedTuple):
    repository: GoogleRuntimeRepository
    owner: SessionExecutionOwner
    registration: GoogleApplicationRegistration
    toolkit_id: str
    agent_id: str


async def _runtime(
    manager: SessionManager[WriteSession],
    *,
    owned: bool,
) -> RuntimeHarness:
    h = await _google(manager)
    attempt = await _review(h, None)
    outcome = await h.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        settings=_settings(),
    )
    selection = make_test_model_selection().model_dump(mode="json")
    async with manager() as session:
        agent = RDBAgent(
            workspace_id=h.subject.workspace_id,
            name="Executing Google Agent",
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection,
                lightweight_model_selection=selection,
            ),
            main_model_label="default",
            lightweight_model_label="default",
        )
        session.write_session.add(agent)
        await session.write_session.flush()
        executing = RDBAgentSession(
            workspace_id=h.subject.workspace_id,
            agent_id=agent.id,
            lifecycle_root_session_id=None,
            current_model_target_label=None,
            applied_model_target_label=None,
            current_model_selection=None,
            current_model_settings=None,
            current_reasoning_effort=None,
            applied_reasoning_effort=None,
            current_enabled_execution_options=[],
            applied_enabled_execution_options=[],
            current_effective_context_window_tokens=None,
            current_effective_auto_compaction_threshold_tokens=None,
            current_inference_resolved_at=None,
        )
        executing.run_state = AgentSessionRunState.RUNNING
        session.write_session.add(executing)
        if owned:
            await session.write_session.execute(
                sa.update(RDBToolkitConfig)
                .where(RDBToolkitConfig.id == outcome.toolkit_id)
                .values(owner_agent_id=agent.id)
            )
        else:
            session.write_session.add(
                RDBAgentToolkit(
                    agent_id=agent.id,
                    toolkit_id=outcome.toolkit_id,
                    toolkit_type="google",
                )
            )
        await session.write_session.flush()
        await h.repo.namespaces.ensure_active(
            session,
            agent_id=agent.id,
            toolkit_id=outcome.toolkit_id,
            base_slug="google_reviewed",
        )
        owner = SessionExecutionOwner(executing.id, executing.owner_generation)
        agent_id = agent.id
    return RuntimeHarness(
        GoogleRuntimeRepository(
            manager, h.repo.cipher, h.repo.toolkits, h.repo.settings, h.repo.payloads
        ),
        owner,
        h.registration,
        outcome.toolkit_id,
        agent_id,
    )


@pytest.mark.parametrize("owned", [False, True])
async def test_runtime_admits_current_account_without_human_login(
    rdb_session_manager: SessionManager[WriteSession],
    owned: bool,
) -> None:
    h = await _runtime(rdb_session_manager, owned=owned)
    current = await h.repository.load(h.owner, h.toolkit_id, h.registration)
    assert current.connection.candidate.identity.subject == "verified-google-subject"
    assert current.connection.status is GoogleConnectionStatus.CONNECTED


async def test_owner_generation_change_denies_admission_and_result_mutation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _runtime(rdb_session_manager, owned=False)
    snapshot = await h.repository.load(h.owner, h.toolkit_id, h.registration)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == h.owner.session_id)
            .values(owner_generation=h.owner.owner_generation + 1)
        )
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await h.repository.load(h.owner, h.toolkit_id, h.registration)
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await h.repository.finalize_refresh(
            h.owner, snapshot=snapshot, refreshed=None, rejected=True
        )


async def test_operator_secret_rotation_discards_stale_failure(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _runtime(rdb_session_manager, owned=False)
    snapshot = await h.repository.load(h.owner, h.toolkit_id, h.registration)
    payloads = h.repository.payloads
    assert isinstance(payloads, Mock)
    old = payloads.resolve_current.return_value
    payloads.resolve_current.return_value = dataclasses.replace(
        old,
        effective_generation="rotated",
        secrets=GoogleApplicationSecrets(client_secret="rotated-secret"),
    )
    assert not await h.repository.finalize_refresh(
        h.owner,
        snapshot=snapshot,
        refreshed=None,
        rejected=True,
    )
    current = await h.repository.load(
        h.owner,
        h.toolkit_id,
        dataclasses.replace(
            h.registration,
            client_secret="rotated-secret",
            effective_generation="rotated",
        ),
    )
    assert current.connection.status is GoogleConnectionStatus.CONNECTED


async def test_same_grant_omission_retains_actual_scope_not_requested_scope(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _runtime(rdb_session_manager, owned=False)
    snapshot = await h.repository.load(h.owner, h.toolkit_id, h.registration)
    assert await h.repository.finalize_refresh(
        h.owner,
        snapshot=snapshot,
        refreshed=GoogleTokens(
            access_token="new-token",
            refresh_token=None,
            granted_scopes=None,
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(hours=1),
        ),
        rejected=False,
    )
    current = await h.repository.load(h.owner, h.toolkit_id, h.registration)
    assert (
        current.connection.candidate.tokens.granted_scopes
        == snapshot.connection.candidate.tokens.granted_scopes
    )
    assert (
        current.connection.candidate.tokens.refresh_token
        == snapshot.connection.candidate.tokens.refresh_token
    )
    assert current.connection.id == snapshot.connection.id
    assert not await h.repository.finalize_refresh(
        h.owner,
        snapshot=snapshot,
        refreshed=None,
        rejected=True,
    )
    assert (
        await h.repository.load(h.owner, h.toolkit_id, h.registration)
    ).connection.status is GoogleConnectionStatus.CONNECTED
