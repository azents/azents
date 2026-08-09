"""Trusted bubblewrap launcher tests."""

import os

import pytest

from azents_runtime_runner.bwrap_launcher import (
    _bwrap_arguments,
    _seccomp_program_fd,
)


def test_bwrap_arguments_inject_seccomp_before_command() -> None:
    arguments = [
        "/opt/azents-runtime/bin/bwrap",
        "--unshare-user",
        "--",
        "/bin/true",
    ]

    assert _bwrap_arguments(arguments, 17) == [
        "/opt/azents-runtime/bin/bwrap",
        "--unshare-user",
        "--seccomp",
        "17",
        "--",
        "/bin/true",
    ]


def test_bwrap_arguments_require_command_separator() -> None:
    with pytest.raises(RuntimeError, match="separator"):
        _bwrap_arguments(["/opt/azents-runtime/bin/bwrap"], 17)


def test_seccomp_program_exports_nonempty_bpf() -> None:
    descriptor = _seccomp_program_fd()
    try:
        assert os.fstat(descriptor).st_size > 0
    finally:
        os.close(descriptor)
