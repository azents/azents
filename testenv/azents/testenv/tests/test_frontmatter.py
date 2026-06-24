"""Frontmatter parser unit tests."""

from pathlib import Path

import pytest

from testenv.frontmatter import (
    SpecParseError,
    parse_setup_spec,
)


def write_setup(tmp_path: Path, sid: str, **extra: str) -> Path:
    """Parse a valid setup markdown file with extra frontmatter keys."""
    lines = [
        "---",
        f"id: {sid}",
        "summary: test summary",
        "requires: []",
        "provides:",
        "  - user.email",
        "idempotent: true",
        "created: 2026-04-14",
    ]
    for k, v in extra.items():
        lines.append(f"{k}: {v}")
    lines.extend(["---", "", "# body", ""])
    md = tmp_path / f"{sid}.md"
    md.write_text("\n".join(lines))
    return md


def test_parse_setup_minimal(tmp_path: Path) -> None:
    """Default required fields are parsed."""
    md = write_setup(tmp_path, "foo-bar")
    spec = parse_setup_spec(md, base_dir=tmp_path)
    assert spec.id == "foo-bar"
    assert spec.requires == []
    assert spec.provides == ["user.email"]
    assert spec.idempotent is True
    assert spec.handler is None
    assert spec.scope == "tc"  # defaultvalue
    assert spec.locks == []


def test_parse_setup_filename_mismatch(tmp_path: Path) -> None:
    """File stem must match setup id."""
    md = tmp_path / "real-name.md"
    md.write_text(
        "\n".join(
            [
                "---",
                "id: different-id",
                "summary: test",
                "requires: []",
                "provides: []",
                "idempotent: true",
                "---",
                "",
                "body",
            ]
        )
    )
    with pytest.raises(SpecParseError, match="must match filename stem"):
        parse_setup_spec(md, base_dir=tmp_path)


def test_parse_setup_missing_required(tmp_path: Path) -> None:
    """Missing required fields fail."""
    md = tmp_path / "bad.md"
    md.write_text("---\nid: bad\n---\n\nbody\n")
    with pytest.raises(SpecParseError, match="missing required setup fields"):
        parse_setup_spec(md, base_dir=tmp_path)


def test_parse_setup_scope_validation(tmp_path: Path) -> None:
    """scope value verify."""
    md = write_setup(tmp_path, "scope-test", scope="invalid")
    with pytest.raises(SpecParseError, match="scope"):
        parse_setup_spec(md, base_dir=tmp_path)


def test_parse_setup_handler_resolution(tmp_path: Path) -> None:
    """Handler path resolves relative to base_dir."""
    md = write_setup(tmp_path, "handler-test", handler="setup_handlers/foo.py")
    spec = parse_setup_spec(md, base_dir=tmp_path)
    assert spec.handler == tmp_path / "setup_handlers/foo.py"
