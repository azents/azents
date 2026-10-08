"""Named patch identities and strict missing-target classification fixtures."""

import os
from pathlib import Path

import pytest

from azents_runtime_runner.apply_patch import _stat_signature
from azents_runtime_runner.operations import _stat_payload
from azents_runtime_runner.workspace import Workspace


def test_patch_stat_identity_has_named_fields(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("snapshot")
    source.chmod(0o640)
    value = source.stat()
    signature = _stat_signature(value)
    assert signature.device == value.st_dev
    assert signature.inode == value.st_ino
    assert signature.mode == value.st_mode
    assert signature.size == len(b"snapshot")
    assert signature.mtime_ns == value.st_mtime_ns
    assert signature == _stat_signature(source.stat())
    source.chmod(0o600)
    assert signature != _stat_signature(source.stat())


@pytest.mark.parametrize(
    "failure_type", [FileNotFoundError, NotADirectoryError, PermissionError, OSError]
)
def test_symlink_stat_distinguishes_missing_from_io_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[OSError],
) -> None:
    """Synthetic OS errors exercise classification without permission probing."""
    target = tmp_path / "target"
    target.write_text("fixture")
    link = tmp_path / "link"
    link.symlink_to(target)
    workspace = Workspace(str(tmp_path))
    original_stat = Path.stat

    def failing_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if path == target:
            raise failure_type("synthetic stat failure")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", failing_stat)
    if failure_type in {FileNotFoundError, NotADirectoryError}:
        assert _stat_payload(link, workspace)["resolved_kind"] == "missing"
    else:
        with pytest.raises(failure_type):
            _stat_payload(link, workspace)
