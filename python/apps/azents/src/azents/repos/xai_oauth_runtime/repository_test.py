"""PostgreSQL regressions for xAI OAuth refresh persistence and ordering."""

import asyncio
import datetime
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.credentials import XaiOAuthConfig, XaiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import LLMProvider
from azents.core.workspace import WorkspaceCreate
from azents.core.xai_oauth import XaiOAuthConnectionMethod
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.xai_oauth_runtime import XaiOAuthRuntimeRepository
from azents.services.xai_oauth.client import XaiOAuthClient
from azents.services.xai_oauth.data import (
    ProviderEntitlementDenied,
    ProviderRejected,
    ProviderUnavailable,
    TokenSet,
)
from azents.services.xai_oauth.runtime import (
    _persist_refresh_failure,
    _persist_refresh_success,
    ensure_runtime_tokens,
)


def _unexpected_http(_request: httpx.Request) -> httpx.Response:
    """Fail if the controlled refresh hook leaks an actual transport request."""
    raise AssertionError("OAuth repository fixtures must not perform external HTTP")


@asynccontextmanager
async def _client_factory() -> AsyncIterator[XaiOAuthClient]:
    """Retain class-level refresh mocks behind a network-denying transport."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_unexpected_http), timeout=20.0
    ) as client:
        yield XaiOAuthClient(client)


class _Sessions:
    """Use independent committed PostgreSQL transactions and track their lifetime."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.active_transactions = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        async with AsyncSession(self.engine, expire_on_commit=False) as _raw_session:
            session = ReadWriteSession(_raw_session)
            self.active_transactions += 1
            try:
                async with session.write_session.begin():
                    yield session
            finally:
                self.active_transactions -= 1


class _Harness(NamedTuple):
    """Committed integration and collaborators for runtime refresh tests."""

    sessions: _Sessions
    cipher: CredentialCipher
    integration_repository: LLMProviderIntegrationRepository
    persistence: XaiOAuthRuntimeRepository
    integration: LLMProviderIntegrationWithSecrets


