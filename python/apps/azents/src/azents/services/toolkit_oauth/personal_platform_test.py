"""Platform test credentials are admitted before any server App token or MCP use."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.core.personal_toolkit import (
    PersonalToolkitConfigurationConflict,
    PersonalToolkitProviderAuthorityDenied,
)
from azents.core.tools import TestConnectionResult as ConnectionResult
from azents.engine.tools import github as github_provider
from azents.engine.tools.github import GitHubToolkitProvider
from azents.repos.toolkit.data import ToolkitCreation
from azents.services.github_user_oauth.personal_installations_test import (
    InstallationHarness,
    oauth_state,
)
from azents.services.github_user_oauth.personal_installations_test import (
    fixture as fixture,  # noqa: PLC0414 -- shared PostgreSQL foundation
)
from azents.services.github_user_oauth.personal_installations_test import (
    harness as harness,  # noqa: PLC0414 -- current account and owned Toolkit fixture
)
from azents.services.github_user_oauth.personal_installations_test import (
    installations as installations,  # noqa: PLC0414 -- real inventory and fake Provider
)
from azents.services.toolkit_oauth import helpers
from azents.services.toolkit_oauth.data import (
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
)
from azents.services.toolkit_oauth.personal import PersonalToolkitOAuthService


def credentials(app_id: str, installation_id: int | str) -> dict[str, object]:
    return {
        "type": "github_app_platform",
        "app_id": app_id,
        "installations": [
            {
                "installation_id": str(installation_id),
                "account_login": "fixture-org",
                "account_type": "Organization",
                "account_avatar_url": None,
            }
        ],
    }


@pytest.mark.parametrize(
    "scenario",
    [
        "draft_foreign",
        "saved_withdrawn",
        "saved_stale_app",
        "draft_gap",
        "draft_invalid",
        "allowed",
    ],
)
async def test_platform_inventory_checked_before_token_exchange_or_mcp(
    installations: InstallationHarness,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    h = installations
    subject = h.management.subject
    await h.service.sync(subject, code="fixture-code", state=await oauth_state(h))
    assert h.platform.app_id is not None
    provider = GitHubToolkitProvider(
        platform_runtime=h.runtime,
        user_runtime=MagicMock(),
        user_mcp_server_url=None,
        snapshot_factory=MagicMock(),
    )
    token = AsyncMock(return_value="fixture-installation-token")
    mcp = AsyncMock(
        return_value=ConnectionResult(
            success=True,
            message="fixture-ok",
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=None,
        )
    )
    monkeypatch.setattr(github_provider, "_exchange_app_token", token)
    monkeypatch.setattr(github_provider, "test_mcp_transport", mcp)
    service = PersonalToolkitOAuthService(
        h.management.repository, h.service.config, {"github": provider}, h.runtime
    )
    config: dict[str, object] = {"github_auth_type": "github_app_platform"}
    saved_id = None
    if scenario in ("saved_withdrawn", "saved_stale_app"):
        saved = await h.management.repository.create(
            subject,
            ToolkitCreation(
                toolkit_type="github",
                slug="fixture",
                name="Fixture",
                config=config,
                credentials=json.dumps(
                    credentials(
                        "old-app"
                        if scenario == "saved_stale_app"
                        else h.platform.app_id,
                        42,
                    )
                ),
                always_expose_tools=False,
            ),
            platform_authority=None,
        )
        saved_id = saved.toolkit.id
        if scenario == "saved_withdrawn":
            h.listing.return_value = []
            await h.service.sync(
                subject, code="fixture-new-code", state=await oauth_state(h)
            )
    if scenario == "draft_gap":
        original = helpers.prepare_platform_app_test_credentials

        async def withdraw(
            value: str | None, runtime: object
        ) -> helpers.PreparedPlatformTestCredentials:
            assert runtime is h.runtime
            prepared = await original(value, h.runtime)
            h.listing.return_value = []
            await h.service.sync(
                subject, code="fixture-new-code", state=await oauth_state(h)
            )
            return prepared

        monkeypatch.setattr(helpers, "prepare_platform_app_test_credentials", withdraw)
    if saved_id is not None:
        assert saved_id is not None
        with pytest.raises(
            PersonalToolkitConfigurationConflict
            if scenario == "saved_stale_app"
            else PersonalToolkitProviderAuthorityDenied
        ):
            await service.test_saved(subject, saved_id)
    else:
        request = ToolkitConnectionTestInput(
            toolkit_type="github",
            config=config,
            credentials=credentials(
                h.platform.app_id,
                "invalid-id"
                if scenario == "draft_invalid"
                else 99
                if scenario == "draft_foreign"
                else 42,
            ),
            toolkit_config_id=None,
        )
        if scenario == "allowed":
            assert (await service.test_unsaved(subject, request)).success
        else:
            with pytest.raises(
                ToolkitOAuthError
                if scenario == "draft_invalid"
                else PersonalToolkitProviderAuthorityDenied
            ):
                await service.test_unsaved(subject, request)
    if scenario == "allowed":
        token.assert_awaited_once_with(h.platform.app_id, h.platform.private_key, "42")
        mcp.assert_awaited_once()
    else:
        token.assert_not_awaited()
        mcp.assert_not_awaited()
