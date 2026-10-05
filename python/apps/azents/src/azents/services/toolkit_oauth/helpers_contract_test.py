"""Stored credential decoders preserve opaque compatibility at their boundary."""

import json
from unittest.mock import AsyncMock

import pytest

from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.toolkit_oauth.data import ToolkitConnectionTestInput
from azents.services.toolkit_oauth.helpers import (
    bind_platform_app_test_credentials,
    merge_saved_test_credentials,
)


@pytest.mark.parametrize(
    "credentials",
    [
        None,
        "null",
        "[]",
        '  { "type": "token", "token": "same bytes" }  ',
        '{"type":false,"unknown":[1]}',
    ],
)
async def test_nonplatform_credential_passthrough_keeps_original_bytes(
    credentials: str | None,
) -> None:
    """Unconsumed provider credentials never get normalized or resolved."""
    platform = AsyncMock(spec=PlatformGitHubAppRuntimeService)
    assert (
        await bind_platform_app_test_credentials(credentials, platform) == credentials
    )
    platform.resolve.assert_not_awaited()


async def test_platform_invalid_json_preserves_original_decode_failure() -> None:
    """The direct binding boundary still rejects malformed JSON."""
    platform = AsyncMock(spec=PlatformGitHubAppRuntimeService)
    with pytest.raises(json.JSONDecodeError):
        await bind_platform_app_test_credentials("malformed", platform)
    platform.resolve.assert_not_awaited()


@pytest.mark.parametrize("saved", [None, "null", "[]", "malformed"])
def test_saved_connection_test_credentials_decode_before_merge(
    saved: str | None,
) -> None:
    """Stored malformed objects remain empty while typed submitted edits survive."""
    merged = merge_saved_test_credentials(
        ToolkitConnectionTestInput(
            toolkit_type="token",
            config={},
            credentials={"type": "token", "unknown": {"opaque": [False, 0]}},
            toolkit_config_id=None,
        ),
        saved,
    )
    assert merged is not None
    assert json.loads(merged) == {"type": "token", "unknown": {"opaque": [False, 0]}}
