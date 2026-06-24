"""ChatGPT OAuth connection service."""

import datetime
import secrets
from collections.abc import AsyncIterator
from typing import Annotated, assert_never

import httpx
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.chatgpt_oauth import (
    CHATGPT_OAUTH_DEVICE_REDIRECT_URI,
    CHATGPT_OAUTH_DEVICE_VERIFICATION_URL,
    ChatGPTOAuthConnectionMethod,
    ChatGPTOAuthConnectionStatus,
    ChatGPTOAuthSessionStatus,
)
from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import LLMProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.chatgpt_oauth_session import ChatGPTOAuthSessionRepository
from azents.repos.chatgpt_oauth_session.data import (
    ChatGPTOAuthSessionCreate,
    ChatGPTOAuthSessionWithSecrets,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationCreate

from .client import ChatGPTOAuthClient
from .data import (
    ChatGPTOAuthDeviceStartOutput,
    ChatGPTOAuthDeviceStatusOutput,
    ChatGPTOAuthError,
    ChatGPTOAuthExchangeOutput,
    InvalidSession,
    ProviderPending,
    ProviderRejected,
    ProviderUnavailable,
    SessionNotFound,
    SessionTransitionFailed,
    TokenSet,
)

_SESSION_TTL = datetime.timedelta(minutes=15)


async def _get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Create ChatGPT OAuth HTTP client and close it after request."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def _get_session_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> ChatGPTOAuthSessionRepository:
    """Create ChatGPT OAuth session repository dependency."""
    return ChatGPTOAuthSessionRepository(cipher)


def _get_integration_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> LLMProviderIntegrationRepository:
    """Create LLM provider integration repository dependency."""
    return LLMProviderIntegrationRepository(cipher)


def _get_client(
    http_client: Annotated[httpx.AsyncClient, Depends(_get_http_client)],
) -> ChatGPTOAuthClient:
    """Create ChatGPT OAuth client dependency."""
    return ChatGPTOAuthClient(http_client)


class ChatGPTOAuthService:
    """ChatGPT OAuth device flow service."""

    def __init__(
        self,
        session_manager: Annotated[
            SessionManager[AsyncSession], Depends(get_session_manager)
        ],
        session_repo: Annotated[
            ChatGPTOAuthSessionRepository, Depends(_get_session_repo)
        ],
        integration_repo: Annotated[
            LLMProviderIntegrationRepository, Depends(_get_integration_repo)
        ],
        client: Annotated[ChatGPTOAuthClient, Depends(_get_client)],
    ) -> None:
        """Inject service dependencies."""
        self._session_manager = session_manager
        self._session_repo = session_repo
        self._integration_repo = integration_repo
        self._client = client

    async def start_device(
        self, *, workspace_id: str, user_id: str
    ) -> Result[ChatGPTOAuthDeviceStartOutput, ProviderRejected | ProviderUnavailable]:
        """Start Device OAuth flow."""
        code_result = await self._client.request_device_user_code()
        match code_result:
            case Success(user_code):
                state = secrets.token_urlsafe(32)
                expires_at = datetime.datetime.now(datetime.UTC) + _SESSION_TTL
                async with self._session_manager() as session:
                    created = await self._session_repo.create(
                        session,
                        ChatGPTOAuthSessionCreate(
                            workspace_id=workspace_id,
                            user_id=user_id,
                            method=ChatGPTOAuthConnectionMethod.DEVICE,
                            state=state,
                            code_verifier=secrets.token_urlsafe(32),
                            redirect_uri=CHATGPT_OAUTH_DEVICE_REDIRECT_URI,
                            expires_at=expires_at,
                            device_auth_id=user_code.device_auth_id,
                            user_code=user_code.user_code,
                            verification_uri=CHATGPT_OAUTH_DEVICE_VERIFICATION_URL,
                            interval_seconds=user_code.interval_seconds,
                        ),
                    )
                return Success(
                    ChatGPTOAuthDeviceStartOutput(
                        session_id=created.id,
                        user_code=user_code.user_code,
                        verification_uri=CHATGPT_OAUTH_DEVICE_VERIFICATION_URL,
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
    ) -> Result[ChatGPTOAuthDeviceStatusOutput, ChatGPTOAuthError]:
        """Check Device authentication completion once."""
        session_result = await self._get_owned_pending_session(
            workspace_id=workspace_id,
            user_id=user_id,
            session_id=session_id,
            expected_state=None,
            expected_method=ChatGPTOAuthConnectionMethod.DEVICE,
        )
        match session_result:
            case Success(oauth_session):
                if (
                    oauth_session.device_auth_id is None
                    or oauth_session.user_code is None
                ):
                    return Failure(
                        InvalidSession(reason="Device session is incomplete")
                    )
                poll_result = await self._client.poll_device_authorization_code(
                    device_auth_id=oauth_session.device_auth_id,
                    user_code=oauth_session.user_code,
                )
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(session_result)

        match poll_result:
            case Success(device_code):
                token_result = await self._client.exchange_authorization_code(
                    code=device_code.authorization_code,
                    code_verifier=device_code.code_verifier,
                    redirect_uri=CHATGPT_OAUTH_DEVICE_REDIRECT_URI,
                    connection_method=ChatGPTOAuthConnectionMethod.DEVICE,
                )
                save_result = await self._save_tokens(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    tokens_result=token_result,
                )
                match save_result:
                    case Success(output):
                        return Success(
                            ChatGPTOAuthDeviceStatusOutput(
                                session_id=session_id,
                                status=ChatGPTOAuthSessionStatus.CONNECTED,
                                integration=output.integration,
                            )
                        )
                    case Failure(error):
                        return Failure(error)
                    case _:
                        assert_never(save_result)
            case Failure(ProviderPending()):
                return Success(
                    ChatGPTOAuthDeviceStatusOutput(
                        session_id=session_id,
                        status=ChatGPTOAuthSessionStatus.PENDING,
                    )
                )
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(poll_result)

    async def cancel_device(
        self, *, workspace_id: str, user_id: str, session_id: str
    ) -> Result[ChatGPTOAuthDeviceStatusOutput, ChatGPTOAuthError]:
        """Cancel Device OAuth session."""
        check = await self._get_owned_pending_session(
            workspace_id=workspace_id,
            user_id=user_id,
            session_id=session_id,
            expected_state=None,
            expected_method=ChatGPTOAuthConnectionMethod.DEVICE,
        )
        if isinstance(check, Failure):
            return Failure(check.error)
        async with self._session_manager() as session:
            result = await self._session_repo.cancel(session, session_id)
        match result:
            case Success(value):
                return Success(
                    ChatGPTOAuthDeviceStatusOutput(
                        session_id=value.id, status=value.status
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
        expected_state: str | None,
        expected_method: ChatGPTOAuthConnectionMethod,
    ) -> Result[ChatGPTOAuthSessionWithSecrets, SessionNotFound | InvalidSession]:
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
            or oauth_session.status != ChatGPTOAuthSessionStatus.PENDING
            or oauth_session.expires_at <= datetime.datetime.now(datetime.UTC)
        ):
            return Failure(InvalidSession(reason="OAuth session is not valid"))
        if expected_state is not None and oauth_session.state != expected_state:
            return Failure(InvalidSession(reason="OAuth state does not match"))
        return Success(oauth_session)

    async def _save_tokens(
        self,
        *,
        workspace_id: str,
        session_id: str,
        tokens_result: Result[TokenSet, ProviderRejected | ProviderUnavailable],
    ) -> Result[ChatGPTOAuthExchangeOutput, ChatGPTOAuthError]:
        """Consume Session and store token in integration."""
        match tokens_result:
            case Success(tokens):
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
                            provider=LLMProvider.CHATGPT_OAUTH,
                            name="ChatGPT Subscription",
                            secrets=ChatGPTOAuthSecrets(
                                access_token=tokens.access_token,
                                refresh_token=tokens.refresh_token,
                                id_token=tokens.id_token,
                                expires_at=tokens.expires_at,
                            ),
                            config=ChatGPTOAuthConfig(
                                account_id=tokens.account_id,
                                email=tokens.email,
                                plan_type=tokens.plan_type,
                                connection_method=tokens.connection_method.value,
                                status=ChatGPTOAuthConnectionStatus.CONNECTED.value,
                                connected_at=datetime.datetime.now(datetime.UTC),
                                last_refreshed_at=datetime.datetime.now(datetime.UTC),
                            ),
                        ),
                    )
                return Success(ChatGPTOAuthExchangeOutput(integration=integration))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(tokens_result)
