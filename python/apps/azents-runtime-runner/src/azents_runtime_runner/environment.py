"""Code-owned contained Agent process environment construction."""

import os
from collections.abc import Mapping

_DEFAULT_PATH = (
    "/usr/local/bin/corepack-shims:/home/agent/.local/bin:/usr/local/bin:/usr/bin:/bin"
)
_SAFE_SOURCE_NAMES = (
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "TERM",
    "TZ",
)
_RESERVED_EXACT_NAMES = frozenset(
    {
        "HOME",
        "PATH",
        "SHELL",
        "TMP",
        "TMPDIR",
        "TEMP",
    }
)
_RESERVED_PREFIXES = (
    "AZ_RUNTIME_",
    "AZENTS_RUNTIME_",
)


def build_contained_agent_environment(
    *,
    workspace_path: str,
    operation_environment: Mapping[str, str],
    source_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build one contained Agent environment without Runner inheritance."""
    source = os.environ if source_environment is None else source_environment
    environment = {
        name: value
        for name in _SAFE_SOURCE_NAMES
        if (value := source.get(name)) is not None
    }
    environment.setdefault("PATH", _DEFAULT_PATH)
    environment.setdefault("LANG", "C.UTF-8")
    environment["HOME"] = workspace_path
    environment["SHELL"] = "/bin/bash"
    environment["TMPDIR"] = "/tmp"
    for name, value in operation_environment.items():
        if _reserved_environment_name(name):
            raise ValueError(f"Agent environment name is reserved: {name}")
        environment[name] = value
    return environment


def _reserved_environment_name(name: str) -> bool:
    if name in _RESERVED_EXACT_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in _RESERVED_PREFIXES)
