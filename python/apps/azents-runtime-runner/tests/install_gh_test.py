"""Build-time GitHub CLI supply-chain failures stop before installation."""

import os
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "docker" / "install-gh.sh"


@pytest.mark.parametrize("architecture", ["amd64", "arm64"])
def test_corrupt_release_never_extracts_or_replaces_tool(
    tmp_path: Path, architecture: str
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    download = tools / "curl"
    download.write_text(
        '#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\nprintf corrupted > "$2"\n'
    )
    download.chmod(0o755)
    extraction = tools / "tar"
    extraction.write_text('#!/bin/sh\ntouch "$EXTRACTION_MARKER"\nexit 1\n')
    extraction.chmod(0o755)
    prefix = tmp_path / "prefix"
    (prefix / "bin").mkdir(parents=True)
    binary = prefix / "bin" / "gh"
    binary.write_text("previous executable")
    marker = tmp_path / "extracted"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = subprocess.run(
        ["sh", str(INSTALLER), architecture, str(prefix)],
        env={
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "TMPDIR": str(scratch),
            "EXTRACTION_MARKER": str(marker),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not marker.exists()
    assert binary.read_text() == "previous executable"
    assert list(scratch.iterdir()) == []


def test_unsupported_architecture_does_not_download(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    download = tools / "curl"
    download.write_text('#!/bin/sh\ntouch "$DOWNLOAD_MARKER"\nexit 1\n')
    download.chmod(0o755)
    marker = tmp_path / "downloaded"
    result = subprocess.run(
        ["sh", str(INSTALLER), "unsupported", str(tmp_path / "prefix")],
        env={
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "DOWNLOAD_MARKER": str(marker),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Unsupported GitHub CLI architecture" in result.stderr
    assert not marker.exists()
    assert not (tmp_path / "prefix").exists()
