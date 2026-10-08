"""Typed confirmation-impact persistence boundary regressions."""

import pytest
from pydantic import ValidationError

from azents.core.github_system_setting_data import PlatformGitHubAppImpact
from azents.repos.github_platform_system_setting.data import (
    PlatformGitHubAppConfirmationImpact,
)


def _impact(actions: tuple[str, ...]) -> PlatformGitHubAppImpact:
    """Build typed impact evidence with a required action choice."""
    return PlatformGitHubAppImpact(
        app_id_changed=True,
        affected_user_count=1,
        affected_installation_count=2,
        affected_toolkit_count=3,
        affected_agent_count=4,
        current_app_id_source="admin",
        confirmation_actions=actions,
    )


@pytest.mark.parametrize("actions", [(), ("activate",)])
def test_impact_round_trip_preserves_existing_flat_metadata(
    actions: tuple[str, ...],
) -> None:
    """Storage arrays round-trip to typed actions with unchanged response metadata."""
    domain = _impact(actions)
    typed = PlatformGitHubAppConfirmationImpact.from_impact(domain)
    metadata = typed.model_dump(mode="json")
    expected = domain.to_metadata()
    expected["confirmation_required"] = domain.confirmation_required
    assert metadata == expected
    assert PlatformGitHubAppConfirmationImpact.model_validate(metadata) == typed
    assert typed.confirmation_actions == actions
    assert typed.confirmation_required is bool(actions)


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": "not a protocol field"},
        {"confirmation_actions": ["activate", 1]},
        {"confirmation_required": False},
        {"affected_agent_count": "4"},
    ],
)
def test_impact_decoder_rejects_untyped_or_inconsistent_snapshot(
    change: dict[str, object],
) -> None:
    """Invalid stored evidence cannot establish a confirmation action."""
    metadata = PlatformGitHubAppConfirmationImpact.from_impact(
        _impact(("activate",))
    ).model_dump(mode="json")
    metadata.update(change)
    with pytest.raises(ValidationError):
        PlatformGitHubAppConfirmationImpact.model_validate(metadata)
