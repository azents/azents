"""Docker Runtime containment AppArmor profile tests."""

from pathlib import Path

_PROFILE_PATH = Path(__file__).parents[1] / "docker/apparmor/azents-runtime-bwrap"


def test_bwrap_profile_allows_required_root_pivot() -> None:
    """The trusted bwrap bootstrap may pivot into its prepared mount namespace."""
    rules = {
        line.strip()
        for line in _PROFILE_PATH.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "pivot_root," in rules
