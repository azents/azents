"""Initial system administrator bootstrap service."""

import dataclasses
import hashlib
import hmac
import logging
import secrets
from typing import Annotated

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.jwt import create_access_token
from azents.core.auth.password import (
    WeakPasswordError,
    hash_password,
    validate_password_strength,
)
from azents.core.config import AuthConfig, SystemBootstrapConfig
from azents.core.deps import get_auth_config, get_system_bootstrap_config
from azents.core.enums import SystemUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.system_bootstrap.repository import SystemBootstrapRepository
from azents.repos.system_user_role.data import SystemUserRoleAssignmentCreate
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services._utils import generate_refresh_token

from .data import (
    BootstrapUnavailable,
    InvalidSetupToken,
    SystemBootstrapInput,
    SystemBootstrapOutput,
    SystemBootstrapStatusOutput,
    WeakBootstrapPassword,
)

logger = logging.getLogger(__name__)


def _hash_setup_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclasses.dataclass
class SystemBootstrapService:
    """Initialize and consume the one-time system bootstrap token."""

    bootstrap_repository: Annotated[SystemBootstrapRepository, Depends()]
    system_role_repository: Annotated[SystemUserRoleRepository, Depends()]
    user_repository: Annotated[UserRepository, Depends()]
    password_login_repository: Annotated[PasswordLoginRepository, Depends()]
    session_repository: Annotated[SessionRepository, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)]
    bootstrap_config: Annotated[
        SystemBootstrapConfig, Depends(get_system_bootstrap_config)
    ]

    async def initialize(self) -> None:
        """Ensure zero-user installations have one active setup token."""
        configured_token = self.bootstrap_config.setup_token
        if configured_token is not None and len(configured_token) < 32:
            raise ValueError(
                "The configured system bootstrap setup token must contain at least "
                "32 characters."
            )

        generated_token: str | None = None
        configured_token_activated = False
        async with self.session_manager() as session:
            await self.bootstrap_repository.acquire_mutation_lock(session)
            if await self.user_repository.count(session) != 0:
                return

            state = await self.bootstrap_repository.get(session)
            if state is not None and state.consumed_at is not None:
                return

            if configured_token is not None:
                token_hash = _hash_setup_token(configured_token)
                if state is None:
                    await self.bootstrap_repository.create(
                        session,
                        token_hash=token_hash,
                    )
                    configured_token_activated = True
                elif not hmac.compare_digest(state.token_hash, token_hash):
                    await self.bootstrap_repository.replace_token(
                        session,
                        token_hash=token_hash,
                    )
                    configured_token_activated = True
            elif state is None:
                generated_token = secrets.token_urlsafe(32)
                await self.bootstrap_repository.create(
                    session,
                    token_hash=_hash_setup_token(generated_token),
                )

        if generated_token is not None:
            logger.warning(
                "Generated one-time system bootstrap setup token",
                extra={
                    "setup_token": generated_token,
                    "secret_logging_reason": "initial_system_bootstrap",
                },
            )
        elif configured_token_activated:
            logger.info("Configured system bootstrap setup token activated")

    async def get_status(self) -> SystemBootstrapStatusOutput:
        """Return whether the initial bootstrap transaction can run."""
        async with self.session_manager() as session:
            if await self.user_repository.count(session) != 0:
                return SystemBootstrapStatusOutput(available=False)
            state = await self.bootstrap_repository.get(session)
        return SystemBootstrapStatusOutput(
            available=state is not None and state.consumed_at is None
        )

    async def bootstrap(
        self,
        input: SystemBootstrapInput,
    ) -> Result[
        SystemBootstrapOutput,
        BootstrapUnavailable | InvalidSetupToken | WeakBootstrapPassword,
    ]:
        """Create the first User, system role, credentials, and session atomically.

        :param input: Initial administrator and setup-token data
        :return: Session tokens or a rejected-bootstrap reason
        """
        submitted_hash = _hash_setup_token(input.setup_token)
        async with self.session_manager() as session:
            await self.bootstrap_repository.acquire_mutation_lock(session)
            if await self.user_repository.count(session) != 0:
                self._log_rejection(input, reason="users_exist")
                return Failure(BootstrapUnavailable())

            state = await self.bootstrap_repository.get(session)
            if state is None or state.consumed_at is not None:
                self._log_rejection(input, reason="inactive_setup_token")
                return Failure(BootstrapUnavailable())
            if not hmac.compare_digest(state.token_hash, submitted_hash):
                self._log_rejection(input, reason="invalid_setup_token")
                return Failure(InvalidSetupToken())

            try:
                validate_password_strength(input.password)
            except WeakPasswordError as error:
                return Failure(WeakBootstrapPassword(message=error.message))

            now = tznow()
            user = await self.user_repository.create_with_verified_primary_email(
                session,
                UserCreate(email=input.email.strip().lower()),
                verified_at=now,
            )
            await self.password_login_repository.create(
                session,
                PasswordLoginCreate(
                    user_id=user.id,
                    password_hash=hash_password(input.password),
                ),
            )
            await self.system_role_repository.create(
                session,
                SystemUserRoleAssignmentCreate(
                    user_id=user.id,
                    role=SystemUserRole.SYSTEM_ADMIN,
                    granted_by_user_id=None,
                ),
            )

            refresh_token = generate_refresh_token()
            expires_at = now + self.auth_config.refresh_token.expire_timedelta
            max_expires_at = (
                now + self.auth_config.refresh_token.max_expire_timedelta
                if self.auth_config.refresh_token.max_expire_timedelta is not None
                else None
            )
            auth_session = await self.session_repository.create(
                session,
                SessionCreate(
                    user_id=user.id,
                    refresh_token=refresh_token,
                    expires_at=expires_at,
                    max_expires_at=max_expires_at,
                    user_agent=input.user_agent,
                    ip_address=input.ip_address,
                ),
            )
            await self.bootstrap_repository.consume(session)

        access_token = create_access_token(
            config=self.auth_config.jwt,
            user_id=user.id,
            session_id=auth_session.id,
        )
        logger.info(
            "Initial system administrator bootstrap completed",
            extra={
                "user_id": user.id,
                "session_id": auth_session.id,
                "source": "bootstrap",
            },
        )
        return Success(
            SystemBootstrapOutput(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=self.auth_config.jwt.access_token_expire_seconds,
            )
        )

    @staticmethod
    def _log_rejection(input: SystemBootstrapInput, *, reason: str) -> None:
        logger.info(
            "System bootstrap attempt rejected",
            extra={
                "reason": reason,
                "ip_address": input.ip_address,
                "user_agent": input.user_agent,
            },
        )
