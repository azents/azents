"""Initial system administrator bootstrap service."""

import dataclasses
import hashlib
import logging
import secrets
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.auth.jwt import create_access_token
from azents.core.auth.password import (
    WeakPasswordError,
    hash_password,
    validate_password_strength,
)
from azents.core.config import AuthConfig, SystemBootstrapConfig
from azents.core.deps import get_auth_config, get_system_bootstrap_config
from azents.repos.system_bootstrap.operations import (
    BootstrapCommand,
    BootstrapCreated,
    BootstrapRejection,
    SystemBootstrapOperationRepository,
)
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

    operation_repository: Annotated[SystemBootstrapOperationRepository, Depends()]
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

        token = configured_token or secrets.token_urlsafe(32)
        result = await self.operation_repository.initialize(
            token_hash=_hash_setup_token(token),
            configured=configured_token is not None,
        )
        if result.generated:
            logger.warning(
                "Generated one-time system bootstrap setup token",
                extra={
                    "setup_token": token,
                    "secret_logging_reason": "initial_system_bootstrap",
                },
            )
        elif result.configured:
            logger.info("Configured system bootstrap setup token activated")

    async def get_status(self) -> SystemBootstrapStatusOutput:
        """Return whether the initial bootstrap transaction can run."""
        return SystemBootstrapStatusOutput(
            available=await self.operation_repository.available()
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
        rejection = await self.operation_repository.admission(
            submitted_hash=submitted_hash
        )
        if rejection is not None:
            return Failure(self._reject(input, rejection))
        try:
            validate_password_strength(input.password)
        except WeakPasswordError as error:
            return Failure(WeakBootstrapPassword(message=error.message))
        now = tznow()
        password_hash = hash_password(input.password)
        refresh_token = generate_refresh_token()
        result = await self.operation_repository.bootstrap(
            command=BootstrapCommand(
                submitted_hash=submitted_hash,
                email=input.email.strip().lower(),
                password_hash=password_hash,
                now=now,
                refresh_token=refresh_token,
                expires_at=now + self.auth_config.refresh_token.expire_timedelta,
                max_expires_at=(
                    now + self.auth_config.refresh_token.max_expire_timedelta
                    if self.auth_config.refresh_token.max_expire_timedelta is not None
                    else None
                ),
                user_agent=input.user_agent,
                ip_address=input.ip_address,
            )
        )
        match result:
            case BootstrapRejection():
                return Failure(self._reject(input, result))
            case BootstrapCreated():
                pass
            case _:
                assert_never(result)
        access_token = create_access_token(
            config=self.auth_config.jwt,
            user_id=result.user_id,
            session_id=result.session_id,
        )
        logger.info(
            "Initial system administrator bootstrap completed",
            extra={
                "user_id": result.user_id,
                "session_id": result.session_id,
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

    def _reject(
        self, input: SystemBootstrapInput, rejection: BootstrapRejection
    ) -> BootstrapUnavailable | InvalidSetupToken:
        self._log_rejection(input, reason=rejection.value)
        match rejection:
            case BootstrapRejection.INVALID_TOKEN:
                return InvalidSetupToken()
            case BootstrapRejection.USERS_EXIST | BootstrapRejection.INACTIVE:
                return BootstrapUnavailable()
            case _:
                assert_never(rejection)

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
