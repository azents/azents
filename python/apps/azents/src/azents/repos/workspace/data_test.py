"""Workspace row-snapshot named contract compatibility."""

import datetime

from azents.repos.workspace.data import Workspace, WorkspaceSnapshot


def test_workspace_snapshot_names_and_initial_unpacking_compatibility() -> None:
    """Named access and existing unpacking observe the same detached row projection."""
    now = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
    workspace = Workspace(
        name="Snapshot",
        handle="snapshot",
        default_runtime_profile_id=None,
        default_runtime_profile_version=1,
        created_at=now,
        updated_at=now,
    )
    snapshot = WorkspaceSnapshot(workspace_id="w" * 32, workspace=workspace)
    assert snapshot.workspace_id == "w" * 32
    assert snapshot.workspace is workspace
    workspace_id, projection = snapshot
    assert workspace_id == snapshot.workspace_id
    assert projection is snapshot.workspace
