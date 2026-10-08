"""Completed initial-system bootstrap database operations."""

import dataclasses
import datetime
import enum
import hmac
from typing import Annotated

from fastapi import Depends

from azents.core.enums import SystemUserRole
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.system_bootstrap.repository import SystemBootstrapRepository
from azents.repos.system_user_role.data import SystemUserRoleAssignmentCreate
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate


class BootstrapRejection(enum.Enum):
    """Existing authority rejection predicates."""

    USERS_EXIST = "users_exist"
    INACTIVE = "inactive_setup_token"
    INVALID_TOKEN = "invalid_setup_token"


@dataclasses.dataclass(frozen=True)
class BootstrapInitialization:
    """Whether an initial or configured setup token was activated."""

    generated: bool
    configured: bool


@dataclasses.dataclass(frozen=True)
class BootstrapCommand:
    """Prepared initial account intent without hashing or application callbacks."""

    submitted_hash: str
    email: str
    password_hash: str
    now: datetime.datetime
    refresh_token: str
    expires_at: datetime.datetime
    max_expires_at: datetime.datetime | None
    user_agent: str | None
    ip_address: str | None


@dataclasses.dataclass(frozen=True)
class BootstrapCreated:
    """Committed identity used for post-transaction JWT construction."""

    user_id: str
    session_id: str


@dataclasses.dataclass(frozen=True)
class SystemBootstrapOperationRepository:
    """Retain advisory serialization and first-account atomicity."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    bootstrap_repository: Annotated[SystemBootstrapRepository, Depends()]
    role_repository: Annotated[SystemUserRoleRepository, Depends()]
    user_repository: Annotated[UserRepository, Depends()]
    password_repository: Annotated[PasswordLoginRepository, Depends()]
    session_repository: Annotated[SessionRepository, Depends()]

    async def initialize(
        self, *, token_hash: str, configured: bool
    ) -> BootstrapInitialization:
        """Activate only absent/unconsumed zero-user state under the original lock."""
        async with self.session_manager() as session:
            await self.bootstrap_repository.acquire_mutation_lock(session)
            if await self.user_repository.count(session) != 0:
                return BootstrapInitialization(generated=False, configured=False)
            state = await self.bootstrap_repository.get(session)
            if state is not None and state.consumed_at is not None:
                return BootstrapInitialization(generated=False, configured=False)
            if state is None:
                await self.bootstrap_repository.create(session, token_hash=token_hash)
                return BootstrapInitialization(
                    generated=not configured, configured=configured
                )
            if configured and not hmac.compare_digest(state.token_hash, token_hash):
                await self.bootstrap_repository.replace_token(
                    session, token_hash=token_hash
                )
                return BootstrapInitialization(generated=False, configured=True)
            return BootstrapInitialization(generated=False, configured=False)

    async def available(self) -> bool:
        """Complete independent status reads without mutation capability."""
        async with self.read_session_manager() as session:
            if await self.user_repository.count(session) != 0:
                return False
            state = await self.bootstrap_repository.get(session)
            return state is not None and state.consumed_at is None

    async def admission(self, *, submitted_hash: str) -> BootstrapRejection | None:
        """Check original rejection order before expensive password preparation."""
        async with self.read_session_manager() as session:
            return await self._rejection(session, submitted_hash)

    async def _rejection(
        self, session: ReadSession, submitted_hash: str
    ) -> BootstrapRejection | None:
        if await self.user_repository.count(session) != 0:
            return BootstrapRejection.USERS_EXIST
        state = await self.bootstrap_repository.get(session)
        if state is None or state.consumed_at is not None:
            return BootstrapRejection.INACTIVE
        if not hmac.compare_digest(state.token_hash, submitted_hash):
            return BootstrapRejection.INVALID_TOKEN
        return None

    async def bootstrap(
        self, *, command: BootstrapCommand
    ) -> BootstrapCreated | BootstrapRejection:
        """Revalidate authority and commit the entire first-account group."""
        async with self.session_manager() as session:
            await self.bootstrap_repository.acquire_mutation_lock(session)
            rejection = await self._rejection(session, command.submitted_hash)
            if rejection is not None:
                return rejection
            user = await self.user_repository.create_with_verified_primary_email(
                session, UserCreate(email=command.email), verified_at=command.now
            )
            password = await self.password_repository.create(
                session,
                PasswordLoginCreate(
                    user_id=user.id, password_hash=command.password_hash
                ),
            )
            if not password.success:
                # The primitive rolled back; no subsequent query may restart the group.
                raise RuntimeError("Initial bootstrap password creation failed.")
            await self.role_repository.create(
                session,
                SystemUserRoleAssignmentCreate(
                    user_id=user.id,
                    role=SystemUserRole.SYSTEM_ADMIN,
                    granted_by_user_id=None,
                ),
            )
            auth_session = await self.session_repository.create(
                session,
                SessionCreate(
                    user_id=user.id,
                    refresh_token=command.refresh_token,
                    expires_at=command.expires_at,
                    max_expires_at=command.max_expires_at,
                    user_agent=command.user_agent,
                    ip_address=command.ip_address,
                ),
            )
            await self.bootstrap_repository.consume(session)
            return BootstrapCreated(user_id=user.id, session_id=auth_session.id)
