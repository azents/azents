"""User service over completed account repository operations."""

import dataclasses
import datetime
import logging
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.system_user_role import LastSystemAdmin
from azents.core.user import NotFound, UserDeletionStatus, UserUpdate
from azents.repos.user.data import UserCreate
from azents.repos.user.operations import UserOperationRepository
from azents.services.runtime_terminal.invalidation import (
    RuntimeTerminalInvalidationPublisherDependency,
)

from .data import UserListOutput, UserOutput

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class UserService:
    """Project completed User operations and publish committed invalidation."""

    repository: Annotated[UserOperationRepository, Depends()]
    terminal_invalidation_publisher: RuntimeTerminalInvalidationPublisherDependency

    async def create(self, create: UserCreate) -> UserOutput:
        """Create User and primary email."""
        return UserOutput.convert_from(await self.repository.create(create))

    async def get(self, user_id: str) -> UserOutput | None:
        """Fetch User by ID."""
        user = await self.repository.get(user_id)
        return None if user is None else UserOutput.convert_from(user)

    async def get_by_email(self, email: str) -> UserOutput | None:
        """Fetch User by exact email."""
        user = await self.repository.get_by_email(email)
        return None if user is None else UserOutput.convert_from(user)

    async def update(
        self, user_id: str, update: UserUpdate
    ) -> Result[UserOutput, NotFound]:
        """Update User with the existing partial-update semantics."""
        user = await self.repository.update(user_id, update)
        if user is None:
            return Failure(NotFound(user_id=user_id))
        return Success(UserOutput.convert_from(user))

    async def list_all(self, *, offset: int = 0, limit: int = 50) -> UserListOutput:
        """Fetch the existing User count and page."""
        result = await self.repository.list_all(offset=offset, limit=limit)
        return UserListOutput(
            items=[UserOutput.convert_from(u) for u in result.items],
            total=result.total,
        )

    async def delete(self, user_id: str) -> Result[None, LastSystemAdmin]:
        """Disable User access and enqueue durable account purge before effects."""
        result = await self.repository.delete(
            user_id, disabled_at=datetime.datetime.now(datetime.UTC)
        )
        if isinstance(result, Failure):
            logger.warning(
                "Final system administrator deletion denied",
                extra={"target_user_id": user_id},
            )
            return Failure(result.error)
        match result.value:
            case UserDeletionStatus.MISSING:
                return Success(None)
            case UserDeletionStatus.ACCEPTED:
                pass
            case _:
                assert_never(result.value)
        await self.terminal_invalidation_publisher.publish_user_terminal_invalidation(
            user_id
        )
        logger.info(
            "User account deletion accepted; purge lifecycle enqueued",
            extra={"target_user_id": user_id},
        )
        return Success(None)
