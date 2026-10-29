"""Real PostgreSQL admission, lifecycle and deterministic concurrency checks."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Success
from azcommon.uuid import uuid7
from azents_llm_contract.target import InferenceTarget
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.enums import AgentLifecycleStatus, LLMProvider
from azents.core.llm_access import (
    LLMAccessDenied,
    LLMTargetDenied,
    LLMTokenConflict,
    token_digest,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_access import RDBLLMAccessSupply, RDBLLMAccessToken
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    ReadWriteSession,
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.agent import AgentRepository
from azents.repos.llm_access import CreatedAccess, LLMAccessRepository
from azents.repos.llm_authority import LLMAuthorityRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.llm_access import LLMAccessService
from azents.services.llm_authority import LLMAuthorityService
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)
from azents.worker.session.idle_continuation_lock_test import _wait_for_database_blocker


@dataclass(frozen=True)
class Subject:
    agent_id: str
    workspace_id: str
    integration_id: str
    repository: LLMAccessRepository
    authority: LLMAuthorityRepository

    @property
    def target_id(self) -> str:
        return InferenceTarget("default", self.integration_id, "test-model").target_id


@pytest_asyncio.fixture
async def subject(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[Subject]:
    cipher = CredentialCipher(Fernet.generate_key().decode())
    manager = create_read_write_session_manager(rdb_engine)
    async with manager() as scope:
        workspace = RDBWorkspace(name="Inference authority test", handle=uuid7().hex)
        scope.write_session.add(workspace)
        await scope.write_session.flush()
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace.id,
            provider=LLMProvider.OPENAI,
            name="Fixture",
            encrypted_credentials=cipher.encrypt(
                '{"type":"api_key","api_key":"provider-sentinel"}'
            ),
            config=None,
        )
        scope.write_session.add(integration)
        await scope.write_session.flush()
        selection = make_test_model_selection_dict(
            integration_id=integration.id, model_identifier="test-model"
        )
        agent = RDBAgent(
            workspace_id=workspace.id,
            name="Fixture",
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection, lightweight_model_selection=selection
            ),
            main_model_label="default",
            lightweight_model_label="lightweight",
        )
        scope.write_session.add(agent)
        await scope.write_session.flush()
        result = Subject(
            agent.id,
            workspace.id,
            integration.id,
            LLMAccessRepository(manager),
            LLMAuthorityRepository(
                manager, LLMProviderIntegrationRepository(cipher), AgentRepository()
            ),
        )
    try:
        yield result
    finally:
        async with manager() as scope:
            await scope.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == result.agent_id)
            )
            await scope.write_session.execute(
                sa.delete(RDBLLMProviderIntegration).where(
                    RDBLLMProviderIntegration.id == result.integration_id
                )
            )
            await scope.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == result.workspace_id)
            )


async def _issue(subject: Subject, *, value: str, supply: str) -> CreatedAccess:
    return await subject.repository.issue(
        agent_id=subject.agent_id,
        subject=supply,
        issuer="test-admin",
        digest=token_digest(value),
    )


async def test_hash_only_issue_and_nonsecret_inspection(
    subject: Subject, rdb_engine: AsyncEngine
) -> None:
    service = LLMAccessService(subject.repository)
    issued = await service.issue(
        agent_id=subject.agent_id, subject="development", issuer="test-admin"
    )
    bearer = issued.agent_token.get_secret_value()
    assert len(bearer) >= 43
    assert bearer not in repr(issued)
    async with AsyncSession(rdb_engine) as session:
        row = await session.get(RDBLLMAccessToken, issued.token_id)
        assert row is not None and row.digest == token_digest(bearer)
        assert row.expires_at - row.issued_at == datetime.timedelta(hours=1)
    state = await service.inspect(supply_id=issued.supply_id)
    assert bearer not in repr(state) and token_digest(bearer) not in repr(state)
    assert state.current_token_id == issued.token_id
    assert (
        await subject.repository.authenticate(digest=token_digest(bearer))
    ).agent_id == subject.agent_id
    with pytest.raises(LLMTokenConflict):
        await _issue(subject, value="second", supply="development")


async def test_rotation_is_bounded_and_supplies_are_independent(
    subject: Subject,
) -> None:
    initial = await _issue(subject, value="old", supply="one")
    other = await _issue(subject, value="other", supply="two")
    successor = await subject.repository.rotate(
        supply_id=initial.supply_id,
        expected_token_id=initial.token_id,
        digest=token_digest("new"),
    )
    assert successor.predecessor_expires_at is not None
    assert successor.predecessor_expires_at <= initial.expires_at
    assert (
        successor.predecessor_expires_at
        <= successor.expires_at - datetime.timedelta(minutes=55)
    )
    await subject.repository.authenticate(digest=token_digest("old"))
    await subject.repository.authenticate(digest=token_digest("new"))
    await subject.repository.rotate(
        supply_id=initial.supply_id,
        expected_token_id=successor.token_id,
        digest=token_digest("newest"),
    )
    with pytest.raises(LLMAccessDenied):
        await subject.repository.authenticate(digest=token_digest("old"))
    await subject.repository.authenticate(digest=token_digest("new"))
    await subject.repository.revoke(supply_id=initial.supply_id, token_id=None)
    for value in ("new", "newest"):
        with pytest.raises(LLMAccessDenied):
            await subject.repository.authenticate(digest=token_digest(value))
    assert (
        await subject.repository.authenticate(digest=token_digest("other"))
    ).supply_id == other.supply_id


async def test_rotation_race_has_one_winner(subject: Subject) -> None:
    initial = await _issue(subject, value="old", supply="one")

    async def rotate(value: str) -> CreatedAccess | None:
        try:
            return await subject.repository.rotate(
                supply_id=initial.supply_id,
                expected_token_id=initial.token_id,
                digest=token_digest(value),
            )
        except LLMTokenConflict:
            return None

    results = await asyncio.gather(rotate("a"), rotate("b"))
    assert sum(result is not None for result in results) == 1
    state = await subject.repository.inspect(supply_id=initial.supply_id)
    assert len(state.tokens) == 2


@pytest.mark.parametrize(
    "dimension", ["absolute", "handover", "revoked", "disabled", "deleting"]
)
async def test_expiry_revocation_and_liveness(
    subject: Subject, rdb_engine: AsyncEngine, dimension: str
) -> None:
    issued = await _issue(subject, value="token", supply="one")
    async with rdb_engine.begin() as connection:
        match dimension:
            case "absolute":
                await connection.execute(
                    sa.update(RDBLLMAccessToken)
                    .where(RDBLLMAccessToken.id == issued.token_id)
                    .values(expires_at=sa.func.clock_timestamp())
                )
            case "handover":
                await connection.execute(
                    sa.update(RDBLLMAccessToken)
                    .where(RDBLLMAccessToken.id == issued.token_id)
                    .values(handover_until=sa.func.clock_timestamp())
                )
            case "revoked":
                await connection.execute(
                    sa.update(RDBLLMAccessToken)
                    .where(RDBLLMAccessToken.id == issued.token_id)
                    .values(revoked_at=sa.func.clock_timestamp())
                )
            case "disabled":
                await connection.execute(
                    sa.update(RDBAgent)
                    .where(RDBAgent.id == subject.agent_id)
                    .values(enabled=False)
                )
            case "deleting":
                await connection.execute(
                    sa.update(RDBAgent)
                    .where(RDBAgent.id == subject.agent_id)
                    .values(lifecycle_status=AgentLifecycleStatus.DECOMMISSIONING)
                )
    with pytest.raises(LLMAccessDenied):
        await subject.repository.authenticate(digest=token_digest("token"))


async def test_expiry_is_rechecked_after_lock_wait(
    subject: Subject, rdb_engine: AsyncEngine
) -> None:
    issued = await _issue(subject, value="token", supply="one")
    waiter_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            pid = await session.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            waiter_pid.set_result(pid)
            try:
                yield ReadWriteSession(session)
                await session.commit()
            except asyncio.CancelledError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise

    repository = LLMAccessRepository(manager)
    async with AsyncSession(rdb_engine) as holder:
        await holder.execute(
            sa.select(RDBAgent).where(RDBAgent.id == subject.agent_id).with_for_update()
        )
        blocker = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
        assert isinstance(blocker, int)
        pending = asyncio.create_task(
            repository.authenticate(digest=token_digest("token"))
        )
        try:
            async with asyncio.timeout(15):
                await _wait_for_database_blocker(
                    rdb_engine, blocked_pid=await waiter_pid, blocker_pid=blocker
                )
                await holder.execute(
                    sa.update(RDBLLMAccessToken)
                    .where(RDBLLMAccessToken.id == issued.token_id)
                    .values(expires_at=sa.func.clock_timestamp())
                )
                await holder.commit()
                with pytest.raises(LLMAccessDenied):
                    await pending
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


async def test_token_revoke_does_not_revoke_supply(subject: Subject) -> None:
    issued = await _issue(subject, value="token", supply="one")
    await subject.repository.revoke(
        supply_id=issued.supply_id, token_id=issued.token_id
    )
    with pytest.raises(LLMAccessDenied):
        await subject.repository.authenticate(digest=token_digest("token"))
    await subject.repository.rotate(
        supply_id=issued.supply_id,
        expected_token_id=issued.token_id,
        digest=token_digest("new"),
    )
    await subject.repository.authenticate(digest=token_digest("new"))
    with pytest.raises(LLMAccessDenied):
        await subject.repository.authenticate(digest=token_digest("token"))


async def test_agent_delete_cascades_inference_state(
    subject: Subject, rdb_engine: AsyncEngine
) -> None:
    issued = await _issue(subject, value="token", supply="one")
    async with rdb_engine.begin() as connection:
        await connection.execute(
            sa.delete(RDBAgent).where(RDBAgent.id == subject.agent_id)
        )
        assert (
            await connection.scalar(
                sa.select(RDBLLMAccessSupply.id).where(
                    RDBLLMAccessSupply.id == issued.supply_id
                )
            )
            is None
        )
        assert (
            await connection.scalar(
                sa.select(RDBLLMAccessToken.id).where(
                    RDBLLMAccessToken.id == issued.token_id
                )
            )
            is None
        )
    with pytest.raises(LLMAccessDenied):
        await subject.repository.authenticate(digest=token_digest("token"))


async def test_authority_is_current_and_revalidates_after_refresh(
    subject: Subject, rdb_engine: AsyncEngine
) -> None:
    await _issue(subject, value="token", supply="one")
    args = dict(
        digest=token_digest("token"), model="test-model", target_id=subject.target_id
    )
    prepared = await subject.authority.prepare(**args)
    assert prepared.integration.secrets.type == "api_key"
    assert prepared.identity.workspace_id == subject.workspace_id
    assert (
        await subject.authority.list_models(digest=token_digest("token"))
    ).models == ("test-model",)
    await subject.authority.finalize(
        **args, prepared=prepared, refreshed=prepared.integration
    )
    async with rdb_engine.begin() as connection:
        await connection.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == subject.agent_id)
            .values(model_parameters={"temperature": 0.2})
        )
    with pytest.raises(LLMTargetDenied):
        await subject.authority.finalize(
            **args, prepared=prepared, refreshed=prepared.integration
        )


@pytest.mark.parametrize("mutation", ["disable", "replace", "remove_target", "revoke"])
async def test_authority_rejects_changes_during_preparation(
    subject: Subject, rdb_engine: AsyncEngine, mutation: str
) -> None:
    issued = await _issue(subject, value="token", supply="one")
    args = dict(
        digest=token_digest("token"), model="test-model", target_id=subject.target_id
    )
    prepared = await subject.authority.prepare(**args)
    async with rdb_engine.begin() as connection:
        if mutation == "disable":
            await connection.execute(
                sa.update(RDBLLMProviderIntegration)
                .where(RDBLLMProviderIntegration.id == subject.integration_id)
                .values(enabled=False)
            )
        elif mutation == "replace":
            await connection.execute(
                sa.update(RDBLLMProviderIntegration)
                .where(RDBLLMProviderIntegration.id == subject.integration_id)
                .values(catalog_configuration_version=2)
            )
        elif mutation == "remove_target":
            await connection.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == subject.agent_id)
                .values(
                    selectable_model_options=[
                        {
                            **option.model_dump(mode="json"),
                            "candidates": [
                                {
                                    **candidate.model_dump(mode="json"),
                                    "model_selection": {
                                        **candidate.model_selection.model_dump(
                                            mode="json"
                                        ),
                                        "model_identifier": "changed-model",
                                    },
                                }
                                for candidate in option.candidates
                            ],
                        }
                        for option in prepared.agent.selectable_model_options
                    ]
                )
            )
        else:
            await connection.execute(
                sa.update(RDBLLMAccessSupply)
                .where(RDBLLMAccessSupply.id == issued.supply_id)
                .values(revoked_at=sa.func.clock_timestamp())
            )
    with pytest.raises((LLMTargetDenied, LLMAccessDenied)):
        await subject.authority.finalize(
            **args, prepared=prepared, refreshed=prepared.integration
        )


@pytest.mark.parametrize(
    "model,target", [("foreign", "valid"), ("test-model", "foreign")]
)
async def test_target_selectors_do_not_grant_authority(
    subject: Subject, model: str, target: str
) -> None:
    await _issue(subject, value="token", supply="one")
    with pytest.raises(LLMTargetDenied):
        await subject.authority.prepare(
            digest=token_digest("token"),
            model=model,
            target_id=subject.target_id if target == "valid" else "a" * 64,
        )


async def test_disabled_agent_still_allows_inspection_and_security_revocation(
    subject: Subject, rdb_engine: AsyncEngine
) -> None:
    issued = await _issue(subject, value="token", supply="uncertain-response")
    async with rdb_engine.begin() as connection:
        await connection.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == subject.agent_id)
            .values(enabled=False)
        )
    service = LLMAccessService(subject.repository)
    state = await service.inspect_subject(
        agent_id=subject.agent_id, subject="uncertain-response"
    )
    assert state.supply_id == issued.supply_id
    assert "digest" not in repr(state)
    await service.revoke(supply_id=issued.supply_id, token_id=None)
    assert (await service.inspect(supply_id=issued.supply_id)).revoked_at is not None


async def test_provider_io_runs_after_prepare_transaction_is_closed(
    subject: Subject, rdb_engine: AsyncEngine
) -> None:
    await _issue(subject, value="token", supply="one")
    tokens = AsyncMock(spec=EngineRuntimeTokenResolver)

    async def refresh(
        integration: LLMProviderIntegrationWithSecrets,
    ) -> Success[LLMProviderIntegrationWithSecrets]:
        # A second connection must be able to change both rows while external
        # preparation is running. Any leaked prepare lock fails deterministically.
        async with rdb_engine.begin() as connection:
            await connection.execute(sa.text("SET LOCAL lock_timeout = '1s'"))
            await connection.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == subject.agent_id)
                .values(name="Renamed")
            )
            await connection.execute(
                sa.update(RDBLLMProviderIntegration)
                .where(RDBLLMProviderIntegration.id == subject.integration_id)
                .values(name="Renamed integration")
            )
        return Success(integration)

    tokens.ensure.side_effect = refresh
    result = await LLMAuthorityService(subject.authority, tokens, AsyncMock()).resolve(
        agent_token="token", model="test-model", target_id=subject.target_id
    )
    assert result.identity.agent_id == subject.agent_id


@pytest.mark.parametrize("mutation", ["workspace", "provider"])
async def test_integration_identity_cannot_escape_agent_scope(
    subject: Subject, rdb_engine: AsyncEngine, mutation: str
) -> None:
    await _issue(subject, value="token", supply="one")
    manager = create_read_write_session_manager(rdb_engine)
    async with manager() as scope:
        foreign = RDBWorkspace(name="Foreign", handle=uuid7().hex)
        scope.write_session.add(foreign)
        await scope.write_session.flush()
        if mutation == "workspace":
            update = sa.update(RDBLLMProviderIntegration).values(
                workspace_id=foreign.id
            )
        else:
            update = sa.update(RDBLLMProviderIntegration).values(
                provider=LLMProvider.XAI
            )
        await scope.write_session.execute(
            update.where(RDBLLMProviderIntegration.id == subject.integration_id)
        )
    try:
        with pytest.raises(LLMTargetDenied):
            await subject.authority.prepare(
                digest=token_digest("token"),
                model="test-model",
                target_id=subject.target_id,
            )
    finally:
        async with manager() as scope:
            await scope.write_session.execute(
                sa.update(RDBLLMProviderIntegration)
                .where(RDBLLMProviderIntegration.id == subject.integration_id)
                .values(workspace_id=subject.workspace_id, provider=LLMProvider.OPENAI)
            )
            await scope.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == foreign.id)
            )
