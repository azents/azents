"""Current registration guards and transient token capture for local removal."""

import dataclasses

import sqlalchemy as sa
from pydantic import ConfigDict, TypeAdapter, ValidationError

from azents.core.crypto import CredentialCipher
from azents.core.github_credentials import GitHubSecrets, GitHubSecretsAppUser
from azents.core.github_user_oauth import (
    GitHubUserConnectionSummary,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRevocation,
)
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserAttempt,
    RDBGitHubUserConnection,
)
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.github_user_oauth.payloads import attempt_from, connection_from


def same_app(left: GitHubUserRegistration, right: GitHubUserRegistration) -> bool:
    """Identity equality does not conflate different App or OAuth clients."""
    return (left.source, left.app_id, left.client_id) == (
        right.source,
        right.app_id,
        right.client_id,
    )


def capture_registration(
    toolkit: RDBToolkitConfig | None,
    original: GitHubUserRegistration,
    supplied: GitHubUserRegistration | None,
    cipher: CredentialCipher,
) -> GitHubUserRegistration:
    """Use available same-App secret material without changing captured identity."""
    if supplied is not None and same_app(original, supplied):
        return dataclasses.replace(original, client_secret=supplied.client_secret)
    if (
        original.source != "byoa_user"
        or toolkit is None
        or toolkit.encrypted_credentials is None
    ):
        return original
    try:
        credentials = TypeAdapter(
            GitHubSecrets, config=ConfigDict(hide_input_in_errors=True)
        ).validate_json(cipher.decrypt(toolkit.encrypted_credentials))
    except ValidationError:
        # Invalid current registration cannot substitute another App's credential.
        return original
    if (
        isinstance(credentials, GitHubSecretsAppUser)
        and credentials.app_id == original.app_id
        and credentials.client_id == original.client_id
    ):
        return dataclasses.replace(original, client_secret=credentials.client_secret)
    return original


def distinct_revocations(
    values: list[GitHubUserRevocation],
) -> tuple[GitHubUserRevocation, ...]:
    """Deduplicate only factual identical captured token/App targets."""
    result: list[GitHubUserRevocation] = []
    for value in values:
        if not any(
            same_app(value.registration, prior.registration)
            and value.access_token == prior.access_token
            for prior in result
        ):
            result.append(value)
    return tuple(result)


async def read_summary(
    session: ReadSession, toolkit_id: str
) -> GitHubUserConnectionSummary | None:
    """Read allowlisted account and source facts without exposing credentials."""
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
    )


async def assert_registration_change_allowed(
    session: WriteSession, toolkit_id: str
) -> None:
    """Changing provider identity requires an explicit active/candidate replacement."""
    await session.write_session.scalar(
        sa.select(RDBToolkitConfig)
        .where(RDBToolkitConfig.id == toolkit_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    active = await session.read_session.scalar(
        sa.select(RDBGitHubUserConnection.id)
        .where(RDBGitHubUserConnection.toolkit_id == toolkit_id)
        .limit(1)
    )
    reviewed = await session.read_session.scalar(
        sa.select(RDBGitHubUserAttempt.id)
        .where(
            RDBGitHubUserAttempt.toolkit_id == toolkit_id,
            RDBGitHubUserAttempt.encrypted_candidate.is_not(None),
        )
        .limit(1)
    )
    if active is not None or reviewed is not None:
        raise GitHubUserOAuthError(
            GitHubUserErrorCode.STALE,
            "Disconnect the current GitHub user connection or cancel its review "
            "before changing App registration.",
        )


async def capture_and_clear_user_tokens(
    session: WriteSession,
    toolkit_id: str,
    registration: GitHubUserRegistration | None,
    *,
    cipher: CredentialCipher,
) -> tuple[GitHubUserRevocation, ...]:
    """Capture known exact targets and remove local authority in the caller's write."""
    toolkit = await session.write_session.scalar(
        sa.select(RDBToolkitConfig)
        .where(RDBToolkitConfig.id == toolkit_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    values: list[GitHubUserRevocation] = []
    current = await session.read_session.scalar(
        sa.select(RDBGitHubUserConnection).where(
            RDBGitHubUserConnection.toolkit_id == toolkit_id
        )
    )
    if current is not None:
        saved = connection_from(current, cipher)
        values.append(
            GitHubUserRevocation(
                registration=capture_registration(
                    toolkit, saved.registration, registration, cipher
                ),
                access_token=saved.access_token,
            )
        )
    attempts = (
        await session.read_session.scalars(
            sa.select(RDBGitHubUserAttempt).where(
                RDBGitHubUserAttempt.toolkit_id == toolkit_id
            )
        )
    ).all()
    for row in attempts:
        attempt = attempt_from(row, cipher)
        if attempt.candidate is not None:
            values.append(
                GitHubUserRevocation(
                    registration=attempt.registration,
                    access_token=attempt.candidate.access_token,
                )
            )
    await session.write_session.execute(
        sa.delete(RDBGitHubUserAttempt).where(
            RDBGitHubUserAttempt.toolkit_id == toolkit_id
        )
    )
    await session.write_session.execute(
        sa.delete(RDBGitHubUserConnection).where(
            RDBGitHubUserConnection.toolkit_id == toolkit_id
        )
    )
    return distinct_revocations(values)


async def capture_and_clear_agent_user_tokens(
    session: WriteSession, *, agent_id: str, cipher: CredentialCipher
) -> tuple[GitHubUserRevocation, ...]:
    """Remove only exact Agent-owned credentials, never shared attachments."""
    toolkits = (
        await session.write_session.scalars(
            sa.select(RDBToolkitConfig)
            .where(RDBToolkitConfig.owner_agent_id == agent_id)
            .order_by(RDBToolkitConfig.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    values: list[GitHubUserRevocation] = []
    for toolkit in toolkits:
        values.extend(
            await capture_and_clear_user_tokens(
                session, toolkit.id, None, cipher=cipher
            )
        )
    return distinct_revocations(values)
