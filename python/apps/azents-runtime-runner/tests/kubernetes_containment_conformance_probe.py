"""Exercise the production bwrap backend inside a real Kubernetes Runner Pod."""

import asyncio
import json
import sys
import textwrap
from pathlib import Path

from azents_runtime_runner.containment import (
    ExecutionSpec,
    execution_backend_from_environment,
)
from azents_runtime_runner.environment import build_contained_agent_environment

_WORKSPACE_PATH = "/runtime/home"
_AGENT_SCRIPT = textwrap.dedent(
    """
    import json
    import os
    import pathlib
    import socket
    import sys

    workspace = pathlib.Path(sys.argv[1])
    allowed_host = sys.argv[2]
    allowed_port = int(sys.argv[3])
    denied_host = sys.argv[4]
    denied_port = int(sys.argv[5])
    status = {}
    for line in pathlib.Path("/proc/self/status").read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            status[key] = value.strip()
    capability_fields = ("CapEff", "CapPrm", "CapInh", "CapAmb", "CapBnd")
    checks = {
        "uid": os.getuid() == 1000,
        "gid": os.getgid() == 1000,
        "capabilities": all(int(status[name], 16) == 0 for name in capability_fields),
        "no_new_privileges": status.get("NoNewPrivs") == "1",
        "apparmor_enforced": pathlib.Path(
            "/proc/self/attr/current"
        ).read_text().strip() == "azents-runtime-bwrap (enforce)",
        "bwrap_hidden": not any(
            pathlib.Path(path).exists()
            for path in (
                "/usr/bin/bwrap",
                "/opt/azents-runtime/bin/bwrap",
            )
        ),
        "runner_private_hidden": not pathlib.Path(
            "/run/azents/runner-private"
        ).exists(),
        "runner_venv_hidden": not pathlib.Path(
            "/workspace/python/apps/azents-runtime-runner/.venv"
        ).exists(),
        "docker_socket_hidden": not pathlib.Path(
            "/var/run/azents-engine/docker.sock"
        ).exists(),
    }
    (workspace / "workspace-marker").write_text("workspace")
    pathlib.Path("/tmp/temporary-marker").write_text("temporary")
    with socket.create_connection((allowed_host, allowed_port), timeout=5):
        checks["allowed_egress"] = True
    try:
        with socket.create_connection((denied_host, denied_port), timeout=2):
            checks["denied_egress"] = False
    except OSError:
        checks["denied_egress"] = True
    failed = sorted(name for name, passed in checks.items() if not passed)
    print(json.dumps({"checks": checks, "failed": failed}, sort_keys=True))
    raise SystemExit(1 if failed else 0)
    """
).strip()


async def _run() -> None:
    if len(sys.argv) != 5:
        raise RuntimeError("expected allowed host/port and denied host/port arguments")
    backend = execution_backend_from_environment(workspace_path=_WORKSPACE_PATH)
    if backend.kind != "bwrap":
        raise RuntimeError("Kubernetes containment probe requires the bwrap backend")
    try:
        await backend.qualify()
        process = await backend.start(
            ExecutionSpec(
                argv=(
                    "/usr/local/bin/python",
                    "-c",
                    _AGENT_SCRIPT,
                    _WORKSPACE_PATH,
                    *sys.argv[1:],
                ),
                cwd=Path(_WORKSPACE_PATH),
                environment=build_contained_agent_environment(
                    workspace_path=_WORKSPACE_PATH,
                    operation_environment={},
                ),
                stdin=False,
                managed=False,
            )
        )
        stdout, stderr, returncode = await asyncio.gather(
            process.stdout.read(),
            process.stderr.read(),
            process.wait(),
        )
        if returncode != 0:
            raise RuntimeError(
                "contained Agent probe failed: "
                f"stdout={stdout.decode()!r} stderr={stderr.decode()!r}"
            )
        result = json.loads(stdout)
        if not isinstance(result, dict) or result.get("failed") != []:
            raise RuntimeError("contained Agent probe returned invalid evidence")
        sys.stdout.write(f"{json.dumps(result, sort_keys=True)}\n")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(_run())
