"""Same-transaction Toolkit mutation guards and redacted read projections."""

import sqlalchemy as sa

from azents.core.github_user_oauth import (
    GitHubUserAttemptStatus,
    GitHubUserConnectionSummary,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
)
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserAttempt,
    RDBGitHubUserCleanup,
    RDBGitHubUserConnection,
)
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session_capabilities import ReadSession, WriteSession


async def cleanup_pending(session: ReadSession, toolkit_id: str) -> bool:
    """Observe unfinished cleanup without decrypting any credential."""
    retired = await session.read_session.scalar(
        sa.select(RDBGitHubUserCleanup.id)
        .where(RDBGitHubUserCleanup.toolkit_id == toolkit_id)
        .limit(1)
    )
    if retired is not None:
        return True
    inflight = await session.read_session.scalar(
        sa.select(RDBGitHubUserAttempt.id)
        .where(
            RDBGitHubUserAttempt.toolkit_id == toolkit_id,
            RDBGitHubUserAttempt.status == GitHubUserAttemptStatus.CANCELLED,
            RDBGitHubUserAttempt.exchange_in_flight.is_(True),
        )
        .limit(1)
    )
    return inflight is not None


async def read_summary(
    session: ReadSession, toolkit_id: str
) -> GitHubUserConnectionSummary | None:
    """Project only allowlisted account/App facts in an existing authorized read."""
    result = (
        await session.read_session.execute(
            sa.select(RDBGitHubUserConnection, RDBToolkitConfig.config)
            .join(
                RDBToolkitConfig,
                RDBToolkitConfig.id == RDBGitHubUserConnection.toolkit_id,
            )
            .where(RDBGitHubUserConnection.toolkit_id == toolkit_id)
        )
    ).one_or_none()
    if result is None:
        return None
    row, config = result
    source = (
        "platform_user"
        if config.get("github_auth_type") == "github_app_platform_user"
        else "byoa_user"
    )
    return GitHubUserConnectionSummary(
        id=row.id,
        account_id=row.account_id,
        account_login=row.account_login,
        account_avatar_url=row.account_avatar_url,
        app_id=row.app_id,
        source=source,
        status=row.status,
        failure_reason=row.failure_reason,
        cleanup_pending=await cleanup_pending(session, toolkit_id),
    )


async def assert_mutation_allowed(
    session: WriteSession,
    toolkit_id: str,
    *,
    registration_changed: bool,
    deleting: bool,
) -> None:
    """Keep registration/deletion compatible with current setup and cleanup state."""
    if not registration_changed and not deleting:
        return
    await session.write_session.scalar(
        sa.select(RDBToolkitConfig.id)
        .where(RDBToolkitConfig.id == toolkit_id)
        .with_for_update()
    )
    connection = await session.read_session.scalar(
        sa.select(RDBGitHubUserConnection.id)
        .where(RDBGitHubUserConnection.toolkit_id == toolkit_id)
        .limit(1)
    )
    attempt = await session.read_session.scalar(
        sa.select(RDBGitHubUserAttempt.id)
        .where(
            RDBGitHubUserAttempt.toolkit_id == toolkit_id,
            sa.or_(
                RDBGitHubUserAttempt.status.in_(
                    (
                        GitHubUserAttemptStatus.PENDING,
                        GitHubUserAttemptStatus.EXCHANGING,
                        GitHubUserAttemptStatus.REVIEW,
                    )
                ),
                RDBGitHubUserAttempt.exchange_in_flight.is_(True),
                RDBGitHubUserAttempt.encrypted_issued_token.is_not(None),
                RDBGitHubUserAttempt.encrypted_candidate.is_not(None),
            ),
        )
        .limit(1)
    )
    if (
        connection is not None
        or attempt is not None
        or await cleanup_pending(session, toolkit_id)
    ):
        raise GitHubUserOAuthError(
            GitHubUserErrorCode.CLEANUP_REQUIRED,
            "Disconnect GitHub user authorization and complete token cleanup "
            "before changing registration or deleting this Toolkit.",
        )
    if deleting:
        await session.write_session.execute(
            sa.delete(RDBGitHubUserAttempt).where(
                RDBGitHubUserAttempt.toolkit_id == toolkit_id
            )
        )
