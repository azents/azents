"""Completed owner-authority validation for VFS backend routing."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.session_execution.ownership import OwnerBoundSessionManager


@dataclasses.dataclass(frozen=True)
class VfsReadAuthorityRepository:
    """Finish the durable owner check before filesystem or backend I/O."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def assert_current(self, *, session_id: str, owner_generation: int) -> None:
        """Validate the concrete Session generation in a completed DB operation."""
        await OwnerBoundSessionManager(
            session_manager=self.session_manager,
            session_id=session_id,
            owner_generation=owner_generation,
        ).assert_current()


def get_vfs_read_authority_repository(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
) -> VfsReadAuthorityRepository:
    """Wire complete owner checks without exporting a live SessionManager."""
    return VfsReadAuthorityRepository(session_manager=session_manager)