@pytest_asyncio.fixture
async def harness(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[_Harness]:
    sessions = _Sessions(rdb_engine)
    cipher = CredentialCipher(Fernet.generate_key().decode())
    repository = LLMProviderIntegrationRepository(cipher)
    persistence = XaiOAuthRuntimeRepository(repository, sessions)
    now = datetime.datetime.now(datetime.UTC)
    workspace_id: str | None = None
    try:
        async with sessions() as session:
            workspace = await WorkspaceRepository().create(
                session,
                WorkspaceCreate(
                    name="xAI refresh", handle=f"xai-refresh-{uuid.uuid4().hex}"
                ),
            )
            assert isinstance(workspace, Success)
            workspace_id = await WorkspaceRepository().resolve_id(
                session, workspace.value.handle
            )
            assert workspace_id is not None
            created = await repository.create(
                session,
                LLMProviderIntegrationCreate(
                    workspace_id=workspace_id,
                    provider=LLMProvider.XAI_OAUTH,
                    name="xAI refresh",
                    secrets=XaiOAuthSecrets(
                        access_token="synthetic-old-access",
                        refresh_token="synthetic-old-refresh",
                        expires_at=now + datetime.timedelta(minutes=1),
                    ),
                    config=XaiOAuthConfig(
                        account_id="old-account",
                        email="old@example.invalid",
                        connection_method=XaiOAuthConnectionMethod.DEVICE.value,
                        status="connected",
                        connected_at=now,
                        last_refreshed_at=now - datetime.timedelta(hours=1),
                    ),
                ),
            )
        integration = await persistence.load_integration(integration_id=created.id)
        assert integration is not None
        yield _Harness(sessions, cipher, repository, persistence, integration)
    finally:
        if workspace_id is not None:
            async with sessions() as session:
                await session.write_session.execute(
                    sa.delete(RDBLLMProviderIntegration).where(
                        RDBLLMProviderIntegration.workspace_id == workspace_id
                    )
                )
                await session.write_session.execute(
                    sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
                )


def _tokens(*, rotate_refresh_token: bool) -> TokenSet:
    return TokenSet(
        access_token="synthetic-new-access",
        refresh_token=(
            "synthetic-new-refresh" if rotate_refresh_token else "synthetic-old-refresh"
        ),
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
        account_id="new-account",
        email="new@example.invalid",
        connection_method=XaiOAuthConnectionMethod.DEVICE,
    )


@pytest.mark.parametrize(
    "change_kind",
    ["user_reconnect", "user_config", "runtime_credentials", "runtime_refreshed_at"],
)
@pytest.mark.parametrize(
    "error",
    [
        None,
        ProviderRejected(reason="stale-rejection"),
        ProviderUnavailable(reason="stale-unavailable"),
        ProviderEntitlementDenied(reason="stale-entitlement"),
    ],
)
async def test_superseded_refresh_preserves_complete_current_integration(
    harness: _Harness,
    change_kind: str,
    error: ProviderRejected | ProviderUnavailable | ProviderEntitlementDenied | None,
) -> None:
    """A stale refresh cannot replace reconnects or a newer runtime identity."""
    original = harness.integration
    assert isinstance(original.secrets, XaiOAuthSecrets)
    assert isinstance(original.config, XaiOAuthConfig)
    secrets = original.secrets.model_copy(
        update={
            "access_token": "current-access",
            "id_token": "current-id-token",
            "expires_at": original.secrets.expires_at + datetime.timedelta(hours=2),
        }
    )
    config = original.config.model_copy(
        update={"account_id": "current-account", "email": "current@example.invalid"}
    )
    async with harness.sessions() as session:
        if change_kind == "user_reconnect":
            update = await harness.integration_repository.update_by_id(
                session, original.id, {"secrets": secrets, "config": config}
            )
        elif change_kind == "user_config":
            update = await harness.integration_repository.update_by_id(
                session, original.id, {"config": config}
            )
        elif change_kind == "runtime_credentials":
            update = await harness.integration_repository.update_runtime_state_by_id(
                session, original.id, {"secrets": secrets}
            )
        else:
            assert original.config.last_refreshed_at is not None
            update = await harness.integration_repository.update_runtime_state_by_id(
                session,
                original.id,
                {
                    "config": original.config.model_copy(
                        update={
                            "last_refreshed_at": original.config.last_refreshed_at
                            + datetime.timedelta(seconds=1)
                        }
                    )
                },
            )
        assert isinstance(update, Success)
    latest = await harness.persistence.load_integration(integration_id=original.id)
    assert latest is not None
    assert latest.catalog_configuration_version == (
        original.catalog_configuration_version
        + (1 if change_kind.startswith("user_") else 0)
    )
    if error is None:
        result = await _persist_refresh_success(
            integration=original,
            persistence_repository=harness.persistence,
            tokens=_tokens(rotate_refresh_token=False),
        )
        assert isinstance(result, Success)
        recovered = result.value
    else:
        recovered = await _persist_refresh_failure(
            integration=original,
            persistence_repository=harness.persistence,
            error=error,
        )
    assert recovered == latest
    stored = await harness.persistence.load_integration(integration_id=original.id)
    assert stored == latest


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (None, "connected"),
        (ProviderRejected(reason="synthetic-rejection"), "refresh_required"),
        (
            ProviderUnavailable(reason="synthetic-unavailable"),
            "temporarily_unavailable",
        ),
        (ProviderEntitlementDenied(reason="synthetic-denial"), "entitlement_denied"),
    ],
)
async def test_provider_refresh_runs_after_completed_database_operations(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    error: ProviderRejected | ProviderUnavailable | ProviderEntitlementDenied | None,
    status: str,
) -> None:
    """Provider HTTP never holds a transaction and persisted outcomes commit."""
    tokens = _tokens(rotate_refresh_token=True)

    async def refresh(
        _self: XaiOAuthClient,
        *,
        refresh_token: str,
        connection_method: XaiOAuthConnectionMethod,
    ) -> Result[
        TokenSet, ProviderRejected | ProviderUnavailable | ProviderEntitlementDenied
    ]:
        assert harness.sessions.active_transactions == 0
        assert refresh_token == "synthetic-old-refresh"
        assert connection_method is XaiOAuthConnectionMethod.DEVICE
        return Success(tokens) if error is None else Failure(error)

    monkeypatch.setattr(XaiOAuthClient, "refresh_tokens", refresh)
    result = await ensure_runtime_tokens(
        integration=harness.integration,
        persistence_repository=harness.persistence,
        client_factory=_client_factory,
    )
    assert harness.sessions.active_transactions == 0
    stored = await harness.persistence.load_integration(
        integration_id=harness.integration.id
    )
    assert stored is not None and isinstance(stored.config, XaiOAuthConfig)
    assert stored.config.status == status
    assert (
        stored.catalog_configuration_version
        == harness.integration.catalog_configuration_version
    )
    if error is None:
        assert isinstance(result, Success)
        assert isinstance(stored.secrets, XaiOAuthSecrets)
        assert stored.secrets.access_token == tokens.access_token
        assert stored.secrets.refresh_token == tokens.refresh_token
    else:
        assert result == Failure(error)
        assert stored.secrets == harness.integration.secrets
        assert stored.config.last_failure_reason is not None
        assert error.reason not in stored.config.last_failure_reason
        if isinstance(error, ProviderEntitlementDenied):
            assert stored.config.entitlement_status == "denied"


