"""Toolkit lifecycle projections preserve provider-owned wire compatibility."""

import datetime
import itertools
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.core.system_setting import SystemSettingFieldSource
from azents.repos.toolkit.data import ToolkitConfig
from azents.repos.toolkit_operations import ToolkitOperationsRepository
from azents.repos.toolkit_operations.owned import AgentToolkitOperationsRepository
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.github_user_oauth.service import GitHubUserOAuthService
from azents.services.toolkit import (
    ToolkitService,
    _decode_toolkit_auth,
    _decode_toolkit_auth_transition,
    _PreparedCredentials,
)
from azents.services.toolkit.data import (
    InvalidCredentials,
    ToolkitCreateInput,
    ToolkitOutput,
)
from azents.testing.types import require_instance

_VALUES: list[object] = [
    None,
    "",
    "none",
    "bearer",
    "oauth2",
    "github_app_user",
    "github_app_platform_user",
    "github_app_platform",
    "pat",
    "future-provider-mode",
    True,
    3,
    [],
    {"opaque": None},
]


def _toolkit(toolkit_type: str, config: dict[str, object]) -> ToolkitConfig:
    return ToolkitConfig(
        id="toolkit-1",
        workspace_id="workspace-1",
        owner_agent_id=None,
        toolkit_type=toolkit_type,
        slug="sample",
        name="Sample",
        config=config,
        credentials='{"token":"synthetic-private-value"}',
        enabled=True,
        always_expose_tools=False,
        revision=1,
        created_at=datetime.datetime(2026, 10, 15, tzinfo=datetime.UTC),
        updated_at=datetime.datetime(2026, 10, 15, tzinfo=datetime.UTC),
    )


def _service(runtime: MagicMock) -> ToolkitService:
    return ToolkitService(
        operations_repository=require_instance(
            MagicMock(spec=ToolkitOperationsRepository), ToolkitOperationsRepository
        ),
        owned_operations=require_instance(
            MagicMock(spec=AgentToolkitOperationsRepository),
            AgentToolkitOperationsRepository,
        ),
        toolkit_registry={},
        github_runtime=require_instance(runtime, PlatformGitHubAppRuntimeService),
        github_user_oauth=require_instance(
            MagicMock(spec=GitHubUserOAuthService), GitHubUserOAuthService
        ),
    )


def test_creation_projection_preserves_all_selector_combinations() -> None:
    """Unknown/null selectors remain nonmatching while current modes admit setup."""
    for toolkit_type, configured, submitted in itertools.product(
        ["github", "mcp", "future-provider"], _VALUES, _VALUES
    ):
        config = {"github_auth_type": configured, "extension": {"value": None}}
        credentials = {"type": submitted, "client_secret": "synthetic-private-value"}
        create = ToolkitCreateInput(
            workspace_id="workspace-1",
            toolkit_type=toolkit_type,
            config=config,
            credentials=credentials,
            always_expose_tools=False,
        )
        expected = toolkit_type == "github" and (
            configured in ("github_app_user", "github_app_platform_user")
            or submitted in ("github_app_user", "github_app_platform_user")
        )
        assert ToolkitService._requires_user_creation(create) is expected
        assert create.config == config
        assert create.credentials == credentials


def test_projection_keeps_missing_and_partial_credentials_opaque() -> None:
    """Projection does not require a complete registration or serialize secrets."""
    assert not _decode_toolkit_auth(None, None).user_creation
    assert not _decode_toolkit_auth({}, {}).user_creation
    credentials: dict[str, object] = {
        "type": "github_app_user",
        "client_secret": None,
        "extension": {"future": True},
    }
    evidence = _decode_toolkit_auth({}, credentials)
    assert evidence.credential_type == "github_app_user"
    assert evidence.github_auth_type is None
    assert evidence.user_creation
    assert credentials == {
        "type": "github_app_user",
        "client_secret": None,
        "extension": {"future": True},
    }
    assert "client_secret" not in repr(evidence)


def test_transition_preserves_exact_provider_value_equality() -> None:
    """Opaque generic auth values participate only in the historical comparison."""
    for toolkit_type, old_auth, new_auth, old_github, new_github in itertools.product(
        ["github", "future-provider"],
        _VALUES,
        _VALUES,
        [None, "github_app_user"],
        [None, "github_app_user", "github_app_platform_user"],
    ):
        existing_config = {"auth_type": old_auth, "github_auth_type": old_github}
        submitted_config = {"auth_type": new_auth, "github_auth_type": new_github}
        transition = _decode_toolkit_auth_transition(
            toolkit_type, existing_config, submitted_config
        )
        same_user = (
            toolkit_type == "github"
            and old_github in ("github_app_user", "github_app_platform_user")
            and new_github == old_github
        )
        assert transition.mcp_auth_changed == (old_auth != new_auth)
        assert transition.mcp_auth_supplied == (new_auth is not None)
        assert transition.same_github_user_registration == same_user
        update = ToolkitService._build_repo_update(
            {"config": submitted_config},
            existing=_toolkit(toolkit_type, existing_config),
            normalized_credentials=None,
        )
        assert ("credentials" in update) is (
            old_auth != new_auth and new_auth is not None and not same_user
        )
        assert update["config"] is submitted_config


