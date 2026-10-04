"""Genuine PostgreSQL ownership, authorization, CAS and closure proofs."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from cryptography.fernet import Fernet
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.agent_session_data import AgentSession
from azents.core.crypto import CredentialCipher
from azents.core.enums import LLMProvider
from azents.core.model_availability import ModelCandidateIdentity as PublicIdentity
from azents.core.model_availability import PrimaryModelReservation
from azents.core.model_availability_operations import (
    SessionModelAvailabilityNotFound,
    SessionModelReservationConflict,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_admin import RDBAgentAdmin
from azents.rdb.models.runtime_connection_generation import (
    RDBRuntimeConnectionGenerationCutover,
)
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.active_profile_admission import ActiveProfileAdmissionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_automatic_project import AgentAutomaticProjectRepository
from azents.repos.agent_automatic_project_operations import (
    AgentAutomaticProjectOperationsRepository,
    AutomaticProjectDenial,
    AutomaticProjectOperationResult,
)
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import (
    AgentProjectCatalogEntry,
    AgentProjectCatalogStatusPatch,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import ModelCandidateIdentity
from azents.repos.project_browser_manifest_read import (
    ManifestReadDenial,
    ProjectBrowserManifestReadRepository,
)
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_model_availability import SessionModelAvailabilityRepository
from azents.repos.session_model_profile.repository import SessionModelProfileRepository
from azents.repos.session_working_folder_binding.data import (
    SessionWorkingFolderAuthority,
)
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.subscription_usage_read import SubscriptionUsageReadRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services import project_browser_manifest_test as manifest_fixtures
from azents.services.agent.data import NotAdmin
from azents.services.agent_automatic_project import AgentAutomaticProjectService
from azents.services.agent_automatic_project import service_test as policy_fixtures
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.agent_runtime.lifecycle_data import (
    RuntimeOperationAuthority,
    RuntimeOperationTarget,
)
from azents.services.chatgpt_oauth.data import ProviderRejected, ProviderUnavailable
from azents.services.model_availability import SessionModelAvailabilityService
from azents.services.oauth_runtime_clients import ChatGPTOAuthClientFactory
from azents.services.project_browser_manifest import (
    ProjectBrowserAccessDenied,
    ProjectBrowserManifestService,
)
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingService,
)
from azents.services.subscription_usage import service_test as usage_fixtures
from azents.services.subscription_usage.data import (
    SubscriptionUsageAvailable,
    SubscriptionUsageNotFound,
    SubscriptionUsageNotInWorkspace,
)
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


@pytest_asyncio.fixture
async def committed_fixture_metadata(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> sa.MetaData:
    """Reflect the actual FK graph once for this module's committed test seeds."""
    del latest_db_schema
    metadata = sa.MetaData()
    async with rdb_engine.connect() as connection:
        await connection.run_sync(metadata.reflect)
    return metadata


@pytest_asyncio.fixture(autouse=True)
async def cleanup_committed_fixture_graph(
    rdb_engine: AsyncEngine, committed_fixture_metadata: sa.MetaData
) -> AsyncIterator[None]:
    """Always release only identities created by this committed evidence case."""
    async with committed_fixture_graph(rdb_engine, committed_fixture_metadata):
        yield


