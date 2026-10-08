"""Pure subprocess/control contracts for MCP call ordering; no listener is started."""

import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

import pytest

from support.consts import REPOSITORY_ROOT
from tests.required.public.test_agent_execution_persistence import _MockMcpInstance


@pytest.mark.parametrize(
    "scenario", ["held", "disabled", "timeout", "closed", "partial"]
)
def test_one_shot_instance_barrier_is_explicit_and_bounded(
    tmp_path: Path, scenario: str
) -> None:
    """Load fixture declarations but never execute its listener entrypoint."""
    helper = REPOSITORY_ROOT / "testenv/azents/fixtures/mock_mcp_server.py"
    script = """
import os
import runpy
import select
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

Barrier = runpy.run_path(sys.argv[1])["OneShotInstanceBarrier"]
scenario = sys.argv[2]
if scenario == "disabled":
    barrier = Barrier(None, None, 0)
    barrier.wait_once()
    barrier.wait_once()
elif scenario == "partial":
    try:
        Barrier(1, None, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("Partial control descriptors must fail.")
else:
    with ExitStack() as controls:
        reached_reader, reached_writer = os.pipe()
        release_reader, release_writer = os.pipe()
        for fd in (reached_reader, reached_writer, release_reader):
            controls.callback(os.close, fd)
        barrier = Barrier(
            reached_writer, release_reader, 5 if scenario == "held" else 0
        )
        if scenario == "held":
            controls.callback(os.close, release_writer)
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(barrier.wait_once)
                try:
                    ready, _, _ = select.select([reached_reader], [], [], 5)
                    assert ready
                    assert os.read(reached_reader, 1) == b"R"
                    assert not pending.done()
                    # Only the first call participates; no second release is needed.
                    barrier.wait_once()
                finally:
                    os.write(release_writer, b"R")
                pending.result(timeout=5)
        else:
            if scenario == "closed":
                os.close(release_writer)
                expected = RuntimeError
            else:
                controls.callback(os.close, release_writer)
                expected = TimeoutError
            try:
                barrier.wait_once()
            except expected:
                pass
            else:
                raise AssertionError("An unreleased barrier must not succeed.")
"""
    subprocess.run(
        [sys.executable, "-I", "-c", script, str(helper), scenario],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_parent_releases_control_even_when_live_assertion_fails() -> None:
    """Exercise the parent channels without creating a server or subprocess."""
    with ExitStack() as controls:
        reached_reader, reached_writer = os.pipe()
        release_reader, release_writer = os.pipe()
        for fd in (reached_reader, reached_writer, release_reader, release_writer):
            controls.callback(os.close, fd)
        instance = _MockMcpInstance("unused", reached_reader, release_writer)
        os.write(reached_writer, b"R")
        with pytest.raises(AssertionError, match="live evidence failure"):
            try:
                instance.wait_until_reached(timeout=0)
                raise AssertionError("live evidence failure")
            finally:
                instance.release()
        assert os.read(release_reader, 1) == b"R"
