"""xAI OAuth connection service."""

import datetime
from collections.abc import AsyncIterator
from typing import Annotated, assert_never

import httpx
from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.credentials import XaiOAuthConfig, XaiOAuthSecrets
from azents.core.xai_oauth import (
    XaiOAuthConnectionMethod,
    XaiOAuthConnectionStatus,
    XaiOAuthSessionStatus,
)
from azents.repos.oauth_persistence_errors import OAuthPersistenceError
from azents.repos.xai_oauth_session.data import (
    XaiOAuthSessionCreate,
    XaiOAuthSessionWithSecrets,
)
from azents.repos.xai_oauth_session.operations import XaiOAuthOperations

from .client import XaiOAuthClient
from .data import (
    InvalidSession,
    ProviderEntitlementDenied,
    ProviderPending,
    ProviderRejected,
    ProviderSlowDown,
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
_SLOW_DOWN_INCREMENT_SECONDS = 5


async def _get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Create xAI OAuth HTTP client and close it after request."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def _get_client(
    http_client: Annotated[httpx.AsyncClient, Depends(_get_http_client)],
) -> XaiOAuthClient:
    """Create xAI OAuth client dependency."""
    return XaiOAuthClient(http_client)


class XaiOAuthService:
    """xAI OAuth device flow service."""

    def __init__(
        self,
        operations: Annotated[XaiOAuthOperations, Depends(XaiOAuthOperations)],
        client: Annotated[XaiOAuthClient, Depends(_get_client)],
    ) -> None:
        """Inject service dependencies."""
        self.operations = operations
        self.client = client

    async def start_device(
        self, *, workspace_id: str, user_id: str, integration_id: str | None
    ) -> Result[
        XaiOAuthDeviceStartOutput,
        InvalidSession
        | ProviderRejected
        | ProviderEntitlementDenied
        | ProviderUnavailable,
    ]:
        """Start Device OAuth flow."""
        if integration_id is not None and not await self.operations.valid_target(
            workspace_id=workspace_id, integration_id=integration_id
        ):
            return Failure(InvalidSession(reason="Invalid integration target"))
        code_result = await self.client.request_device_user_code()
        match code_result:
            case Success(user_code):
                expires_at = datetime.datetime.now(datetime.UTC) + min(
                    _SESSION_TTL,
                    datetime.timedelta(seconds=user_code.expires_in_seconds),
                )
                created = await self.operations.create_session(
                    XaiOAuthSessionCreate(
                        workspace_id=workspace_id,
                        user_id=user_id,
                        integration_id=integration_id,
                        method=XaiOAuthConnectionMethod.DEVICE,
                        device_code=user_code.device_code,
                        user_code=user_code.user_code,
                        verification_uri=user_code.verification_uri,
                        interval_seconds=user_code.interval_seconds,
                        expires_at=expires_at,
                    )
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
                poll_result = await self.client.poll_device_tokens(
                    device_code=oauth_session.device_code,
                    connection_method=XaiOAuthConnectionMethod.DEVICE,
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
                    tokens_result=Success(tokens),
                )
                match save_result:
                    case Success(output):
                        return Success(
                            XaiOAuthDeviceStatusOutput(
                                session_id=session_id,
                                status=XaiOAuthSessionStatus.CONNECTED,
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
                    XaiOAuthDeviceStatusOutput(
                        session_id=session_id,
                        status=XaiOAuthSessionStatus.PENDING,
                        interval_seconds=oauth_session.interval_seconds,
                    )
                )
            case Failure(ProviderSlowDown()):
                interval_result = await self.operations.increase_poll_interval(
                    session_id, seconds=_SLOW_DOWN_INCREMENT_SECONDS
                )
                match interval_result:
                    case Success(value):
                        return Success(
                            XaiOAuthDeviceStatusOutput(
                                session_id=session_id,
                                status=XaiOAuthSessionStatus.PENDING,
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
        result = await self.operations.cancel_session(session_id)
        match result:
            case Success(value):
                return Success(
                    XaiOAuthDeviceStatusOutput(
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
        expected_method: XaiOAuthConnectionMethod,
    ) -> Result[XaiOAuthSessionWithSecrets, SessionNotFound | InvalidSession]:
        """Fetch pending session belonging to requesting user and workspace."""
        oauth_session = await self.operations.get_session_with_secrets(session_id)
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
                secrets = XaiOAuthSecrets(
                    access_token=tokens.access_token,
                    refresh_token=tokens.refresh_token,
                    id_token=tokens.id_token,
                    expires_at=tokens.expires_at,
                )
                config = XaiOAuthConfig(
                    account_id=tokens.account_id,
                    email=tokens.email,
                    connection_method=tokens.connection_method.value,
                    status=XaiOAuthConnectionStatus.CONNECTED.value,
                    connected_at=now,
                    last_refreshed_at=now,
                )
                stored = await self.operations.save_tokens(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    secrets=secrets,
                    config=config,
                )
                match stored:
                    case Success(integration):
                        return Success(XaiOAuthExchangeOutput(integration=integration))
                    case Failure(error):
                        match error:
                            case OAuthPersistenceError.INVALID_TARGET:
                                return Failure(
                                    InvalidSession(reason="Invalid integration target")
                                )
                            case OAuthPersistenceError.TRANSITION_FAILED:
                                return Failure(
                                    SessionTransitionFailed(session_id=session_id)
                                )
                            case _:
                                assert_never(error)
                    case _:
                        assert_never(stored)
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(tokens_result)
