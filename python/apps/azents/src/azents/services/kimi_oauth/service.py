"""Kimi OAuth connection service."""

import datetime
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, assert_never

import httpx
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import KimiOAuthConfig, KimiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import LLMProvider
from azents.core.kimi_oauth import (
    KimiOAuthConnectionMethod,
    KimiOAuthConnectionStatus,
    KimiOAuthSessionStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.kimi_oauth_session.data import (
    KimiOAuthSessionCreate,
    KimiOAuthSessionWithSecrets,
)
from azents.repos.kimi_oauth_session.repository import KimiOAuthSessionRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationCreate

from .client import KimiOAuthClient
from .data import (
    InvalidSession,
    KimiOAuthDeviceStartOutput,
    KimiOAuthDeviceStatusOutput,
    KimiOAuthError,
    KimiOAuthExchangeOutput,
    ProviderPending,
    ProviderRejected,
    ProviderSlowDown,
    ProviderUnavailable,
    SessionNotFound,
    SessionTransitionFailed,
    TokenSet,
)

_SESSION_TTL = datetime.timedelta(minutes=15)
_SLOW_DOWN_INCREMENT_SECONDS = 5


async def _get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Create Kimi OAuth HTTP client and close it after request."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def _get_session_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> KimiOAuthSessionRepository:
    """Create Kimi OAuth session repository dependency."""
    return KimiOAuthSessionRepository(cipher)


def _get_integration_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> LLMProviderIntegrationRepository:
    """Create LLM provider integration repository dependency."""
    return LLMProviderIntegrationRepository(cipher)


def _get_client(
    http_client: Annotated[httpx.AsyncClient, Depends(_get_http_client)],
) -> KimiOAuthClient:
    """Create Kimi OAuth client dependency."""
    return KimiOAuthClient(http_client)


class KimiOAuthService:
    """Kimi OAuth device flow service."""

    def __init__(
        self,
        session_manager: Annotated[
            SessionManager[AsyncSession], Depends(get_session_manager)
        ],
        session_repo: Annotated[KimiOAuthSessionRepository, Depends(_get_session_repo)],
        integration_repo: Annotated[
            LLMProviderIntegrationRepository, Depends(_get_integration_repo)
        ],
        client: Annotated[KimiOAuthClient, Depends(_get_client)],
    ) -> None:
        """Inject service dependencies."""
        self.session_manager = session_manager
        self.session_repository = session_repo
        self.integration_repository = integration_repo
        self.client = client

    async def start_device(
        self, *, workspace_id: str, user_id: str
    ) -> Result[
        KimiOAuthDeviceStartOutput,
        ProviderRejected | ProviderUnavailable,
    ]:
        """Start Device OAuth flow."""
        device_id = uuid.uuid4().hex
        code_result = await self.client.request_device_user_code(device_id=device_id)
        match code_result:
            case Success(user_code):
                expires_at = datetime.datetime.now(datetime.UTC) + min(
                    _SESSION_TTL,
                    datetime.timedelta(seconds=user_code.expires_in_seconds),
                )
                async with self.session_manager() as session:
                    created = await self.session_repository.create(
                        session,
                        KimiOAuthSessionCreate(
                            workspace_id=workspace_id,
                            user_id=user_id,
                            method=KimiOAuthConnectionMethod.DEVICE,
                            device_code=user_code.device_code,
                            device_id=device_id,
                            user_code=user_code.user_code,
                            verification_uri=user_code.verification_uri,
                            interval_seconds=user_code.interval_seconds,
                            expires_at=expires_at,
                        ),
                    )
                return Success(
                    KimiOAuthDeviceStartOutput(
                        session_id=created.id,
                        user_code=user_code.user_code,
                        verification_uri=user_code.verification_uri,
                        interval_seconds=user_code.interval_seconds,
                        expires_at=expires_at,
                    )
                )
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(code_result)

    async def poll_device(
        self, *, workspace_id: str, user_id: str, session_id: str
    ) -> Result[KimiOAuthDeviceStatusOutput, KimiOAuthError]:
        """Check Device authentication completion once."""
        session_result = await self._get_owned_pending_session(
            workspace_id=workspace_id,
            user_id=user_id,
            session_id=session_id,
            expected_method=KimiOAuthConnectionMethod.DEVICE,
        )
        match session_result:
            case Success(oauth_session):
                poll_result = await self.client.poll_device_tokens(
                    device_code=oauth_session.device_code,
                    device_id=oauth_session.device_id,
                    connection_method=KimiOAuthConnectionMethod.DEVICE,
                )
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(session_result)

        match poll_result:
            case Success(tokens):
                save_result = await self._save_tokens(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    device_id=oauth_session.device_id,
                    tokens_result=Success(tokens),
                )
                match save_result:
                    case Success(output):
                        return Success(
                            KimiOAuthDeviceStatusOutput(
                                session_id=session_id,
                                status=KimiOAuthSessionStatus.CONNECTED,
                                interval_seconds=oauth_session.interval_seconds,
                                integration=output.integration,
                            )
                        )
                    case Failure(error):
                        return Failure(error)
                    case _:
                        assert_never(save_result)
            case Failure(ProviderPending()):
                return Success(
                    KimiOAuthDeviceStatusOutput(
                        session_id=session_id,
                        status=KimiOAuthSessionStatus.PENDING,
                        interval_seconds=oauth_session.interval_seconds,
                    )
                )
            case Failure(ProviderSlowDown()):
                async with self.session_manager() as session:
                    interval_result = (
                        await self.session_repository.increase_poll_interval(
                            session,
                            session_id,
                            seconds=_SLOW_DOWN_INCREMENT_SECONDS,
                        )
                    )
                match interval_result:
                    case Success(value):
                        return Success(
                            KimiOAuthDeviceStatusOutput(
                                session_id=session_id,
                                status=KimiOAuthSessionStatus.PENDING,
                                interval_seconds=value.interval_seconds,
                            )
                        )
                    case Failure():
                        return Failure(SessionTransitionFailed(session_id=session_id))
                    case _:
                        assert_never(interval_result)
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(poll_result)

    async def cancel_device(
        self, *, workspace_id: str, user_id: str, session_id: str
    ) -> Result[KimiOAuthDeviceStatusOutput, KimiOAuthError]:
        """Cancel Device OAuth session."""
        check = await self._get_owned_pending_session(
            workspace_id=workspace_id,
            user_id=user_id,
            session_id=session_id,
            expected_method=KimiOAuthConnectionMethod.DEVICE,
        )
        if isinstance(check, Failure):
            return Failure(check.error)
        async with self.session_manager() as session:
            result = await self.session_repository.cancel(session, session_id)
        match result:
            case Success(value):
                return Success(
                    KimiOAuthDeviceStatusOutput(
                        session_id=value.id,
                        status=value.status,
                        interval_seconds=value.interval_seconds,
                    )
                )
            case Failure():
                return Failure(SessionTransitionFailed(session_id=session_id))
            case _:
                assert_never(result)

    async def _get_owned_pending_session(
        self,
        *,
        workspace_id: str,
        user_id: str,
        session_id: str,
        expected_method: KimiOAuthConnectionMethod,
    ) -> Result[KimiOAuthSessionWithSecrets, SessionNotFound | InvalidSession]:
        """Fetch pending session belonging to requesting user and workspace."""
        async with self.session_manager() as session:
            oauth_session = await self.session_repository.get_by_id_with_secrets(
                session, session_id
            )
        if oauth_session is None:
            return Failure(SessionNotFound(session_id=session_id))
        if (
            oauth_session.workspace_id != workspace_id
            or oauth_session.user_id != user_id
            or oauth_session.method != expected_method
            or oauth_session.status != KimiOAuthSessionStatus.PENDING
            or oauth_session.expires_at <= datetime.datetime.now(datetime.UTC)
        ):
            return Failure(InvalidSession(reason="OAuth session is not valid"))
        return Success(oauth_session)

    async def _save_tokens(
        self,
        *,
        workspace_id: str,
        session_id: str,
        device_id: str,
        tokens_result: Result[TokenSet, ProviderRejected | ProviderUnavailable],
    ) -> Result[KimiOAuthExchangeOutput, KimiOAuthError]:
        """Consume Session and store token in integration."""
        match tokens_result:
            case Success(tokens):
                now = datetime.datetime.now(datetime.UTC)
                secrets = KimiOAuthSecrets(
                    access_token=tokens.access_token,
                    refresh_token=tokens.refresh_token,
                    expires_at=tokens.expires_at,
                    device_id=device_id,
                )
                config = KimiOAuthConfig(
                    connection_method=tokens.connection_method.value,
                    status=KimiOAuthConnectionStatus.CONNECTED.value,
                    connected_at=now,
                    last_refreshed_at=now,
                    last_failed_at=None,
                    last_failure_reason=None,
                )
                async with self.session_manager() as session:
                    consume_result = await self.session_repository.consume(
                        session, session_id
                    )
                    if isinstance(consume_result, Failure):
                        return Failure(SessionTransitionFailed(session_id=session_id))
                    integrations = await self.integration_repository.list_by_workspace(
                        session, workspace_id
                    )
                    existing = next(
                        (
                            item
                            for item in integrations.items
                            if item.provider == LLMProvider.KIMI_OAUTH
                        ),
                        None,
                    )
                    if existing is None:
                        integration = await self.integration_repository.create(
                            session,
                            LLMProviderIntegrationCreate(
                                workspace_id=workspace_id,
                                provider=LLMProvider.KIMI_OAUTH,
                                name="Kimi subscription",
                                secrets=secrets,
                                config=config,
                            ),
                        )
                    else:
                        update_result = await self.integration_repository.update_by_id(
                            session,
                            existing.id,
                            {"secrets": secrets, "config": config},
                        )
                        match update_result:
                            case Success(integration):
                                pass
                            case Failure():
                                return Failure(
                                    SessionTransitionFailed(session_id=session_id)
                                )
                            case _:
                                assert_never(update_result)
                return Success(KimiOAuthExchangeOutput(integration=integration))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(tokens_result)
