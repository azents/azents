"""Agent Workspace source contract tests."""

from pathlib import Path

_HISTORICAL_AGENT_WORKSPACE = "/workspace/agent"
_PRODUCTION_ROOTS = (
    "proto",
    "python/apps/azents/src",
    "python/apps/azents-runtime-runner/src",
    "python/apps/azents-runtime-provider-docker/src",
    "python/apps/azents-runtime-provider-kubernetes/src",
    "python/libs/azents-runtime-control/src",
)


def test_production_sources_do_not_embed_historical_agent_workspace() -> None:
    """Runtime-specific workspace behavior must not regain a fixed root."""
    repository_root = _repository_root()
    offenders: list[str] = []
    for relative_root in _PRODUCTION_ROOTS:
        for path in (repository_root / relative_root).rglob("*"):
            if not _is_scanned_source(path):
                continue
            if _HISTORICAL_AGENT_WORKSPACE in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(repository_root).as_posix())

    assert offenders == []


def _repository_root() -> Path:
    """Find the repository root from this source checkout."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "proto").is_dir() and (parent / "python").is_dir():
            return parent
    raise RuntimeError("Azents repository root not found")


def _is_scanned_source(path: Path) -> bool:
    """Return whether a path is production Python or protobuf source."""
    if not path.is_file() or path.suffix not in {".py", ".proto"}:
        return False
    if path.name.startswith("test_") or path.name.endswith("_test.py"):
        return False
    return not path.name.endswith(("_pb2.py", "_pb2_grpc.py"))
