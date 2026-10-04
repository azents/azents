"""Real PostgreSQL interleavings for ChatGPT OAuth refresh persistence."""

import asyncio
import datetime
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import sqlalchemy as sa
from azcommon.result import Result, Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.chatgpt_oauth import (
    ChatGPTOAuthConnectionMethod,
    ChatGPTOAuthConnectionStatus,
)
from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import LLMProvider
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.workspace import WorkspaceRepository
from azents.services.chatgpt_oauth.client import ChatGPTOAuthClient
from azents.services.chatgpt_oauth.data import (
    ProviderRejected,
    ProviderUnavailable,
    TokenSet,
)
from azents.services.chatgpt_oauth.runtime import (
    _persist_refresh_failure,
    _persist_refresh_success,
    ensure_runtime_tokens,
)


def _unexpected_http(_request: httpx.Request) -> httpx.Response:
    """Fail if a freshness regression attempts provider HTTP in a race fixture."""
    raise AssertionError("OAuth race fixtures must not perform external HTTP")


@asynccontextmanager
async def _client_factory() -> AsyncIterator[ChatGPTOAuthClient]:
    """Provide a typed client whose transport cannot leave the test process."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_unexpected_http), timeout=20.0
    ) as client:
        yield ChatGPTOAuthClient(
            client, token_url="https://oauth.example.invalid/token"
        )


class _PausedIntegrationRepository(LLMProviderIntegrationRepository):
    """Pause a stale read or a locked read at an explicitly selected boundary."""

    def __init__(self, cipher: CredentialCipher, *, lock_before_pause: bool) -> None:
        super().__init__(cipher)
        self.lock_before_pause = lock_before_pause
        self.read_complete = asyncio.Event()
        self.resume = asyncio.Event()
        self.backend_pid: int | None = None

    async def get_by_id_with_secrets_for_update(
        self, session: WriteSession, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Exercise identity-map refresh and actual PostgreSQL row serialization."""
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
        # Populate the identity map with stale data before the final locked reread.
        stale_row = await session.read_session.get(
            RDBLLMProviderIntegration, integration_id
        )
        assert stale_row is not None
        self.read_complete.set()
        await self.resume.wait()
        return await super().get_by_id_with_secrets_for_update(session, integration_id)

    async def get_by_id_with_secrets(
        self, session: ReadSession, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Expose the old non-atomic read boundary for regression verification."""
        latest = await super().get_by_id_with_secrets(session, integration_id)
        self.read_complete.set()
        await self.resume.wait()
        return latest


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
    ],
)
async def test_superseded_refresh_preserves_complete_current_integration(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    change_kind: str,
    error: ProviderRejected | ProviderUnavailable | None,
) -> None:
    """Committed reconnect or runtime updates fence both stale persistence paths."""

    @asynccontextmanager
    async def sessions() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as _raw_session:
            session = ReadWriteSession(_raw_session)
            async with session.write_session.begin():
                yield session

    repository = LLMProviderIntegrationRepository(
        CredentialCipher(Fernet.generate_key().decode())
    )
    persistence = ChatGPTOAuthRuntimeRepository(repository, sessions)
    now = datetime.datetime.now(datetime.UTC)
    workspace_id: str | None = None
    try:
        async with sessions() as session:
            workspace = await WorkspaceRepository().create(
                session,
                WorkspaceCreate(
                    name="OAuth identity fence",
                    handle=f"oauth-fence-{uuid.uuid4().hex}",
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
                    provider=LLMProvider.CHATGPT_OAUTH,
                    name="OAuth identity fence",
                    secrets=ChatGPTOAuthSecrets(
                        access_token="original-access",
                        refresh_token="shared-refresh",
                        expires_at=now + datetime.timedelta(minutes=1),
                    ),
                    config=ChatGPTOAuthConfig(
                        account_id="original-account",
                        connection_method=ChatGPTOAuthConnectionMethod.CALLBACK.value,
                        status="connected",
                        connected_at=now,
                        last_refreshed_at=now,
                    ),
                ),
            )
        original = await persistence.load_integration(integration_id=created.id)
        assert original is not None
        assert isinstance(original.secrets, ChatGPTOAuthSecrets)
        assert isinstance(original.config, ChatGPTOAuthConfig)
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
        async with sessions() as session:
            if change_kind == "user_reconnect":
                update = await repository.update_by_id(
                    session, original.id, {"secrets": secrets, "config": config}
                )
            elif change_kind == "user_config":
                update = await repository.update_by_id(
                    session, original.id, {"config": config}
                )
            elif change_kind == "runtime_credentials":
                update = await repository.update_runtime_state_by_id(
                    session, original.id, {"secrets": secrets}
                )
            else:
                update = await repository.update_runtime_state_by_id(
                    session,
                    original.id,
                    {
                        "config": original.config.model_copy(
                            update={
                                "last_refreshed_at": now + datetime.timedelta(seconds=1)
                            }
                        )
                    },
                )
            assert isinstance(update, Success)
        latest = await persistence.load_integration(integration_id=original.id)
        assert latest is not None
        assert latest.catalog_configuration_version == (
            original.catalog_configuration_version
            + (1 if change_kind.startswith("user_") else 0)
        )
        if error is None:
            result = await _persist_refresh_success(
                integration=original,
                persistence_repository=persistence,
                tokens=TokenSet(
                    access_token="stale-refreshed-access",
                    refresh_token="shared-refresh",
                    id_token="stale-refreshed-id",
                    expires_at=now + datetime.timedelta(hours=1),
                    connection_method=ChatGPTOAuthConnectionMethod.CALLBACK,
                ),
            )
            assert isinstance(result, Success)
            recovered = result.value
        else:
            recovered = await _persist_refresh_failure(
                integration=original,
                persistence_repository=persistence,
                error=error,
            )
        assert recovered == latest
        stored = await persistence.load_integration(integration_id=original.id)
        assert stored == latest
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


@pytest.mark.parametrize("lock_before_pause", [False, True])
@pytest.mark.parametrize("rotate_refresh_token", [False, True])
@pytest.mark.parametrize(
    "error",
    [
        None,
        ProviderRejected(reason="invalid_grant"),
        ProviderUnavailable(reason="unavailable"),
    ],
)
async def test_refresh_completions_are_atomically_ordered(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    lock_before_pause: bool,
    rotate_refresh_token: bool,
    error: ProviderRejected | ProviderUnavailable | None,
) -> None:
    """The first successful identity wins; state-only failure can be repaired."""

    @asynccontextmanager
    async def sessions() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as _raw_session:
            session = ReadWriteSession(_raw_session)
            async with session.write_session.begin():
                yield session

    cipher = CredentialCipher(Fernet.generate_key().decode())
    repository = LLMProviderIntegrationRepository(cipher)
    paused = _PausedIntegrationRepository(cipher, lock_before_pause=lock_before_pause)
    failure_persistence = ChatGPTOAuthRuntimeRepository(paused, sessions)
    success_persistence = ChatGPTOAuthRuntimeRepository(repository, sessions)
    now = datetime.datetime.now(datetime.UTC)
    workspace_id: str | None = None
    failure_task: asyncio.Task[LLMProviderIntegrationWithSecrets | None] | None = None
    success_task: (
        asyncio.Task[Result[LLMProviderIntegrationWithSecrets, ProviderRejected]] | None
    ) = None
    try:
        async with sessions() as session:
            workspace = await WorkspaceRepository().create(
                session,
                WorkspaceCreate(
                    name="OAuth race", handle=f"oauth-race-{uuid.uuid4().hex}"
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
                    provider=LLMProvider.CHATGPT_OAUTH,
                    name="OAuth race",
                    secrets=ChatGPTOAuthSecrets(
                        access_token="synthetic-old-access",
                        refresh_token="synthetic-old-refresh",
                        expires_at=now + datetime.timedelta(minutes=1),
                    ),
                    config=ChatGPTOAuthConfig(
                        account_id="old-account",
                        email="old@example.invalid",
                        plan_type="old-plan",
                        connection_method=ChatGPTOAuthConnectionMethod.CALLBACK.value,
                        status=ChatGPTOAuthConnectionStatus.CONNECTED.value,
                        connected_at=now,
                        last_refreshed_at=now - datetime.timedelta(hours=1),
                    ),
                ),
            )
            original = await repository.get_by_id_with_secrets(session, created.id)
            assert original is not None
        tokens = TokenSet(
            access_token="synthetic-new-access",
            refresh_token=(
                "synthetic-new-refresh"
                if rotate_refresh_token
                else "synthetic-old-refresh"
            ),
            expires_at=now + datetime.timedelta(hours=1),
            account_id="new-account",
            email="new@example.invalid",
            plan_type="new-plan",
            connection_method=ChatGPTOAuthConnectionMethod.CALLBACK,
        )
        success_tokens = (
            tokens.model_copy(
                update={"access_token": "competing-access", "id_token": "competing-id"}
            )
            if error is None
            else tokens
        )

        async def persist_paused() -> LLMProviderIntegrationWithSecrets | None:
            if error is None:
                paused_success = await _persist_refresh_success(
                    integration=original,
                    persistence_repository=failure_persistence,
                    tokens=tokens,
                )
                assert isinstance(paused_success, Success)
                return paused_success.value
            return await _persist_refresh_failure(
                integration=original,
                persistence_repository=failure_persistence,
                error=error,
            )

        failure_task = asyncio.create_task(persist_paused())
        await asyncio.wait_for(paused.read_complete.wait(), timeout=5)

        async def persist_success() -> Result[
            LLMProviderIntegrationWithSecrets, ProviderRejected
        ]:
            return await _persist_refresh_success(
                integration=original,
                persistence_repository=success_persistence,
                tokens=success_tokens,
            )

        success_task = asyncio.create_task(persist_success())
        if lock_before_pause:
            # Observe actual PostgreSQL blocking, not a sleep or scheduler yield.
            async with asyncio.timeout(5):
                async with AsyncSession(rdb_engine) as _raw_observer:
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
            paused_result = await asyncio.wait_for(failure_task, timeout=5)
            if error is None:
                assert paused_result is not None
            else:
                assert paused_result is None
            success = await asyncio.wait_for(success_task, timeout=5)
            if paused_result is not None:
                assert isinstance(success, Success)
                assert success.value == paused_result
        else:
            success = await asyncio.wait_for(success_task, timeout=5)
            paused.resume.set()
            recovered = await asyncio.wait_for(failure_task, timeout=5)
            assert recovered is not None
            assert isinstance(success, Success)
            assert recovered.secrets == success.value.secrets
            assert recovered.config == success.value.config
        assert isinstance(success, Success)
        stored = await success_persistence.load_integration(integration_id=original.id)
        assert stored is not None
        assert isinstance(stored.secrets, ChatGPTOAuthSecrets)
        assert isinstance(stored.config, ChatGPTOAuthConfig)
        expected_tokens = (
            tokens if error is None and lock_before_pause else success_tokens
        )
        assert stored.secrets.access_token == expected_tokens.access_token
        assert stored.secrets.refresh_token == expected_tokens.refresh_token
        assert stored.secrets.id_token == expected_tokens.id_token
        assert stored.secrets.expires_at == expected_tokens.expires_at
        assert stored.config.status == ChatGPTOAuthConnectionStatus.CONNECTED.value
        assert stored.config.last_refreshed_at != now - datetime.timedelta(hours=1)
        assert stored.config.last_failure_reason is None
        assert stored.config.account_id == "new-account"
        assert stored.config.email == "new@example.invalid"
        assert stored.config.plan_type == "new-plan"
        assert stored.config == success.value.config
        assert stored.secrets == success.value.secrets
        assert (
            stored.catalog_configuration_version
            == original.catalog_configuration_version
        )
        usable = await ensure_runtime_tokens(
            integration=stored,
            persistence_repository=success_persistence,
            client_factory=_client_factory,
        )
        assert isinstance(usable, Success)
        assert usable.value.secrets == stored.secrets
    finally:
        paused.resume.set()
        for task in (failure_task, success_task):
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
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
