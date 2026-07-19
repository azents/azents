"""Kimi OAuth connection service tests."""

import datetime
import uuid
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs

import httpx
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import KimiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import LLMProvider
from azents.core.kimi_oauth import (
    KimiOAuthConnectionMethod,
    KimiOAuthSessionStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.kimi_oauth_session.data import KimiOAuthSessionWithSecrets
from azents.repos.kimi_oauth_session.repository import KimiOAuthSessionRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegration,
    LLMProviderIntegrationList,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

from .client import KimiOAuthClient
from .data import TokenSet
from .service import KimiOAuthService

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


async def test_reconnect_replaces_existing_integration_credentials() -> None:
    """Update an existing Kimi integration instead of creating a duplicate."""
    now = datetime.datetime.now(datetime.UTC)
    existing = LLMProviderIntegration(
        id="integration-kimi",
        workspace_id="workspace-1",
        provider=LLMProvider.KIMI_OAUTH,
        name="Team Kimi subscription",
        config=None,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    oauth_session = KimiOAuthSessionWithSecrets(
        id="session-2",
        workspace_id="workspace-1",
        user_id="user-1",
        method=KimiOAuthConnectionMethod.DEVICE,
        user_code="KIMI-2",
        verification_uri="https://auth.kimi.com/device",
        interval_seconds=5,
        status=KimiOAuthSessionStatus.PENDING,
        expires_at=now + datetime.timedelta(minutes=15),
        created_at=now,
        updated_at=now,
        device_code="device-code-2",
        device_id="device-2",
    )
    session_repo = MagicMock(spec=KimiOAuthSessionRepository)
    session_repo.get_by_id_with_secrets = AsyncMock(return_value=oauth_session)
    session_repo.consume = AsyncMock(return_value=Success(object()))
    list_by_workspace = AsyncMock(
        return_value=LLMProviderIntegrationList(items=[existing])
    )
    update_by_id = AsyncMock(return_value=Success(existing))
    create = AsyncMock()
    integration_repo = MagicMock(spec=LLMProviderIntegrationRepository)
    integration_repo.list_by_workspace = list_by_workspace
    integration_repo.update_by_id = update_by_id
    integration_repo.create = create
    client = MagicMock(spec=KimiOAuthClient)
    client.poll_device_tokens = AsyncMock(
        return_value=Success(
            TokenSet(
                access_token="access-2",
                refresh_token="refresh-2",
                expires_at=now + datetime.timedelta(hours=1),
                connection_method=KimiOAuthConnectionMethod.DEVICE,
            )
        )
    )
    service = KimiOAuthService(
        cast(
            SessionManager[AsyncSession],
            _SessionManager(cast(AsyncSession, object())),
        ),
        cast(KimiOAuthSessionRepository, session_repo),
        cast(LLMProviderIntegrationRepository, integration_repo),
        cast(KimiOAuthClient, client),
    )

    result = await service.poll_device(
        workspace_id="workspace-1",
        user_id="user-1",
        session_id="session-2",
    )

    assert isinstance(result, Success)
    assert result.value.integration is not None
    assert result.value.integration.id == existing.id
    create.assert_not_awaited()
    update_by_id.assert_awaited_once()
    assert update_by_id.await_args is not None
    _, integration_id, update = update_by_id.await_args.args
    assert integration_id == existing.id
    secrets = update["secrets"]
    assert isinstance(secrets, KimiOAuthSecrets)
    assert secrets.access_token == "access-2"
    assert secrets.refresh_token == "refresh-2"
    assert secrets.device_id == "device-2"


async def test_slow_down_increases_and_returns_poll_interval(
    rdb_session: AsyncSession,
) -> None:
    """Persist and expose every RFC 8628 slow_down interval increment."""
    suffix = uuid.uuid4().hex[:12]
    workspace_repo = WorkspaceRepository()
    workspace_result = await workspace_repo.create(
        rdb_session,
        WorkspaceCreate(
            name=f"Kimi OAuth service {suffix}",
            handle=f"kimi-oauth-service-{suffix}",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await workspace_repo.resolve_id(
        rdb_session,
        f"kimi-oauth-service-{suffix}",
    )
    assert workspace_id is not None
    user = await UserRepository().create(
        rdb_session,
        UserCreate(email=f"kimi-oauth-service-{suffix}@example.com"),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/oauth/device_authorization":
            assert request.headers["X-Msh-Device-Id"]
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code-123",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://auth.kimi.com/device",
                    "verification_uri_complete": (
                        "https://auth.kimi.com/device?user_code=ABCD-EFGH"
                    ),
                    "interval": 5,
                    "expires_in": 900,
                },
            )
        assert request.url.path == "/api/oauth/token"
        assert request.headers["X-Msh-Device-Id"]
        return httpx.Response(400, json={"error": "slow_down"})

    cipher = CredentialCipher(_TEST_KEY)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        service = KimiOAuthService(
            cast(SessionManager[AsyncSession], _SessionManager(rdb_session)),
            KimiOAuthSessionRepository(cipher),
            LLMProviderIntegrationRepository(cipher),
            KimiOAuthClient(http_client),
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


async def test_reconnect_updates_existing_integration(
    rdb_session: AsyncSession,
) -> None:
    """Replace encrypted credentials while preserving integration identity and alias."""
    suffix = uuid.uuid4().hex[:12]
    workspace_repo = WorkspaceRepository()
    workspace_result = await workspace_repo.create(
        rdb_session,
        WorkspaceCreate(
            name=f"Kimi OAuth reconnect {suffix}",
            handle=f"kimi-oauth-reconnect-{suffix}",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await workspace_repo.resolve_id(
        rdb_session,
        f"kimi-oauth-reconnect-{suffix}",
    )
    assert workspace_id is not None
    user = await UserRepository().create(
        rdb_session,
        UserCreate(email=f"kimi-oauth-reconnect-{suffix}@example.com"),
    )
    device_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal device_requests
        if request.url.path == "/api/oauth/device_authorization":
            device_requests += 1
            return httpx.Response(
                200,
                json={
                    "device_code": f"device-code-{device_requests}",
                    "user_code": f"KIMI-{device_requests}",
                    "verification_uri": "https://auth.kimi.com/device",
                    "interval": 5,
                    "expires_in": 900,
                },
            )
        assert request.url.path == "/api/oauth/token"
        body = parse_qs(request.content.decode())
        device_code = body["device_code"][0]
        return httpx.Response(
            200,
            json={
                "access_token": f"access-{device_code}",
                "refresh_token": f"refresh-{device_code}",
                "expires_in": 3600,
            },
        )

    cipher = CredentialCipher(_TEST_KEY)
    integration_repo = LLMProviderIntegrationRepository(cipher)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = KimiOAuthService(
            cast(SessionManager[AsyncSession], _SessionManager(rdb_session)),
            KimiOAuthSessionRepository(cipher),
            integration_repo,
            KimiOAuthClient(client),
        )

        first_start = await service.start_device(
            workspace_id=workspace_id,
            user_id=user.id,
        )
        assert isinstance(first_start, Success)
        first_poll = await service.poll_device(
            workspace_id=workspace_id,
            user_id=user.id,
            session_id=first_start.value.session_id,
        )
        assert isinstance(first_poll, Success)
        assert first_poll.value.integration is not None
        first_integration_id = first_poll.value.integration.id
        first_with_secrets = await integration_repo.get_by_id_with_secrets(
            rdb_session, first_integration_id
        )
        assert first_with_secrets is not None
        assert isinstance(first_with_secrets.secrets, KimiOAuthSecrets)
        first_device_id = first_with_secrets.secrets.device_id

        alias_result = await integration_repo.update_by_id(
            rdb_session,
            first_integration_id,
            {"name": "Team Kimi subscription"},
        )
        assert isinstance(alias_result, Success)

        second_start = await service.start_device(
            workspace_id=workspace_id,
            user_id=user.id,
        )
        assert isinstance(second_start, Success)
        second_poll = await service.poll_device(
            workspace_id=workspace_id,
            user_id=user.id,
            session_id=second_start.value.session_id,
        )

    assert isinstance(second_poll, Success)
    assert second_poll.value.integration is not None
    assert second_poll.value.integration.id == first_integration_id
    assert second_poll.value.integration.name == "Team Kimi subscription"
    integrations = await integration_repo.list_by_workspace(rdb_session, workspace_id)
    kimi_integrations = [
        item for item in integrations.items if item.provider == LLMProvider.KIMI_OAUTH
    ]
    assert len(kimi_integrations) == 1
    refreshed = await integration_repo.get_by_id_with_secrets(
        rdb_session, first_integration_id
    )
    assert refreshed is not None
    assert isinstance(refreshed.secrets, KimiOAuthSecrets)
    assert refreshed.secrets.access_token == "access-device-code-2"
    assert refreshed.secrets.refresh_token == "refresh-device-code-2"
    assert refreshed.secrets.device_id != first_device_id
