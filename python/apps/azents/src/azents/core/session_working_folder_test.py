"""Tests for Session working-folder path policy."""

import pytest

from .session_working_folder import (
    build_session_working_folder_path,
    validate_session_working_folder_path,
)


def test_build_session_working_folder_path_uses_root_session_handle() -> None:
    """Build the canonical path directly below the managed Session root."""
    assert (
        build_session_working_folder_path(
            "cactus-river-window",
            workspace_root="/runtime/agent",
        )
        == "/runtime/agent/.azents/sessions/cactus-river-window"
    )


@pytest.mark.parametrize("handle", ("", ".", "..", "nested/path"))
def test_build_session_working_folder_path_rejects_non_component_handles(
    handle: str,
) -> None:
    """Reject inputs that cannot form one managed path component."""
    with pytest.raises(ValueError, match="valid path component"):
        build_session_working_folder_path(handle, workspace_root="/runtime/agent")


@pytest.mark.parametrize(
    "path",
    (
        "/runtime/agent/.azents/sessions/cactus-river-window",
        "/runtime/agent/.azents/sessions/test-session-handle",
    ),
)
def test_validate_session_working_folder_path_accepts_managed_leaf(path: str) -> None:
    """Accept an exact direct child of the managed Session root."""
    assert (
        validate_session_working_folder_path(path, workspace_root="/runtime/agent")
        == path
    )


@pytest.mark.parametrize(
    "path",
    (
        "runtime/agent/.azents/sessions/cactus-river-window",
        "/runtime/agent/.azents/sessions",
        "/runtime/agent/.azents/sessions/cactus-river-window/child",
        "/runtime/agent/.azents/sessions/../escape",
        "/runtime/agent/reports",
    ),
)
def test_validate_session_working_folder_path_rejects_outside_or_noncanonical_paths(
    path: str,
) -> None:
    """Reject paths that do not name one exact managed Session folder."""
    with pytest.raises(ValueError, match="outside the managed root"):
        validate_session_working_folder_path(path, workspace_root="/runtime/agent")
