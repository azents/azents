"""Consumed OAuth mode projection retains existing registration comparison."""

import pytest

from .operations import _decode_registration_mode


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"github_auth_type": None},
        {"github_auth_type": 1},
        {"github_auth_type": True},
        {"github_auth_type": []},
        {"github_auth_type": {}},
        {"github_auth_type": ""},
        {"github_auth_type": "pat"},
        {"github_auth_type": "unknown"},
        {"github_auth_type": "github_app_user", "opaque": {"x": None}},
        {"github_auth_type": "github_app_platform_user"},
    ],
)
def test_registration_mode_preserves_exact_auth_comparison(
    config: dict[str, object],
) -> None:
    """Both supported registration sources retain identical stale decisions."""
    before = dict(config)
    projected = _decode_registration_mode(config)
    for expected in ["github_app_user", "github_app_platform_user"]:
        assert (projected.auth_type == expected) == (
            config.get("github_auth_type") == expected
        )
    assert config == before
