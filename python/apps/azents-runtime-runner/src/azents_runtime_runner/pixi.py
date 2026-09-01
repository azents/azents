"""Configure Pixi to use the persistent Agent Workspace."""

import os
from collections.abc import Mapping
from pathlib import Path


def prepare_pixi_environment(
    *,
    workspace_path: str,
    machine: str,
) -> Mapping[str, str]:
    """Place Pixi environments and cache under the Agent Workspace."""
    workspace = Path(workspace_path)
    pixi_home = workspace / ".pixi"
    pixi_cache = workspace / ".cache/pixi"
    pixi_home.mkdir(parents=True, exist_ok=True)
    pixi_cache.mkdir(parents=True, exist_ok=True)

    path = os.environ.get("PATH", "")
    base_path_parts = tuple(part for part in path.split(os.pathsep) if part)
    base_path = os.pathsep.join(dict.fromkeys(base_path_parts))
    pixi_bin = str(pixi_home / "bin")
    return {
        "PIXI_HOME": str(pixi_home),
        "PIXI_CACHE_DIR": str(pixi_cache),
        "PIXI_PLATFORM": _pixi_platform(machine),
        "PIXI_BASE_PATH": base_path,
        "PATH": os.pathsep.join(dict.fromkeys((pixi_bin, *base_path_parts))),
    }


def _pixi_platform(machine: str) -> str:
    normalized = machine.lower()
    if normalized in {"x86_64", "amd64"}:
        return "linux-64"
    if normalized in {"aarch64", "arm64"}:
        return "linux-aarch64"
    raise ValueError(f"Unsupported Pixi machine architecture: {machine}")
