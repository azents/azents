"""xAI OAuth connection service."""

import datetime
from collections.abc import AsyncIterator
from typing import Annotated, assert_never

import httpx
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.config import XaiOAuthConfig as XaiOAuthProviderConfig
from azents.core.credentials import XaiOAuthConfig, XaiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_config, get_credential_cipher
from azents.core.enums import LLMProvider
from azents.core.xai_oauth import (
    XaiOAuthConnectionMethod,
    XaiOAuthConnectionStatus,
    XaiOAuthSessionStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationCreate
from azents.repos.xai_oauth_session import XaiOAuthSessionRepository
from azents.repos.xai_oauth_session.data import (
    XaiOAuthSessionCreate,
    XaiOAuthSessionWithSecrets,
)

from .client import XaiOAuthClient
from .data import (
    InvalidSession,
    ProviderDisabled,
    ProviderEntitlementDenied,
    ProviderPending,
    ProviderRejected,
    ProviderUnavailable,
    SessionNotFound,
    SessionTransitionFailed,
    TokenSet,
    XaiOAuthDeviceStartOutput,
    XaiOAuthDeviceStatusOutput,
    XaiOAuthError,
    XaiOAuthExchangeOutput,
)

_SESSION_TTL = datetime.timedelta(minutes=15)


async def _get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Create xAI OAuth HTTP client and close it after request."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def _get_session_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> XaiOAuthSessionRepository:
    """Create xAI OAuth session repository dependency."""
    return XaiOAuthSessionRepository(cipher)


def _get_integration_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> LLMProviderIntegrationRepository:
    """Create LLM provider integration repository dependency."""
    return LLMProviderIntegrationRepository(cipher)


def _get_xai_oauth_config(
    config: Annotated[Config, Depends(get_config)],
) -> XaiOAuthProviderConfig:
    """Return xAI OAuth provider config."""
    return config.xai_oauth


def _get_client(
    http_client: Annotated[httpx.AsyncClient, Depends(_get_http_client)],
    config: Annotated[XaiOAuthProviderConfig, Depends(_get_xai_oauth_config)],
) -> XaiOAuthClient | None:
    """Create xAI OAuth client dependency when the provider is configured."""
    client_id = _optional_client_id(config)
    if client_id is None:
        return None
    return XaiOAuthClient(http_client, client_id=client_id)


def _optional_client_id(config: XaiOAuthProviderConfig) -> str | None:
    """Return configured xAI OAuth client id when the provider is available."""
    if not config.enabled:
        return None
    if config.client_id is None or not config.client_id.strip():
        return None
    return config.client_id.strip()


class XaiOAuthService:
    """xAI OAuth device flow service."""

    def __init__(
        self,
        session_manager: Annotated[
            SessionManager[AsyncSession], Depends(get_session_manager)
        ],
        session_repo: Annotated[XaiOAuthSessionRepository, Depends(_get_session_repo)],
        integration_repo: Annotated[
            LLMProviderIntegrationRepository, Depends(_get_integration_repo)
        ],
        client: Annotated[XaiOAuthClient | None, Depends(_get_client)],
    ) -> None:
        """Inject service dependencies."""
        self._session_manager = session_manager
        self._session_repo = session_repo
        self._integration_repo = integration_repo
        self._client = client

    def _available_client(self) -> Result[XaiOAuthClient, ProviderDisabled]:
        """Return configured xAI OAuth client or a disabled-provider error."""
        if self._client is None:
            return Failure(
                ProviderDisabled(
                    reason="xAI OAuth provider is disabled or not configured"
                )
            )
        return Success(self._client)

    async def start_device(
        self, *, workspace_id: str, user_id: str
    ) -> Result[
        XaiOAuthDeviceStartOutput,
        ProviderDisabled
        | ProviderRejected
        | ProviderEntitlementDenied
        | ProviderUnavailable,
    ]:
        """Start Device OAuth flow."""
        client_result = self._available_client()
        match client_result:
            case Success(client):
                code_result = await client.request_device_user_code()
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(client_result)
        match code_result:
            case Success(user_code):
                expires_at = datetime.datetime.now(datetime.UTC) + min(
                    _SESSION_TTL,
                    datetime.timedelta(seconds=user_code.expires_in_seconds),
                )
                async with self._session_manager() as session:
                    created = await self._session_repo.create(
                        session,
                        XaiOAuthSessionCreate(
                            workspace_id=workspace_id,
                            user_id=user_id,
                            method=XaiOAuthConnectionMethod.DEVICE,
                            device_code=user_code.device_code,
                            user_code=user_code.user_code,
                            verification_uri=user_code.verification_uri,
                            interval_seconds=user_code.interval_seconds,
                            expires_at=expires_at,
                        ),
                    )
                return Success(
                    XaiOAuthDeviceStartOutput(
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
    ) -> Result[XaiOAuthDeviceStatusOutput, XaiOAuthError]:
        """Check Device authentication completion once."""
        session_result = await self._get_owned_pending_session(
            workspace_id=workspace_id,
            user_id=user_id,
            session_id=session_id,
            expected_method=XaiOAuthConnectionMethod.DEVICE,
        )
        match session_result:
            case Success(oauth_session):
                client_result = self._available_client()
                match client_result:
                    case Success(client):
                        poll_result = await client.poll_device_tokens(
                            device_code=oauth_session.device_code,
                            connection_method=XaiOAuthConnectionMethod.DEVICE,
                        )
                    case Failure(error):
                        return Failure(error)
                    case _:
                        assert_never(client_result)
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(session_result)

        match poll_result:
            case Success(tokens):
                save_result = await self._save_tokens(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    tokens_result=Success(tokens),
                )
                match save_result:
                    case Success(output):
                        return Success(
                            XaiOAuthDeviceStatusOutput(
                                session_id=session_id,
                                status=XaiOAuthSessionStatus.CONNECTED,
                                integration=output.integration,
                            )
                        )
                    case Failure(error):
                        return Failure(error)
                    case _:
                        assert_never(save_result)
            case Failure(ProviderPending()):
                return Success(
                    XaiOAuthDeviceStatusOutput(
                        session_id=session_id,
                        status=XaiOAuthSessionStatus.PENDING,
                    )
                )
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(poll_result)

    async def cancel_device(
        self, *, workspace_id: str, user_id: str, session_id: str
    ) -> Result[XaiOAuthDeviceStatusOutput, XaiOAuthError]:
        """Cancel Device OAuth session."""
        check = await self._get_owned_pending_session(
            workspace_id=workspace_id,
            user_id=user_id,
            session_id=session_id,
            expected_method=XaiOAuthConnectionMethod.DEVICE,
        )
        if isinstance(check, Failure):
            return Failure(check.error)
        async with self._session_manager() as session:
            result = await self._session_repo.cancel(session, session_id)
        match result:
            case Success(value):
                return Success(
                    XaiOAuthDeviceStatusOutput(session_id=value.id, status=value.status)
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
        expected_method: XaiOAuthConnectionMethod,
    ) -> Result[XaiOAuthSessionWithSecrets, SessionNotFound | InvalidSession]:
        """Fetch pending session belonging to requesting user and workspace."""
        async with self._session_manager() as session:
            oauth_session = await self._session_repo.get_by_id_with_secrets(
                session, session_id
            )
        if oauth_session is None:
            return Failure(SessionNotFound(session_id=session_id))
        if (
            oauth_session.workspace_id != workspace_id
            or oauth_session.user_id != user_id
            or oauth_session.method != expected_method
            or oauth_session.status != XaiOAuthSessionStatus.PENDING
            or oauth_session.expires_at <= datetime.datetime.now(datetime.UTC)
        ):
            return Failure(InvalidSession(reason="OAuth session is not valid"))
        return Success(oauth_session)

    async def _save_tokens(
        self,
        *,
        workspace_id: str,
        session_id: str,
        tokens_result: Result[
            TokenSet,
            ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
        ],
    ) -> Result[XaiOAuthExchangeOutput, XaiOAuthError]:
        """Consume Session and store token in integration."""
        match tokens_result:
            case Success(tokens):
                now = datetime.datetime.now(datetime.UTC)
                async with self._session_manager() as session:
                    consume_result = await self._session_repo.consume(
                        session, session_id
                    )
                    if isinstance(consume_result, Failure):
                        return Failure(SessionTransitionFailed(session_id=session_id))
                    integration = await self._integration_repo.create(
                        session,
                        LLMProviderIntegrationCreate(
                            workspace_id=workspace_id,
                            provider=LLMProvider.XAI_OAUTH,
                            name="xAI Grok OAuth",
                            secrets=XaiOAuthSecrets(
                                access_token=tokens.access_token,
                                refresh_token=tokens.refresh_token,
                                id_token=tokens.id_token,
                                expires_at=tokens.expires_at,
                            ),
                            config=XaiOAuthConfig(
                                account_id=tokens.account_id,
                                email=tokens.email,
                                connection_method=tokens.connection_method.value,
                                status=XaiOAuthConnectionStatus.CONNECTED.value,
                                connected_at=now,
                                last_refreshed_at=now,
                            ),
                        ),
                    )
                return Success(XaiOAuthExchangeOutput(integration=integration))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(tokens_result)