def test_patch_omission_null_and_explicit_credentials_remain_distinct() -> None:
    """A projection never invents a patch key or overrides supplied credentials."""
    existing = _toolkit("github", {"auth_type": "bearer"})
    omitted = ToolkitService._build_repo_update(
        {"description": None}, existing=existing, normalized_credentials=None
    )
    assert omitted == {"description": None}
    assert ToolkitService._build_repo_update(
        {"config": {"auth_type": None}},
        existing=existing,
        normalized_credentials=None,
    ) == {"config": {"auth_type": None}}
    assert ToolkitService._build_repo_update(
        {"config": {"auth_type": "oauth2"}, "credentials": None},
        existing=existing,
        normalized_credentials=None,
    ) == {"config": {"auth_type": "oauth2"}, "credentials": None}
    credentials: dict[str, object] = {"type": "pat", "token": "synthetic-token"}
    updated = ToolkitService._build_repo_update(
        {"config": {"auth_type": "oauth2"}, "credentials": credentials},
        existing=existing,
        normalized_credentials=credentials,
    )
    assert updated["credentials"] == '{"type": "pat", "token": "synthetic-token"}'


@pytest.mark.parametrize(
    "credential_type",
    [
        value
        for value in _VALUES
        if value not in ("github_app_platform", "github_app_platform_user")
    ],
)
async def test_non_platform_preparation_preserves_original_opaque_object(
    credential_type: object,
) -> None:
    """Only the exact Platform variants resolve server-owned registration facts."""
    runtime = MagicMock(spec=PlatformGitHubAppRuntimeService)
    runtime.resolve = AsyncMock()
    service = _service(runtime)
    credentials = {"type": credential_type, "extension": {"value": None}}
    prepared = await service._prepare_credentials(credentials)
    assert isinstance(prepared, _PreparedCredentials)
    assert prepared.credentials is credentials
    assert prepared.platform is None
    runtime.resolve.assert_not_called()


@pytest.mark.parametrize(
    "credential_type", ["github_app_platform", "github_app_platform_user"]
)
@pytest.mark.parametrize("app_id", ["current-server-app", None])
async def test_platform_preparation_binds_server_snapshot_without_full_schema(
    credential_type: str, app_id: str | None
) -> None:
    """Partial submissions keep their extensions while App identity is server-owned."""
    runtime = MagicMock(spec=PlatformGitHubAppRuntimeService)
    snapshot = ResolvedPlatformGitHubApp(
        app_id=app_id,
        client_id=None,
        private_key=None,
        client_secret=None,
        app_id_source=SystemSettingFieldSource.ADMIN,
        effective_generation="generation",
    )
    runtime.resolve = AsyncMock(return_value=snapshot)
    service = _service(runtime)
    credentials: dict[str, object] = {
        "type": credential_type,
        "app_id": "submitted-app",
        "extension": {"nullable": None},
    }
    prepared = await service._prepare_credentials(credentials)
    runtime.resolve.assert_awaited_once_with()
    assert credentials["app_id"] == "submitted-app"
    if app_id is None:
        assert isinstance(prepared, InvalidCredentials)
        assert prepared.detail == "Platform GitHub App is not configured."
    else:
        assert isinstance(prepared, _PreparedCredentials)
        assert prepared.platform is snapshot
        assert prepared.credentials == {**credentials, "app_id": app_id}
        assert prepared.credentials is not credentials


def test_readiness_keeps_provider_extensions_and_current_user_mode_contract() -> None:
    runtime = MagicMock(spec=PlatformGitHubAppRuntimeService)
    service = _service(runtime)
    for value in _VALUES:
        toolkit = ToolkitOutput.model_validate(
            _toolkit("github", {"github_auth_type": value, "future": []}),
            from_attributes=True,
        )
        expected = (
            "authorization_required"
            if value in ("github_app_user", "github_app_platform_user")
            else "ready"
        )
        assert service._readiness(toolkit) == expected
        assert (
            service._readiness(toolkit.model_copy(update={"enabled": False}))
            == "disabled"
        )
