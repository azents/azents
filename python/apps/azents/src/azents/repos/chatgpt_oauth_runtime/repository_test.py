"""Real PostgreSQL interleavings for ChatGPT OAuth refresh persistence."""

import asyncio
import datetime
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.workspace import RDBWorkspace
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
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


class _PausedIntegrationRepository(LLMProviderIntegrationRepository):
    """Pause a stale read or a locked read at an explicitly selected boundary."""

    def __init__(self, cipher: CredentialCipher, *, lock_before_pause: bool) -> None:
        super().__init__(cipher)
        self.lock_before_pause = lock_before_pause
        self.read_complete = asyncio.Event()
        self.resume = asyncio.Event()
        self.backend_pid: int | None = None

    async def get_by_id_with_secrets_for_update(
        self, session: AsyncSession, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Exercise identity-map refresh and actual PostgreSQL row serialization."""
        self.backend_pid = await session.scalar(sa.text("SELECT pg_backend_pid()"))
        if self.lock_before_pause:
            latest = await super().get_by_id_with_secrets_for_update(
                session, integration_id
            )
            self.read_complete.set()
            await self.resume.wait()
            return latest
        # Populate the identity map with stale data before the final locked reread.
        stale_row = await session.get(RDBLLMProviderIntegration, integration_id)
        assert stale_row is not None
        self.read_complete.set()
        await self.resume.wait()
        return await super().get_by_id_with_secrets_for_update(session, integration_id)

    async def get_by_id_with_secrets(
        self, session: AsyncSession, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Expose the old non-atomic read boundary for regression verification."""
        latest = await super().get_by_id_with_secrets(session, integration_id)
        self.read_complete.set()
        await self.resume.wait()
        return latest


@pytest.mark.parametrize("lock_before_pause", [False, True])
@pytest.mark.parametrize("rotate_refresh_token", [False, True])
@pytest.mark.parametrize(
    "error",
    [
        ProviderRejected(reason="invalid_grant"),
        ProviderUnavailable(reason="unavailable"),
    ],
)
async def test_refresh_failure_and_success_are_atomically_ordered(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    lock_before_pause: bool,
    rotate_refresh_token: bool,
    error: ProviderRejected | ProviderUnavailable,
) -> None:
    """A successful separate connection always wins over an old refresh failure."""

    @asynccontextmanager
    async def sessions() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            async with session.begin():
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
        failure_task = asyncio.create_task(
            _persist_refresh_failure(
                integration=original,
                persistence_repository=failure_persistence,
                error=error,
            )
        )
        await asyncio.wait_for(paused.read_complete.wait(), timeout=5)

        async def persist_success() -> Result[
            LLMProviderIntegrationWithSecrets, ProviderRejected
        ]:
            return await _persist_refresh_success(
                integration=original,
                persistence_repository=success_persistence,
                tokens=tokens,
            )

        success_task = asyncio.create_task(persist_success())
        if lock_before_pause:
            # Observe actual PostgreSQL blocking, not a sleep or scheduler yield.
            async with asyncio.timeout(5):
                async with AsyncSession(rdb_engine) as observer:
                    while not await observer.scalar(
                        sa.text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks "
                            "WHERE NOT granted AND :pid = ANY(pg_blocking_pids(pid)))"
                        ),
                        {"pid": paused.backend_pid},
                    ):
                        pass
            assert not success_task.done()
            paused.resume.set()
            assert await asyncio.wait_for(failure_task, timeout=5) is None
            success = await asyncio.wait_for(success_task, timeout=5)
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
        assert stored.secrets.access_token == tokens.access_token
        assert stored.secrets.refresh_token == tokens.refresh_token
        assert stored.config.status == ChatGPTOAuthConnectionStatus.CONNECTED.value
        assert stored.config.last_refreshed_at != now - datetime.timedelta(hours=1)
        assert stored.config.last_failure_reason is None
        assert stored.config.account_id == "new-account"
        assert stored.config.email == "new@example.invalid"
        assert stored.config.plan_type == "new-plan"
        assert stored.config == success.value.config
        assert (
            stored.catalog_configuration_version
            == original.catalog_configuration_version
        )
        usable = await ensure_runtime_tokens(
            integration=stored, persistence_repository=success_persistence
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
                await session.execute(
                    sa.delete(RDBLLMProviderIntegration).where(
                        RDBLLMProviderIntegration.workspace_id == workspace_id
                    )
                )
                await session.execute(
                    sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
                )
