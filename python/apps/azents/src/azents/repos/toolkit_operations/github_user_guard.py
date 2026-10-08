"""Bind user-credential mutation guards to current locked Toolkit facts."""

import sqlalchemy as sa
from pydantic import ConfigDict, TypeAdapter

from azents.core.github_credentials import (
    GitHubSecrets,
    GitHubSecretsAppPlatformUser,
    GitHubSecretsAppUser,
)
from azents.core.github_user_oauth import GitHubUserErrorCode, GitHubUserOAuthError
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_user_oauth.guards import assert_mutation_allowed
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import ToolkitConfig, ToolkitUpdate

_adapter: TypeAdapter[GitHubSecrets] = TypeAdapter(
    GitHubSecrets, config=ConfigDict(hide_input_in_errors=True)
)
_USER_MODES = frozenset(("github_app_user", "github_app_platform_user"))


def _registration_identity(
    credentials: str | None,
) -> tuple[str, str, str | None] | None:
    if credentials is None:
        return None
    registration = _adapter.validate_json(credentials)
    match registration:
        case GitHubSecretsAppUser():
            return registration.type, registration.app_id, registration.client_id
        case GitHubSecretsAppPlatformUser():
            return registration.type, registration.app_id, None
        case _:
            return None


async def _current_github_toolkit(
    session: WriteSession,
    toolkit: ToolkitConfig,
    repository: ToolkitRepository,
) -> ToolkitConfig:
    """Serialize the exact GitHub mutation before interpreting current authority."""
    await session.write_session.scalar(
        sa.select(RDBToolkitConfig)
        .where(RDBToolkitConfig.id == toolkit.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    current = await repository.get_by_id(session, toolkit.id)
    if (
        current is None
        or current.workspace_id != toolkit.workspace_id
        or (current.owner_agent_id != toolkit.owner_agent_id)
    ):
        raise GitHubUserOAuthError(
            GitHubUserErrorCode.NOT_FOUND, "Toolkit is no longer in this context."
        )
    return current


async def guard_user_registration_update(
    session: WriteSession,
    toolkit: ToolkitConfig,
    update: ToolkitUpdate,
    *,
    repository: ToolkitRepository,
) -> None:
    """Evaluate requested replacement against locked, not detached, registration."""
    if toolkit.toolkit_type != "github":
        return
    current = await _current_github_toolkit(session, toolkit, repository)
    old_mode = current.config.get("github_auth_type")
    if old_mode not in _USER_MODES:
        return
    new_mode = update.get("config", current.config).get("github_auth_type")
    changed = new_mode != old_mode
    if "credentials" in update:
        changed = changed or _registration_identity(
            update["credentials"]
        ) != _registration_identity(current.credentials)
    await assert_mutation_allowed(
        session, current.id, registration_changed=changed, deleting=False
    )


async def guard_user_toolkit_delete(
    session: WriteSession,
    toolkit: ToolkitConfig,
    *,
    repository: ToolkitRepository,
) -> None:
    """Prevent a stale old-mode delete from cascading new user credentials."""
    if toolkit.toolkit_type != "github":
        return
    current = await _current_github_toolkit(session, toolkit, repository)
    if current.config.get("github_auth_type") not in _USER_MODES:
        return
    await assert_mutation_allowed(
        session, current.id, registration_changed=False, deleting=True
    )
