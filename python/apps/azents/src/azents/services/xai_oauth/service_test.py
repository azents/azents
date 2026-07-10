"""xAI OAuth connection service tests."""

import uuid
from typing import cast

import httpx
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.xai_oauth_session import XaiOAuthSessionRepository

from . import XaiOAuthService
from .client import XaiOAuthClient

_TEST_KEY = Fernet.generate_key().decode()


class _SessionManager:
    """Expose a single test DB session as a context manager."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def __call__(self) -> "_SessionManager":
        return self

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


async def test_slow_down_increases_and_returns_poll_interval(
    rdb_session: AsyncSession,
) -> None:
    """Persist and expose every RFC 8628 slow_down interval increment."""
    suffix = uuid.uuid4().hex[:12]
    workspace_repo = WorkspaceRepository()
    workspace_result = await workspace_repo.create(
        rdb_session,
        WorkspaceCreate(
            name=f"xAI OAuth service {suffix}",
            handle=f"xai-oauth-service-{suffix}",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await workspace_repo.resolve_id(
        rdb_session,
        f"xai-oauth-service-{suffix}",
    )
    assert workspace_id is not None
    user = await UserRepository().create(
        rdb_session,
        UserCreate(email=f"xai-oauth-service-{suffix}@example.com"),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/device/code":
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code-123",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://auth.x.ai/activate",
                    "interval": 5,
                    "expires_in": 900,
                },
            )
        return httpx.Response(400, json={"error": "slow_down"})

    cipher = CredentialCipher(_TEST_KEY)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        service = XaiOAuthService(
            cast(SessionManager[AsyncSession], _SessionManager(rdb_session)),
            XaiOAuthSessionRepository(cipher),
            LLMProviderIntegrationRepository(cipher),
            XaiOAuthClient(http_client),
        )
        start = await service.start_device(
            workspace_id=workspace_id,
            user_id=user.id,
        )
        assert isinstance(start, Success)

        first = await service.poll_device(
            workspace_id=workspace_id,
            user_id=user.id,
            session_id=start.value.session_id,
        )
        second = await service.poll_device(
            workspace_id=workspace_id,
            user_id=user.id,
            session_id=start.value.session_id,
        )

    assert isinstance(first, Success)
    assert first.value.interval_seconds == 10
    assert isinstance(second, Success)
    assert second.value.interval_seconds == 15