class _PausedIntegrationRepository(LLMProviderIntegrationRepository):
    """Pause the real database read to force each competing commit order."""

    def __init__(self, cipher: CredentialCipher, *, lock_before_pause: bool) -> None:
        super().__init__(cipher)
        self.lock_before_pause = lock_before_pause
        self.read_complete = asyncio.Event()
        self.resume = asyncio.Event()
        self.backend_pid: int | None = None

    async def get_by_id_with_secrets_for_update(
        self, session: WriteSession, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        self.backend_pid = await session.read_session.scalar(
            sa.text("SELECT pg_backend_pid()")
        )
        if self.lock_before_pause:
            latest = await super().get_by_id_with_secrets_for_update(
                session, integration_id
            )
            self.read_complete.set()
            await self.resume.wait()
            return latest
        stale_row = await session.read_session.get(
            RDBLLMProviderIntegration, integration_id
        )
        assert stale_row is not None
        self.read_complete.set()
        await self.resume.wait()
        return await super().get_by_id_with_secrets_for_update(session, integration_id)


@pytest.mark.parametrize("lock_before_pause", [False, True])
async def test_concurrent_success_cannot_replace_first_committed_refresh(
    harness: _Harness, lock_before_pause: bool
) -> None:
    """Lock serialization preserves the first successful full credential identity."""
    paused = _PausedIntegrationRepository(
        harness.cipher, lock_before_pause=lock_before_pause
    )
    persistence = XaiOAuthRuntimeRepository(paused, harness.sessions)
    paused_task = asyncio.create_task(
        _persist_refresh_success(
            integration=harness.integration,
            persistence_repository=persistence,
            tokens=_tokens(rotate_refresh_token=False).model_copy(
                update={"access_token": "paused-access", "id_token": "paused-id"}
            ),
        )
    )
    other_task: (
        asyncio.Task[Result[LLMProviderIntegrationWithSecrets, ProviderRejected]] | None
    ) = None
    try:
        await asyncio.wait_for(paused.read_complete.wait(), timeout=10)
        other_task = asyncio.create_task(
            _persist_refresh_success(
                integration=harness.integration,
                persistence_repository=harness.persistence,
                tokens=_tokens(rotate_refresh_token=False).model_copy(
                    update={"access_token": "other-access", "id_token": "other-id"}
                ),
            )
        )
        if lock_before_pause:
            async with asyncio.timeout(10):
                async with AsyncSession(harness.sessions.engine) as _raw_observer:
                    observer = ReadWriteSession(_raw_observer)
                    while not await observer.read_session.scalar(
                        sa.text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks "
                            "WHERE NOT granted AND :pid = ANY(pg_blocking_pids(pid)))"
                        ),
                        {"pid": paused.backend_pid},
                    ):
                        pass
            assert not other_task.done()
            paused.resume.set()
            first = await asyncio.wait_for(paused_task, timeout=10)
            second = await asyncio.wait_for(other_task, timeout=10)
        else:
            first = await asyncio.wait_for(other_task, timeout=10)
            paused.resume.set()
            second = await asyncio.wait_for(paused_task, timeout=10)
        assert isinstance(first, Success) and isinstance(second, Success)
        assert second.value == first.value
        stored = await harness.persistence.load_integration(
            integration_id=harness.integration.id
        )
        assert stored == first.value
        assert stored.catalog_configuration_version == (
            harness.integration.catalog_configuration_version
        )
    finally:
        paused.resume.set()
        for task in (paused_task, other_task):
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("lock_before_pause", [False, True])
@pytest.mark.parametrize("rotate_refresh_token", [False, True])
@pytest.mark.parametrize(
    "error",
    [
        ProviderRejected(reason="synthetic-rejection"),
        ProviderUnavailable(reason="synthetic-unavailable"),
        ProviderEntitlementDenied(reason="synthetic-denial"),
    ],
)
async def test_concurrent_success_preserves_fresh_credentials_and_metadata(
    harness: _Harness,
    lock_before_pause: bool,
    rotate_refresh_token: bool,
    error: ProviderRejected | ProviderUnavailable | ProviderEntitlementDenied,
) -> None:
    """Separate PostgreSQL sessions serialize failure and retain concurrent success."""
    paused = _PausedIntegrationRepository(
        harness.cipher, lock_before_pause=lock_before_pause
    )
    persistence = XaiOAuthRuntimeRepository(paused, harness.sessions)
    tokens = _tokens(rotate_refresh_token=rotate_refresh_token)
    failure_task = asyncio.create_task(
        _persist_refresh_failure(
            integration=harness.integration,
            persistence_repository=persistence,
            error=error,
        )
    )
    success_task: (
        asyncio.Task[Result[LLMProviderIntegrationWithSecrets, ProviderRejected]] | None
    ) = None
    try:
        await asyncio.wait_for(paused.read_complete.wait(), timeout=10)
        success_task = asyncio.create_task(
            _persist_refresh_success(
                integration=harness.integration,
                persistence_repository=harness.persistence,
                tokens=tokens,
            )
        )
        if lock_before_pause:
            # Observe actual row-lock blocking instead of relying on scheduler timing.
            async with asyncio.timeout(10):
                async with AsyncSession(harness.sessions.engine) as _raw_observer:
                    observer = ReadWriteSession(_raw_observer)
                    while not await observer.read_session.scalar(
                        sa.text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks "
                            "WHERE NOT granted AND :pid = ANY(pg_blocking_pids(pid)))"
                        ),
                        {"pid": paused.backend_pid},
                    ):
                        pass
            assert not success_task.done()
            paused.resume.set()
            assert await asyncio.wait_for(failure_task, timeout=10) is None
            success = await asyncio.wait_for(success_task, timeout=10)
        else:
            success = await asyncio.wait_for(success_task, timeout=10)
            paused.resume.set()
            recovered = await asyncio.wait_for(failure_task, timeout=10)
            assert recovered is not None and isinstance(success, Success)
            assert recovered.secrets == success.value.secrets
            assert recovered.config == success.value.config
        assert isinstance(success, Success)
        stored = await harness.persistence.load_integration(
            integration_id=harness.integration.id
        )
        assert stored is not None
        assert isinstance(stored.config, XaiOAuthConfig)
        assert isinstance(stored.secrets, XaiOAuthSecrets)
        assert stored.config.status == "connected"
        assert stored.secrets.access_token == tokens.access_token
        assert stored.secrets.refresh_token == tokens.refresh_token
        assert stored.config.account_id == "new-account"
        assert stored.config.email == "new@example.invalid"
        assert stored.config.last_failure_reason is None
        assert stored.config.last_failed_at is None
        assert stored.config == success.value.config
        assert stored.secrets == success.value.secrets
        assert (
            stored.catalog_configuration_version
            == harness.integration.catalog_configuration_version
        )
        assert isinstance(harness.integration.config, XaiOAuthConfig)
        assert (
            stored.config.last_refreshed_at
            != harness.integration.config.last_refreshed_at
        )
        usable = await ensure_runtime_tokens(
            integration=stored,
            persistence_repository=harness.persistence,
            client_factory=_client_factory,
        )
        assert usable == Success(stored)
    finally:
        paused.resume.set()
        for task in (failure_task, success_task):
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
