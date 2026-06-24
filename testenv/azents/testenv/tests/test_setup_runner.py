"""Setup runner DAG / 3-case decision unit tests.

actual handler execution through the subprocess path.
These tests verify :func:`resolve_setup_dag` decisions.
"""

from pathlib import Path

import pytest

from testenv.setup_runner import SetupResolveError, resolve_setup_dag
from testenv.types import SetupSpec


def _spec(
    sid: str,
    requires: list[str] | None = None,
    provides: list[str] | None = None,
    idempotent: bool = True,
) -> SetupSpec:
    """Create a SetupSpec for tests."""
    return SetupSpec(
        id=sid,
        handler=None,
        requires=requires or [],
        provides=provides or [],
        idempotent=idempotent,
        verify=None,
        reclaim=None,
        teardown=None,
        scope="tc",
        locks=[],
        markdown_path=Path(f"/tmp/{sid}.md"),
    )


def test_resolve_topological_order() -> None:
    """Resolve transitive setup dependencies."""
    setups = {
        "a": _spec("a"),
        "b": _spec("b", requires=["a"]),
        "c": _spec("c", requires=["a"]),
        "d": _spec("d", requires=["b", "c"]),
    }
    order = resolve_setup_dag(["d"], setups)
    ids = [s.id for s in order]
    # a requires b and c; d has no dependencies.
    assert ids[0] == "a"
    assert ids[-1] == "d"
    # b and c must come before a; d can be anywhere valid.
    assert ids.index("b") > 0 and ids.index("b") < ids.index("d")
    assert ids.index("c") > 0 and ids.index("c") < ids.index("d")


def test_resolve_unknown_setup() -> None:
    """Unknown setup references are rejected."""
    setups = {"a": _spec("a", requires=["missing"])}
    with pytest.raises(SetupResolveError, match="unknown setup"):
        resolve_setup_dag(["a"], setups)


def test_resolve_cycle() -> None:
    """Detect dependency cycles."""
    setups = {
        "a": _spec("a", requires=["b"]),
        "b": _spec("b", requires=["a"]),
    }
    with pytest.raises(SetupResolveError, match="cycle"):
        resolve_setup_dag(["a"], setups)


def test_resolve_single_no_deps() -> None:
    """Run required setups in dependency order."""
    setups = {"solo": _spec("solo")}
    order = resolve_setup_dag(["solo"], setups)
    assert [s.id for s in order] == ["solo"]
