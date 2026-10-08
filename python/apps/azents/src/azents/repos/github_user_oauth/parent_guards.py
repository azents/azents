"""Atomic parent deletion guards preserving unrevoked GitHub user credentials."""

import sqlalchemy as sa

from azents.core.github_user_oauth import (
    GitHubUserAttemptStatus,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
)
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserAttempt,
    RDBGitHubUserCleanup,
    RDBGitHubUserConnection,
)
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session_capabilities import WriteSession


async def _assert_toolkits_clean(
    session: WriteSession, toolkit_ids: tuple[str, ...], *, parent: str
) -> None:
    """Require complete cleanup for locked parent-owned Toolkit rows."""
    if not toolkit_ids:
        return
    current = await session.read_session.scalar(
        sa.select(RDBGitHubUserConnection.id)
        .where(RDBGitHubUserConnection.toolkit_id.in_(toolkit_ids))
        .limit(1)
    )
    retired = await session.read_session.scalar(
        sa.select(RDBGitHubUserCleanup.id)
        .where(RDBGitHubUserCleanup.toolkit_id.in_(toolkit_ids))
        .limit(1)
    )
    protected_attempt = sa.or_(
        RDBGitHubUserAttempt.status.in_(
            (
                GitHubUserAttemptStatus.PENDING,
                GitHubUserAttemptStatus.EXCHANGING,
                GitHubUserAttemptStatus.REVIEW,
            )
        ),
        RDBGitHubUserAttempt.exchange_in_flight.is_(True),
        RDBGitHubUserAttempt.encrypted_candidate.is_not(None),
        RDBGitHubUserAttempt.encrypted_issued_token.is_not(None),
    )
    attempt = await session.read_session.scalar(
        sa.select(RDBGitHubUserAttempt.id)
        .where(
            RDBGitHubUserAttempt.toolkit_id.in_(toolkit_ids),
            protected_attempt,
        )
        .limit(1)
    )
    if current is not None or retired is not None or attempt is not None:
        raise GitHubUserOAuthError(
            GitHubUserErrorCode.CLEANUP_REQUIRED,
            "Disconnect the affected GitHub user Toolkits and complete token "
            f"cleanup before deleting this {parent}.",
        )
    # Only terminal, token-free, non-inflight attempts remain after this check.
    await session.write_session.execute(
        sa.delete(RDBGitHubUserAttempt).where(
            RDBGitHubUserAttempt.toolkit_id.in_(toolkit_ids),
            ~protected_attempt,
        )
    )


async def assert_agent_delete_allowed(session: WriteSession, *, agent_id: str) -> None:
    """Guard only Toolkits owned by the exact authorized Agent, not attachments."""
    toolkit_ids = tuple(
        (
            await session.write_session.scalars(
                sa.select(RDBToolkitConfig.id)
                .where(RDBToolkitConfig.owner_agent_id == agent_id)
                .order_by(RDBToolkitConfig.id)
                .with_for_update()
            )
        ).all()
    )
    await _assert_toolkits_clean(session, toolkit_ids, parent="Agent")


async def assert_workspace_delete_allowed(
    session: WriteSession, *, workspace_id: str
) -> None:
    """Guard all Toolkit ownership kinds inside the exact authorized Workspace."""
    toolkit_ids = tuple(
        (
            await session.write_session.scalars(
                sa.select(RDBToolkitConfig.id)
                .where(RDBToolkitConfig.workspace_id == workspace_id)
                .order_by(RDBToolkitConfig.id)
                .with_for_update()
            )
        ).all()
    )
    await _assert_toolkits_clean(session, toolkit_ids, parent="Workspace")
