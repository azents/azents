"""ChatGPTOAuthService tests."""

import datetime
import uuid
from typing import cast

from azcommon.result import Failure, Result, Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.chatgpt_oauth import (
    ChatGPTOAuthConnectionMethod,
    ChatGPTOAuthSessionStatus,
)
from azents.core.crypto import CredentialCipher
from azents.core.enums import LLMCatalogScope
from azents.rdb.session import SessionManager
from azents.repos.chatgpt_oauth_session import ChatGPTOAuthSessionRepository
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

from . import ChatGPTOAuthService
from .client import ChatGPTOAuthClient
from .data import (
    DeviceAuthorizationCode,
    DeviceUserCode,
    ProviderPending,
    ProviderRejected,
    ProviderUnavailable,
    TokenSet,
)

_TEST_KEY = Fernet.generate_key().decode()


class _SessionManager:
    """Expose single test DB session as context manager."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> "_SessionManager":
        return self

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeClient:
    """Provider client test double."""

    def __init__(self) -> None:
        self.token_result: Result[TokenSet, ProviderRejected | ProviderUnavailable] = (
            Success(
                TokenSet(
                    access_token="access-token",
                    refresh_token="refresh-token",
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                    account_id="account-123",
                    email="user@example.com",
                    plan_type="plus",
                    connection_method=ChatGPTOAuthConnectionMethod.DEVICE,
                )
            )
        )
        self.device_code_result: Result[
            DeviceUserCode, ProviderRejected | ProviderUnavailable
        ] = Success(
            DeviceUserCode(
                device_auth_id="device-auth-123",
                user_code="ABCD-EFGH",
                interval_seconds=5,
            )
        )
        self.poll_result: Result[
            DeviceAuthorizationCode,
            ProviderPending | ProviderRejected | ProviderUnavailable,
        ] = Failure(ProviderPending(session_id="device-auth-123"))

    async def request_device_user_code(
        self,
    ) -> Result[DeviceUserCode, ProviderRejected | ProviderUnavailable]:
        """Return Device user-code result."""
        return self.device_code_result

    async def poll_device_authorization_code(
        self, *, device_auth_id: str, user_code: str
    ) -> Result[
        DeviceAuthorizationCode,
        ProviderPending | ProviderRejected | ProviderUnavailable,
    ]:
        """Return Device polling result."""
        assert device_auth_id == "device-auth-123"
        assert user_code == "ABCD-EFGH"
        return self.poll_result

    async def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        connection_method: ChatGPTOAuthConnectionMethod,
    ) -> Result[TokenSet, ProviderRejected | ProviderUnavailable]:
        """Return Token exchange result."""
        assert code
        assert code_verifier
        assert redirect_uri
        if isinstance(self.token_result, Success):
            self.token_result.value.connection_method = connection_method
        return self.token_result


async def _create_workspace(session: AsyncSession) -> str:
    """Create workspace for tests."""
    suffix = uuid.uuid4().hex[:12]
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(
            name=f"ChatGPT OAuth Service WS {suffix}", handle=f"cgpt-oauth-svc-{suffix}"
        ),
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, f"cgpt-oauth-svc-{suffix}")
    assert workspace_id is not None
    return workspace_id


async def _create_user(session: AsyncSession) -> str:
    """Create user for tests."""
    email = f"chatgpt-oauth-service-{uuid.uuid4().hex}@example.com"
    user = await UserRepository().create(session, UserCreate(email=email))
    return user.id


def _make_service(
    rdb_session: AsyncSession, fake_client: _FakeClient
) -> ChatGPTOAuthService:
    """Create service for tests."""
    cipher = CredentialCipher(_TEST_KEY)
    return ChatGPTOAuthService(
        session_manager=cast(
            SessionManager[AsyncSession], _SessionManager(rdb_session)
        ),
        session_repo=ChatGPTOAuthSessionRepository(cipher),
        integration_repo=LLMProviderIntegrationRepository(cipher),
        catalog_repo=LLMCatalogRepository(),
        client=cast(ChatGPTOAuthClient, fake_client),
    )


class TestChatGPTOAuthService:
    """ChatGPTOAuthService tests."""

    async def test_device_start_pending_success_and_cancel(
        self, rdb_session: AsyncSession
    ) -> None:
        """Handle Device flow pending, success, and cancel states."""
        workspace_id = await _create_workspace(rdb_session)
        user_id = await _create_user(rdb_session)
        fake_client = _FakeClient()
        service = _make_service(rdb_session, fake_client)

        started = await service.start_device(workspace_id=workspace_id, user_id=user_id)
        assert isinstance(started, Success)
        pending = await service.poll_device(
            workspace_id=workspace_id,
            user_id=user_id,
            session_id=started.value.session_id,
        )
        fake_client.poll_result = Success(
            DeviceAuthorizationCode(
                authorization_code="authorization-code",
                code_verifier="device-code-verifier",
            )
        )
        connected = await service.poll_device(
            workspace_id=workspace_id,
            user_id=user_id,
            session_id=started.value.session_id,
        )
        other_started = await service.start_device(
            workspace_id=workspace_id, user_id=user_id
        )
        assert isinstance(other_started, Success)
        cancelled = await service.cancel_device(
            workspace_id=workspace_id,
            user_id=user_id,
            session_id=other_started.value.session_id,
        )

        assert isinstance(pending, Success)
        assert pending.value.status == ChatGPTOAuthSessionStatus.PENDING
        assert isinstance(connected, Success)
        assert connected.value.status == ChatGPTOAuthSessionStatus.CONNECTED
        assert connected.value.integration is not None
        catalog = await LLMCatalogRepository().get_by_integration(
            rdb_session,
            integration_id=connected.value.integration.id,
            workspace_id=workspace_id,
        )
        assert catalog is not None
        assert catalog.scope == LLMCatalogScope.INTEGRATION
        assert isinstance(cancelled, Success)
        assert cancelled.value.status == ChatGPTOAuthSessionStatus.CANCELLED
