"""Regression tests for required Skill discovery metadata."""

from pathlib import Path

import pytest
from quick_validate import validate_skill


@pytest.mark.parametrize("field", ["name", "description"])
@pytest.mark.parametrize("value", ["", "  "])
def test_empty_discovery_metadata_is_rejected(
    tmp_path: Path, field: str, value: str
) -> None:
    metadata = {"name": "valid-skill", "description": "A valid description."}
    metadata[field] = value
    (tmp_path / "SKILL.md").write_text(
        f'---\nname: "{metadata["name"]}"\ndescription: "{metadata["description"]}"\n---\n'
    )
    valid, message = validate_skill(tmp_path)
    assert not valid
    assert "must not be empty" in message


def test_nonempty_discovery_metadata_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text(
        "---\nname: valid-skill\ndescription: Validate metadata.\n---\n"
    )
    assert validate_skill(tmp_path) == (True, "Skill is valid!")
