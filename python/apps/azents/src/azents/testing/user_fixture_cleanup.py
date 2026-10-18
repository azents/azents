"""Exact cleanup for independently committed test accounts and lifecycle work."""

from collections.abc import Sequence

import sqlalchemy as sa

from azents.rdb.models.owner_lifecycle import RDBOwnerLifecycleJob
from azents.rdb.session_capabilities import WriteSession
from azents.repos.user import UserRepository


async def cleanup_committed_users(
    session: WriteSession, user_ids: Sequence[str]
) -> None:
    """Delete only tracked users and their content-free jobs without foreign keys."""
    await session.write_session.execute(
        sa.delete(RDBOwnerLifecycleJob).where(
            RDBOwnerLifecycleJob.user_id.in_(user_ids)
        )
    )
    for user_id in user_ids:
        await UserRepository().delete(session, user_id)
