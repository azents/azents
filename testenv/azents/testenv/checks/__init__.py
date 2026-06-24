"""Preflight check registry.

Exports the ordered production preflight check list through ``all_checks()``. The
registry is explicit instead of auto-discovered so check ordering and dependency
relationships remain easy to review.

Tests may instantiate individual checks directly when they need to inject
external resources such as a shared HTTP client or a mock subprocess runner.
"""

from .base import Check
from .config import EnvFileExists, LLMApiKeyAvailable, RequiredEnvVars
from .images import DockerSocketAccessible
from .infra import (
    PostgresConnectable,
    PostgresContainerHealthy,
    RustfsReachable,
    ValkeyReachable,
)
from .ports import DevserverPortsFree
from .runtime_state import DbMigrationCurrent
from .system import (
    DockerComposeAvailable,
    DockerRunning,
    PythonDepsInstalled,
    PythonVersion,
    RepoRoot,
    TmuxInstalled,
    UvInstalled,
)
from .tunnel import TailscaleFunnelHealthy
from .web import (
    NodeInstalled,
    NointernWebDepsInstalled,
    NointernWebPortFree,
    PnpmInstalled,
)


def all_checks() -> list[Check]:
    """Return the registered preflight checks in execution order.

    Callers should treat the returned list as owned by that run. Checks do not
    require a DI container.
    """
    return [
        # system
        RepoRoot(),
        DockerRunning(),
        DockerSocketAccessible(),
        DockerComposeAvailable(),
        UvInstalled(),
        TmuxInstalled(),
        PythonVersion(),
        PythonDepsInstalled(),
        # ports
        DevserverPortsFree(),
        # Stage 4 — azents-web (system + ports + config)
        NodeInstalled(),
        PnpmInstalled(),
        NointernWebPortFree(),
        NointernWebDepsInstalled(),
        # config
        EnvFileExists(),
        RequiredEnvVars(),
        LLMApiKeyAvailable(),
        # infra
        PostgresContainerHealthy(),
        PostgresConnectable(),
        ValkeyReachable(),
        RustfsReachable(),
        # runtime_state
        DbMigrationCurrent(),
        # Stage 5 — integrations (Tailscale Funnel public URL)
        TailscaleFunnelHealthy(),
    ]
