"""Personal installation authority precedes token, cache and background use."""

import dataclasses
import json
from unittest.mock import AsyncMock, Mock

import pytest

from azents.core.github_installation import GitHubInstallationSnapshot
from azents.core.github_system_setting import (
    PlatformGitHubAppConfig,
    PlatformGitHubAppSecrets,
)
from azents.core.personal_toolkit_runtime import ToolkitEffectAdmission
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingFieldSource,
    SystemSettingSection,
)
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.system_setting_registry import get_system_setting_registry
from azents.core.tools import GitHubToolkitConfig, ResolveContext
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.personal_admission import PersonalToolkitAdmission
from azents.engine.tools import github as github_module
from azents.engine.tools.github import GitHubToolkit, GitHubToolkitProvider
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.toolkit.personal_runtime_test import Harness
from azents.repos.toolkit.personal_runtime_test import (
    fixture as fixture,  # noqa: PLC0414 -- real committed ownership fixture
)
from azents.repos.toolkit.personal_runtime_test import (
    runtime as runtime,  # noqa: PLC0414 -- canonical root and current source
)
from azents.repos.toolkit.personal_test import creation
from azents.services.github_platform_system_setting.runtime import (
    ResolvedPlatformGitHubApp,
)


@pytest.mark.parametrize(
    "change",
    [
        "inventory_before",
        "token_gap",
        "cached_withdrawal",
        "app_changed",
        "other_user_inventory",
    ],
)
async def test_personal_platform_token_authority_does_not_trust_prepared_inventory(
    runtime: Harness,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    h = runtime
    f = h.foundation
    payloads = Mock(spec=SystemSettingPayloadResolver)
    payloads.registry = get_system_setting_registry()
    payloads.resolve_current.return_value = ResolvedSystemSetting(
        SystemSettingSection.PLATFORM_GITHUB_APP,
        1,
        0,
        PlatformGitHubAppConfig(app_id="123"),
        PlatformGitHubAppSecrets.model_construct(
            private_key="fixture-private-key", client_secret="fixture-client-secret"
        ),
        {"app_id": SystemSettingFieldSource.ENVIRONMENT},
        "fixture-generation",
    )
    h.repository = dataclasses.replace(h.repository, platform_settings=payloads)
    config = GitHubToolkitConfig(
        github_auth_type="github_app_platform", inject_runtime_environment=True
    )
    saved = await f.operations.create(
        user_id=f.user_id,
        workspace_id=f.workspace_ids[0],
        create=creation().model_copy(
            update={
                "toolkit_type": "github",
                "config": config.model_dump(),
                "credentials": json.dumps(
                    {
                        "type": "github_app_platform",
                        "app_id": "123",
                        "installations": [
                            {
                                "installation_id": "42",
                                "account_login": "fixture",
                                "account_type": "Organization",
                                "account_avatar_url": None,
                            }
                        ],
                    }
                ),
            }
        ),
    )
    inventory = GithubUserInstallationRepository()

    async def inventory_for(user_id: str, include: bool) -> None:
        async with f.writes() as session:
            await inventory.sync(
                session,
                user_id,
                "123",
                [GitHubInstallationSnapshot(42, 123, "fixture", "Organization", None)]
                if include
                else [],
            )

    await inventory_for(f.user_id, True)
    root = await h.root(f.user_id, 0)
    [source] = await h.sources(root)
    guard: ToolkitEffectAdmission = PersonalToolkitAdmission(
        h.repository, source.target
    )
    platform = AsyncMock()
    platform.resolve.return_value = ResolvedPlatformGitHubApp(
        "123",
        "fixture-client",
        "fixture-private-key",
        "fixture-client-secret",
        SystemSettingFieldSource.ENVIRONMENT,
        "fixture-generation",
    )
    provider = GitHubToolkitProvider(
        platform_runtime=platform,
        user_runtime=Mock(),
        user_mcp_server_url=None,
        snapshot_factory=None,
    )
    resolved = await provider.resolve(
        config,
        ResolveContext(
            toolkit_id=saved.id,
            toolkit_name=saved.name,
            credentials_json=saved.credentials,
            agent_id=root.agent_id,
            session_id=root.owner.session_id,
            workspace_id=root.workspace_id,
            workspace_handle="workload",
            web_url="https://app.test",
            oauth_secret_key=None,
            effect_admission=guard,
        ),
    )
    assert isinstance(resolved, GitHubToolkit)
    resolved.bind_effect_admission(guard)
    [binding] = resolved._installation_bindings

    async def exchange(*args: object) -> str:
        del args
        if change == "token_gap":
            await inventory_for(f.user_id, False)
        return "fixture-installation-token"

    token = AsyncMock(side_effect=exchange)
    monkeypatch.setattr(github_module, "_exchange_app_token", token)
    if change == "cached_withdrawal":
        assert (
            await resolved._get_cached_installation_token("42", binding.token_provider)
            == "fixture-installation-token"
        )
        token.assert_awaited_once()
        token.reset_mock()
    if change in ("inventory_before", "cached_withdrawal", "other_user_inventory"):
        await inventory_for(f.user_id, False)
        if change == "other_user_inventory":
            await inventory_for(f.other_user_id, True)
    elif change == "app_changed":
        payloads.resolve_current.return_value = dataclasses.replace(
            payloads.resolve_current.return_value,
            config=PlatformGitHubAppConfig(app_id="456"),
        )
    with pytest.raises(FunctionToolError):
        await resolved._get_cached_installation_token("42", binding.token_provider)
    if change == "token_gap":
        token.assert_awaited_once()
    else:
        token.assert_not_awaited()
    await resolved._prepare_installation_mcp(binding)
    assert binding.mcp_toolkit is None
    assert binding.lazy_mcp_error is not None
    assert "fixture-installation-token" not in binding.lazy_mcp_error
    if change == "token_gap":
        token.assert_awaited_once()
    else:
        token.assert_not_awaited()