@pytest.mark.parametrize("outcome", ["success", "exception", "cancellation"])
async def test_fixture_cleanup_preserves_preexisting_graph_after_every_outcome(
    rdb_engine: AsyncEngine,
    committed_fixture_metadata: sa.MetaData,
    outcome: str,
) -> None:
    """Exact new graph cleanup preserves prior users, Agents and schema markers."""
    retained = await _model_fixture(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    async with reads() as session:
        cutover = await session.read_session.get(
            RDBRuntimeConnectionGenerationCutover, 1
        )
        assert cutover is not None
        cutover_at = cutover.cutover_at
    added: ModelFixture | None = None
    try:
        async with committed_fixture_graph(rdb_engine, committed_fixture_metadata):
            added = await _model_fixture(rdb_engine)
            if outcome == "exception":
                raise RuntimeError("fixture outcome")
            if outcome == "cancellation":
                raise asyncio.CancelledError("fixture outcome")
    except (RuntimeError, asyncio.CancelledError) as error:
        assert outcome != "success" and str(error) == "fixture outcome"
    assert added is not None
    async with reads() as session:
        assert await session.read_session.get(RDBAgent, added.fixture.agent_id) is None
        assert await session.read_session.get(RDBUser, added.fixture.user_id) is None
        assert await session.read_session.get(RDBAgent, retained.fixture.agent_id)
        assert await session.read_session.get(RDBUser, retained.fixture.user_id)
        cutover = await session.read_session.get(
            RDBRuntimeConnectionGenerationCutover, 1
        )
        assert cutover is not None and cutover.cutover_at == cutover_at


@dataclasses.dataclass
class ReadScopes:
    """Observe real PostgreSQL read-only state and exact context closure."""

    manager: SessionManager[ReadSession]
    active: int = 0
    read_only_values: list[str] = dataclasses.field(default_factory=list)

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[ReadSession]:
        self.active += 1
        try:
            async with self.manager() as session:
                value = await session.read_session.scalar(
                    sa.text("SHOW transaction_read_only")
                )
                assert isinstance(value, str)
                self.read_only_values.append(value)
                assert value == "on"
                yield session
        finally:
            self.active -= 1


class ModelFixture(NamedTuple):
    """Field-named fixture identity, completed operations and read witnesses."""

    fixture: manifest_fixtures._Fixture
    repository: SessionModelAvailabilityRepository
    reads: ReadScopes


async def _model_fixture(
    engine: AsyncEngine,
) -> ModelFixture:
    writes = create_read_write_session_manager(engine)
    async with writes() as session:
        fixture = await manifest_fixtures._create_fixture(
            session, slug="model-own-" + uuid4().hex
        )
    agents = AgentRepository()
    sessions = AgentSessionRepository()
    memberships = WorkspaceUserRepository()
    profiles = SessionModelProfileRepository(
        agent_repository=agents,
        agent_session_repository=sessions,
        workspace_user_repository=memberships,
        chat_write_request_repository=ChatWriteRequestRepository(),
        active_profile_repository=AsyncMock(spec=ActiveProfileAdmissionRepository),
        session_manager=writes,
    )
    reads = ReadScopes(create_read_only_session_manager(engine))
    repository = SessionModelAvailabilityRepository(
        read_session_manager=reads,
        session_manager=writes,
        agent_repository=agents,
        agent_session_repository=sessions,
        session_model_profile_repository=profiles,
        health_repository=ModelCandidateHealthRepository(session_manager=writes),
    )
    return ModelFixture(fixture=fixture, repository=repository, reads=reads)


async def _identity(
    repository: SessionModelAvailabilityRepository,
    fixture: manifest_fixtures._Fixture,
) -> ModelCandidateIdentity:
    result = await repository.get(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
    )
    assert isinstance(result, Success)
    async with repository.read_session_manager() as session:
        agent = await repository.agent_repository.get_by_id(session, fixture.agent_id)
    assert agent is not None
    return ModelCandidateIdentity(
        workspace_id=agent.workspace_id,
        llm_provider_integration_id=result.value.primary.llm_provider_integration_id,
        model_identifier=result.value.primary.model_identifier,
    )


@pytest.mark.asyncio
async def test_model_read_auth_reservation_cas_and_cancel_generations(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    fixture, repository, reads = await _model_fixture(rdb_engine)
    service = SessionModelAvailabilityService(repository=repository)
    denied = await service.get(
        agent_id=fixture.agent_id, session_id=fixture.session_id, user_id="unauthorized"
    )
    assert isinstance(denied, Failure) and isinstance(
        denied.error, SessionModelAvailabilityNotFound
    )
    identity = await _identity(repository, fixture)
    await repository.health_repository.renew_quota(identity)
    primary = PublicIdentity(
        llm_provider_integration_id=identity.llm_provider_integration_id,
        model_identifier=identity.model_identifier,
    )
    mismatch = await service.reserve(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
        semantic_label="stale-label",
        primary=primary,
    )
    assert isinstance(mismatch, Failure) and isinstance(
        mismatch.error, SessionModelReservationConflict
    )
    unchanged = await repository.health_repository.snapshot(identity)
    assert unchanged.health is not None
    assert unchanged.health.claim_token is None
    accepted = await service.reserve(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
        semantic_label="default",
        primary=primary,
    )
    assert isinstance(accepted, Success) and accepted.value.reservation is not None
    reservation = accepted.value.reservation
    assert (
        accepted.value.state == "primary_next"
        and reservation.reservation_generation == 1
    )
    replay = await service.reserve(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
        semantic_label="default",
        primary=primary,
    )
    assert isinstance(replay, Success) and replay.value.reservation == reservation
    stale = await service.cancel(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
        reservation_generation=reservation.reservation_generation + 1,
    )
    assert isinstance(stale, Failure) and isinstance(
        stale.error, SessionModelReservationConflict
    )
    assert stale.error.availability.reservation == reservation
    canceled = await service.cancel(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
        reservation_generation=reservation.reservation_generation,
    )
    assert isinstance(canceled, Success) and canceled.value.reservation is None
    renewed = await service.reserve(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
        semantic_label="default",
        primary=primary,
    )
    assert isinstance(renewed, Success) and renewed.value.reservation is not None
    assert renewed.value.reservation.reservation_generation == 2
    assert (
        reads.active == 0
        and reads.read_only_values
        and set(reads.read_only_values) == {"on"}
    )


class FaultingSessionRepository(AgentSessionRepository):
    """Raise after Session reservation SQL to prove atomic rollback."""

    def __init__(self, failure: BaseException) -> None:
        self.failure = failure

    async def set_primary_model_reservation(
        self,
        session: WriteSession,
        *,
        session_id: str,
        reservation: PrimaryModelReservation | None,
        expected_reservation_generation: int | None,
    ) -> AgentSession | None:
        await super().set_primary_model_reservation(
            session,
            session_id=session_id,
            reservation=reservation,
            expected_reservation_generation=expected_reservation_generation,
        )
        raise self.failure


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_reservation_failure_or_cancellation_rolls_back_health_and_session(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    cancel: bool,
) -> None:
    fixture, repository, reads = await _model_fixture(rdb_engine)
    identity = await _identity(repository, fixture)
    initial = await repository.health_repository.renew_quota(identity)
    failure = (
        asyncio.CancelledError() if cancel else RuntimeError("after reservation SQL")
    )
    repository.agent_session_repository = FaultingSessionRepository(failure)
    with pytest.raises(type(failure)):
        await repository.reserve(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=fixture.user_id,
            semantic_label="default",
            primary=PublicIdentity(
                llm_provider_integration_id=identity.llm_provider_integration_id,
                model_identifier=identity.model_identifier,
            ),
        )
    health = await repository.health_repository.snapshot(identity)
    assert health.health is not None and initial.health is not None
    assert health.health.generation == initial.health.generation
    assert health.health.claim_token is None
    async with repository.read_session_manager() as session:
        current = await AgentSessionRepository().get_by_id(session, fixture.session_id)
    assert current is not None and current.primary_model_reservation is None
    assert current.primary_model_reservation_generation == 0 and reads.active == 0


class FaultingCatalogRepository(AgentProjectCatalogRepository):
    """Fail after a genuine catalog write so policy/catalog rollback is observable."""

    def __init__(self, failure: BaseException) -> None:
        self.failure = failure

    async def update_status(
        self,
        session: WriteSession,
        *,
        agent_id: str,
        path: str,
        patch: AgentProjectCatalogStatusPatch,
    ) -> AgentProjectCatalogEntry:
        await super().update_status(session, agent_id=agent_id, path=path, patch=patch)
        raise self.failure


def _policy_repository(
    engine: AsyncEngine,
    *,
    catalog: AgentProjectCatalogRepository,
) -> AgentAutomaticProjectOperationsRepository:
    return AgentAutomaticProjectOperationsRepository(
        agent_repository=AgentRepository(),
        admin_repository=AgentAdminRepository(),
        policy_repository=AgentAutomaticProjectRepository(),
        catalog_repository=catalog,
        read_session_manager=ReadScopes(create_read_only_session_manager(engine)),
        session_manager=create_read_write_session_manager(engine),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_policy_and_catalog_rollback_together_on_failure_and_cancel(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    cancel: bool,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    fixture = await policy_fixtures._create_fixture(
        writes, handle="policy-own-" + uuid4().hex
    )
    failure = asyncio.CancelledError() if cancel else RuntimeError("after catalog SQL")
    repository = _policy_repository(
        rdb_engine, catalog=FaultingCatalogRepository(failure)
    )
    with pytest.raises(type(failure)):
        await repository.replace(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            paths=["/workspace/agent/project"],
        )
    result = await repository.read(
        agent_id=fixture.agent_id,
        workspace_id=fixture.workspace_id,
        workspace_user_id=fixture.admin_workspace_user_id,
    )
    assert (
        isinstance(result, Success)
        and result.value.revision == 1
        and result.value.project_paths == ()
    )
    async with repository.read_session_manager() as session:
        entries = await AgentProjectCatalogRepository().list_entries_by_paths(
            session,
            agent_id=fixture.agent_id,
            paths=["/workspace/agent/project"],
        )
    assert entries == []


@pytest.mark.asyncio
async def test_policy_final_mutation_rejects_revoked_admin_after_runtime_probe(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    fixture = await policy_fixtures._create_fixture(
        writes, handle="policy-revoke-" + uuid4().hex
    )
    repository = _policy_repository(rdb_engine, catalog=AgentProjectCatalogRepository())
    tracking = policy_fixtures._TrackingSessionManager(writes)
    reads = ReadScopes(create_read_only_session_manager(rdb_engine))
    repository.read_session_manager = reads
    repository.session_manager = tracking

    async def revoke() -> None:
        assert tracking.active_contexts == 0
        assert reads.active == 0
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBAgentAdmin).where(
                    RDBAgentAdmin.agent_id == fixture.agent_id,
                    RDBAgentAdmin.workspace_user_id == fixture.admin_workspace_user_id,
                )
            )

    runner = policy_fixtures._FakeRunnerOperations(
        session_manager=tracking, on_stat=revoke
    )
    service = AgentAutomaticProjectService(
        repository=repository,
        runtime_target_resolver=policy_fixtures._FakeRuntimeTargetResolver(),
        runner_operations=runner,
    )
    result = await service.replace_policy(
        agent_id=fixture.agent_id,
        workspace_id=fixture.workspace_id,
        workspace_user_id=fixture.admin_workspace_user_id,
        expected_revision=1,
        project_paths=["/workspace/agent/project"],
    )
    assert isinstance(result, Failure) and isinstance(result.error, NotAdmin)
    async with repository.read_session_manager() as session:
        policy = await AgentAutomaticProjectRepository().get_policy(
            session, agent_id=fixture.agent_id
        )
    assert policy is not None and policy.revision == 1 and policy.project_paths == ()


@pytest.mark.asyncio
async def test_native_read_scopes_reject_sql_write_and_close_after_error(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """The read-only boundary is enforced by PostgreSQL, not a Python convention."""
    fixture, repository, reads = await _model_fixture(rdb_engine)
    with pytest.raises(DBAPIError, match="read-only transaction"):
        async with repository.read_session_manager() as session:
            await session.read_session.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == fixture.agent_id)
                .values(name="forbidden read scope mutation")
            )
    assert reads.active == 0
    result = await repository.get(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
    )
    assert isinstance(result, Success) and reads.active == 0


@pytest.mark.asyncio
async def test_manifest_post_runtime_read_rechecks_membership_and_closes_scopes(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    async with writes() as session:
        fixture = await manifest_fixtures._create_fixture(
            session, slug="manifest-own-" + uuid4().hex
        )
    reads = ReadScopes(create_read_only_session_manager(rdb_engine))
    repository = ProjectBrowserManifestReadRepository(
        agent_repository=AgentRepository(),
        session_repository=AgentSessionRepository(),
        project_repository=SessionWorkspaceProjectRepository(),
        worktree_repository=SessionGitWorktreeRepository(),
        catalog_repository=AgentProjectCatalogRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        read_session_manager=reads,
    )
    assert isinstance(
        await repository.authorize_session(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=fixture.user_id,
        ),
        Success,
    )
    assert reads.active == 0
    # Model a completed independent revocation while Runtime preparation was outside DB.
    async with writes() as session:
        await session.write_session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.user_id == fixture.user_id,
            )
        )
    result = await repository.read_session(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
        working_folder_path="/workspace/agent/.azents/sessions/test",
    )
    assert result == Failure(ManifestReadDenial.ACCESS_DENIED)
    assert reads.active == 0 and set(reads.read_only_values) == {"on"}


@pytest.mark.asyncio
async def test_subscription_secrets_read_closes_before_freshness_and_usage_client(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove true read-only credential ingress, error ordering and external closure."""
    writes = create_read_write_session_manager(rdb_engine)
    cipher = CredentialCipher(Fernet.generate_key().decode())
    integrations = LLMProviderIntegrationRepository(cipher=cipher)
    template = usage_fixtures._integration()
    async with writes() as session:
        workspace = RDBWorkspace(
            name="Usage ownership", handle="usage-own-" + uuid4().hex
        )
        session.write_session.add(workspace)
        await session.write_session.flush()
        integration = await integrations.create(
            session,
            LLMProviderIntegrationCreate(
                workspace_id=workspace.id,
                provider=LLMProvider.CHATGPT_OAUTH,
                name="Usage snapshot",
                secrets=template.secrets,
                config=template.config,
            ),
        )
        workspace_id = workspace.id
    reads = ReadScopes(create_read_only_session_manager(rdb_engine))
    repository = SubscriptionUsageReadRepository(
        repository=integrations, read_session_manager=reads
    )
    fresh_calls: list[str] = []

    async def freshness(
        *,
        integration: LLMProviderIntegrationWithSecrets,
        persistence_repository: ChatGPTOAuthRuntimeRepository,
        client_factory: ChatGPTOAuthClientFactory,
    ) -> Result[
        LLMProviderIntegrationWithSecrets, ProviderRejected | ProviderUnavailable
    ]:
        del persistence_repository, client_factory
        assert reads.active == 0
        fresh_calls.append(integration.id)
        assert integration.secrets == template.secrets
        return Success(integration)

    def usage(request: httpx.Request) -> httpx.Response:
        assert reads.active == 0
        assert request.headers["authorization"] == "Bearer access-1"
        return httpx.Response(200, json=usage_fixtures._payload())

    monkeypatch.setattr(
        "azents.services.subscription_usage.service.ensure_runtime_tokens", freshness
    )
    service, _ = await usage_fixtures._service(usage, integration=template)
    service.read_repository = repository
    try:
        missing = await service.read(
            integration_id="f" * 32,
            workspace_id=workspace_id,
            include_financial_details=False,
        )
        assert missing == Failure(SubscriptionUsageNotFound(integration_id="f" * 32))
        foreign = await service.read(
            integration_id=integration.id,
            workspace_id="foreign",
            include_financial_details=False,
        )
        assert foreign == Failure(
            SubscriptionUsageNotInWorkspace(integration_id=integration.id)
        )
        assert fresh_calls == []
        result = await service.read(
            integration_id=integration.id,
            workspace_id=workspace_id,
            include_financial_details=False,
        )
        assert isinstance(result, Success) and isinstance(
            result.value, SubscriptionUsageAvailable
        )
        assert fresh_calls == [integration.id]
        assert reads.active == 0 and set(reads.read_only_values) == {"on"}
    finally:
        await service.http_client.aclose()


@pytest.mark.asyncio
async def test_new_quota_generation_fences_old_session_cancellation(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A Session cancellation cannot settle newer candidate-health authority."""
    fixture, repository, _reads = await _model_fixture(rdb_engine)
    identity = await _identity(repository, fixture)
    await repository.health_repository.renew_quota(identity)
    reserved = await repository.reserve(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
        semantic_label="default",
        primary=PublicIdentity(
            llm_provider_integration_id=identity.llm_provider_integration_id,
            model_identifier=identity.model_identifier,
        ),
    )
    assert isinstance(reserved, Success) and reserved.value.reservation is not None
    prior = reserved.value.reservation
    new_quota = await repository.health_repository.renew_quota(identity)
    result = await repository.cancel(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
        reservation_generation=prior.reservation_generation,
    )
    assert isinstance(result, Failure) and isinstance(
        result.error, SessionModelReservationConflict
    )
    assert result.error.availability.reservation is None
    health = await repository.health_repository.snapshot(identity)
    assert health.health is not None and new_quota.health is not None
    assert health.health.generation == new_quota.health.generation
    assert health.health.claim_token is None


@pytest.mark.asyncio
async def test_concurrent_policy_revision_replacement_has_exactly_one_winner(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Two admitted drafts cannot both replace the same revision."""
    writes = create_read_write_session_manager(rdb_engine)
    fixture = await policy_fixtures._create_fixture(
        writes, handle="policy-cas-" + uuid4().hex
    )
    repository = _policy_repository(rdb_engine, catalog=AgentProjectCatalogRepository())
    gate = asyncio.Event()

    async def replace(path: str) -> AutomaticProjectOperationResult:
        await gate.wait()
        return await repository.replace(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            paths=[path],
        )

    first = asyncio.create_task(replace("/workspace/agent/first"))
    second = asyncio.create_task(replace("/workspace/agent/second"))
    gate.set()
    results = await asyncio.gather(first, second)
    assert sum(isinstance(result, Success) for result in results) == 1
    assert (
        sum(
            result == Failure(AutomaticProjectDenial.REVISION_CONFLICT)
            for result in results
        )
        == 1
    )
    policy = await repository.read(
        agent_id=fixture.agent_id,
        workspace_id=fixture.workspace_id,
        workspace_user_id=fixture.admin_workspace_user_id,
    )
    assert isinstance(policy, Success) and policy.value.revision == 2
    assert len(policy.value.project_paths) == 1


class RevokingManifestResolver(manifest_fixtures._RuntimeTargetResolver):
    """Observe completed DB scopes and revoke membership at the Runtime boundary."""

    def __init__(
        self, reads: ReadScopes, writes: SessionManager[WriteSession], user_id: str
    ) -> None:
        self.reads = reads
        self.writes = writes
        self.user_id = user_id

    async def resolve_operation_target(
        self,
        agent_id: str,
        *,
        wait_timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        expected_authority: RuntimeOperationAuthority | None = None,
        start_if_stopped: bool = True,
    ) -> RuntimeOperationTarget:
        assert self.reads.active == 0
        async with self.writes() as session:
            await session.write_session.execute(
                sa.delete(RDBWorkspaceUser).where(
                    RDBWorkspaceUser.user_id == self.user_id,
                )
            )
        return await super().resolve_operation_target(
            agent_id,
            wait_timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            expected_authority=expected_authority,
            start_if_stopped=start_if_stopped,
        )


@pytest.mark.asyncio
async def test_manifest_service_runtime_preparation_has_no_open_db_scope(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """An external boundary revocation is visible in the final authorized snapshot."""
    writes = create_read_write_session_manager(rdb_engine)
    async with writes() as session:
        fixture = await manifest_fixtures._create_fixture(
            session, slug="manifest-service-" + uuid4().hex
        )
    reads = ReadScopes(create_read_only_session_manager(rdb_engine))
    repository = ProjectBrowserManifestReadRepository(
        agent_repository=AgentRepository(),
        session_repository=AgentSessionRepository(),
        project_repository=SessionWorkspaceProjectRepository(),
        worktree_repository=SessionGitWorktreeRepository(),
        catalog_repository=AgentProjectCatalogRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        read_session_manager=reads,
    )
    binding = AsyncMock(spec=SessionWorkingFolderBindingService)
    binding.resolve_bound_authority_for_target.return_value = (
        SessionWorkingFolderAuthority(
            context_id="context",
            agent_id=fixture.agent_id,
            agent_runtime_id="runtime-1",
            working_folder_path="/workspace/agent/.azents/sessions/bound",
            runtime_capability_version=1,
        )
    )

    async def bound(*, agent_id: str, session_id: str) -> None:
        del agent_id, session_id
        assert reads.active == 0

    binding.require_bound_context.side_effect = bound
    service = ProjectBrowserManifestService(
        repository=repository,
        catalog_service=AsyncMock(spec=AgentProjectCatalogService),
        runtime_target_resolver=RevokingManifestResolver(
            reads, writes, fixture.user_id
        ),
        session_working_folder_binding_service=binding,
    )
    result = await service.get_session_manifest(
        agent_id=fixture.agent_id,
        session_id=fixture.session_id,
        user_id=fixture.user_id,
    )
    assert result == Failure(ProjectBrowserAccessDenied())
    assert reads.active == 0 and len(reads.read_only_values) == 2
