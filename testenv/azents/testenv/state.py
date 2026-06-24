"""Fixture setup state.json with 2-tier (``run`` + ``tc[<tc_id>]``) scope.

Saved shape::

    {
      "_meta": {"run_id": "...", "started_at": "..."},
      "run": {"user": {"email": "..."}, "ws": {...}},
      "tc": {"agent-basic": {"agent": {...}, "_finalizers": [...]}},
      "_finalizers": [
        {"setup_id": "...", "cmd": "...", "registered_at": "...", "scope": "run"}
      ],
      "_verified_at": {"user.email": "2026-04-14T00:00:00Z"}
    }

Finalizer stack is best-effort cleanup. Finalizers run in LIFO order within
their scope, and scope is kept for teardown reporting.
"""

import datetime as dt
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

STATE_ENV = "STATE_FILE"
"""Environment variable used by handlers to find the state file."""


@dataclass
class Finalizer:
    """One entry in the teardown stack.

    Attributes:
        setup_id: id of the setup that registered this teardown.
        cmd: shell command to run.
        registered_at: ISO 8601 registration timestamp.
        scope: ``run`` or ``tc``; used for reporting.
    """

    setup_id: str
    cmd: str
    registered_at: str
    scope: str = "run"


@dataclass
class State:
    """State container for one testenv run.

    Use :meth:`save` and :func:`load_state` to sync with disk.

    Internally, run/tc values are nested dictionaries. Handlers access them
    through dotted keys such as ``user.email``.
    """

    path: Path
    run_id: str
    started_at: str
    run: dict[str, Any] = field(default_factory=dict)
    tc: dict[str, dict[str, Any]] = field(default_factory=dict)
    finalizers: list[Finalizer] = field(default_factory=list)
    verified_at: dict[str, str] = field(default_factory=dict)

    # ----- dotted key helpers -------------------------------------------------

    def get_run(self, key: str, default: Any = None) -> Any:
        """Read a run-scope value by dotted key, e.g. ``get_run("user.email")``."""
        return _get_dotted(self.run, key, default)

    def set_run(self, key: str, value: Any) -> None:
        """Write a run-scope value by dotted key, e.g. ``set_run("user.email", ...)``."""
        _set_dotted(self.run, key, value)

    def get_tc(self, tc_id: str, key: str, default: Any = None) -> Any:
        """TC scope value read."""
        return _get_dotted(self.tc.get(tc_id, {}), key, default)

    def set_tc(self, tc_id: str, key: str, value: Any) -> None:
        """TC scope value write."""
        bucket = self.tc.setdefault(tc_id, {})
        _set_dotted(bucket, key, value)

    def has_provide(self, key: str, tc_id: str | None = None) -> bool:
        """Return whether a ``provides`` key is stored in state.

        When ``tc_id`` is supplied, check the TC scope first, then fall back to
        run scope.
        """
        if tc_id is not None:
            tc_bucket = self.tc.get(tc_id, {})
            if _get_dotted(tc_bucket, key, _SENTINEL) is not _SENTINEL:
                return True
        return _get_dotted(self.run, key, _SENTINEL) is not _SENTINEL

    # ----- verification freshness ----------------------------------------------

    def mark_verified(self, key: str, now: str | None = None) -> None:
        """Mark a provided key as verified for stale-threshold checks."""
        self.verified_at[key] = now or dt.datetime.now(dt.UTC).isoformat()

    def last_verified_at(self, key: str) -> str | None:
        """Return the timestamp written by ``mark_verified``, or None."""
        return self.verified_at.get(key)

    def is_stale(self, key: str, threshold_seconds: int = 3600) -> bool:
        """Return whether a key is older than the verification threshold.

        Missing or unparsable verification timestamps are treated as stale.
        """
        last = self.last_verified_at(key)
        if last is None:
            return True
        try:
            when = dt.datetime.fromisoformat(last)
        except ValueError:
            return True
        age = (dt.datetime.now(dt.UTC) - when).total_seconds()
        return age > threshold_seconds

    # ----- finalizer stack ----------------------------------------------------

    def push_finalizer(self, setup_id: str, cmd: str, scope: str = "run") -> None:
        """Push a teardown command onto the stack; caller should save afterward."""
        self.finalizers.append(
            Finalizer(
                setup_id=setup_id,
                cmd=cmd,
                registered_at=dt.datetime.now(dt.UTC).isoformat(),
                scope=scope,
            )
        )

    def pop_all_finalizers(self) -> list[Finalizer]:
        """Pop all finalizers and return them in LIFO order.

        This mutates in memory only; callers must save the state after running
        finalizers.
        """
        result = list(reversed(self.finalizers))
        self.finalizers = []
        return result

    # ----- persistence --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert state to a JSON-serializable dict."""
        return {
            "_meta": {"run_id": self.run_id, "started_at": self.started_at},
            "run": self.run,
            "tc": self.tc,
            "_finalizers": [
                {
                    "setup_id": f.setup_id,
                    "cmd": f.cmd,
                    "registered_at": f.registered_at,
                    "scope": f.scope,
                }
                for f in self.finalizers
            ],
            "_verified_at": self.verified_at,
        }

    def save(self) -> None:
        """Save the current state as JSON to ``self.path`` using atomic replace."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        tmp.replace(self.path)

    def reload(self) -> None:
        """Reload state.json from disk into this in-memory state.

        Subprocess handlers may update the state file, making the caller's
        in-memory state stale. Call this after a setup handler succeeds before
        calling ``save()`` again.
        """
        reloaded = load_state(self.path)
        self.run = reloaded.run
        self.tc = reloaded.tc
        self.finalizers = reloaded.finalizers
        self.verified_at = reloaded.verified_at
        self.run_id = reloaded.run_id
        self.started_at = reloaded.started_at


# ----- create / load -----------------------------------------------------------


def default_run_id() -> str:
    """Create a default run_id in ``YYYY-MM-DD/run-<8hex>`` format."""
    today = dt.date.today().isoformat()
    short = uuid.uuid4().hex[:8]
    return f"{today}/run-{short}"


def run_root(workdir: Path | None = None) -> Path:
    """Return the runs/ root; defaults to ``testenv/azents/runs/`` from cwd."""
    base = workdir if workdir is not None else Path.cwd()
    return base / "runs"


def state_path_for(run_id: str, workdir: Path | None = None) -> Path:
    """Return the state.json path for a run_id."""
    return run_root(workdir) / run_id / "state.json"


def new_state(run_id: str | None = None, workdir: Path | None = None) -> State:
    """Create a new unsaved state object; caller saves it when ready."""
    rid = run_id or default_run_id()
    started = dt.datetime.now(dt.UTC).isoformat()
    path = state_path_for(rid, workdir)
    return State(path=path, run_id=rid, started_at=started)


def load_state(path: Path) -> State:
    """Load state.json, or return an empty state when the file is missing."""
    if not path.exists():
        logger.info("state file %s does not exist, creating empty state", path)
        rid = path.parent.name if path.parent != path.parent.parent else default_run_id()
        return State(path=path, run_id=rid, started_at=dt.datetime.now(dt.UTC).isoformat())

    raw = cast(dict[str, Any], json.loads(path.read_text()))
    meta = cast(dict[str, Any], raw.get("_meta") or {})
    rid = cast(str, meta.get("run_id", path.parent.name))
    started = cast(str, meta.get("started_at", dt.datetime.now(dt.UTC).isoformat()))
    fins_raw = cast(list[dict[str, Any]], raw.get("_finalizers") or [])
    fins = [
        Finalizer(
            setup_id=cast(str, f.get("setup_id", "?")),
            cmd=cast(str, f.get("cmd", "")),
            registered_at=cast(str, f.get("registered_at", "")),
            scope=cast(str, f.get("scope", "run")),
        )
        for f in fins_raw
    ]
    return State(
        path=path,
        run_id=rid,
        started_at=started,
        run=cast(dict[str, Any], raw.get("run") or {}),
        tc=cast(dict[str, dict[str, Any]], raw.get("tc") or {}),
        finalizers=fins,
        verified_at=cast(dict[str, str], raw.get("_verified_at") or {}),
    )


def load_or_create(path: Path, run_id: str | None = None) -> State:
    """Load an existing state file, or create and save a new one."""
    if path.exists():
        return load_state(path)
    rid = run_id or default_run_id()
    state = State(
        path=path,
        run_id=rid,
        started_at=dt.datetime.now(dt.UTC).isoformat(),
    )
    state.save()
    return state


def state_from_env() -> State:
    """Load state from the ``STATE_FILE`` env var; used inside handlers."""
    path_raw = os.environ.get(STATE_ENV)
    if not path_raw:
        raise RuntimeError(f"environment variable {STATE_ENV} is not set")
    return load_state(Path(path_raw))


# ----- dotted key helpers ----------------------------------------------------


_SENTINEL = object()


def _get_dotted(bucket: dict[str, Any], key: str, default: Any = None) -> Any:
    """Resolve ``"a.b.c"`` as ``bucket["a"]["b"]["c"]``."""
    cursor: Any = bucket
    for part in key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def _set_dotted(bucket: dict[str, Any], key: str, value: Any) -> None:
    """Set ``"a.b.c"`` as ``bucket["a"]["b"]["c"] = value``."""
    parts = key.split(".")
    cursor: dict[str, Any] = bucket
    for part in parts[:-1]:
        existing = cursor.get(part)
        if not isinstance(existing, dict):
            existing = {}
            cursor[part] = existing
        cursor = cast(dict[str, Any], existing)
    cursor[parts[-1]] = value
