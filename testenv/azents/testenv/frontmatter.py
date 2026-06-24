"""Markdown frontmatter parser — fixture setup spec loader.

``python-frontmatter`` validates required fields and converts optional fields
(``handler``, ``locks``, ``scope``, ``teardown``, ``reclaim``) into typed objects.

Lint behavior:
    - missing required fields raise ``SpecParseError``
    - unknown fields are logged as warnings because strict mode is not enabled.

Related design: ``docs/azents/design/testenv-qa-fixtures.md``.
"""

import logging
from pathlib import Path
from typing import Any, cast

import frontmatter

from .types import SetupScope, SetupSpec

logger = logging.getLogger(__name__)


class SpecParseError(ValueError):
    """Frontmatter required field missing or validation error."""


def _load_frontmatter(path: Path) -> dict[str, Any]:
    """Return the parsed frontmatter dict from a Markdown file.

    Use ``frontmatter.parse()`` instead of ``frontmatter.load()`` because the
    latter builds a ``Post`` object and can conflict with a frontmatter field
    named ``handler``.
    """
    raw = path.read_text(encoding="utf-8")
    metadata, _body = frontmatter.parse(raw)
    return cast(dict[str, Any], metadata)


# ----- Field helpers --------------------------------------------------------


def _as_str_list(value: object, field_name: str, path: Path) -> list[str]:
    """Validate a YAML field as list[str]."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise SpecParseError(f"{path}: '{field_name}' must be a list, got {type(value).__name__}")
    result: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, str):
            raise SpecParseError(
                f"{path}: '{field_name}' items must be strings, got {type(item).__name__}"
            )
        result.append(item)
    return result


def _resolve_handler(value: object, path: Path, base_dir: Path) -> Path | None:
    """Resolve the optional ``handler:`` field as a path."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SpecParseError(f"{path}: 'handler' must be a string path")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate


# ----- Setup -----------------------------------------------------------------


REQUIRED_SETUP_FIELDS = {"id", "summary", "idempotent"}
KNOWN_SETUP_FIELDS = {
    "id",
    "summary",
    "handler",
    "requires",
    "provides",
    "idempotent",
    "verify",
    "reclaim",
    "teardown",
    "scope",
    "locks",
    "llm_key_required",
    "created",
}


def parse_setup_spec(path: Path, base_dir: Path | None = None) -> SetupSpec:
    """Parse a setup Markdown file into :class:`SetupSpec`.

    :param path: setup markdown file path, for example
        ``setup/test-user-workspace.md``.
    :param base_dir: base directory for resolving the ``handler:`` path. The
        default is ``path.parent.parent`` (usually ``testenv/azents/``).
    :raises SpecParseError: when required fields are missing or invalid.
    """
    base = base_dir if base_dir is not None else path.parent.parent
    meta = _load_frontmatter(path)

    missing = REQUIRED_SETUP_FIELDS - meta.keys()
    if missing:
        raise SpecParseError(f"{path}: missing required setup fields: {sorted(missing)}")

    sid_raw = meta["id"]
    if not isinstance(sid_raw, str):
        raise SpecParseError(f"{path}: 'id' must be a string")
    if sid_raw != path.stem:
        raise SpecParseError(f"{path}: id='{sid_raw}' must match filename stem '{path.stem}'")
    idem_raw = meta["idempotent"]
    if not isinstance(idem_raw, bool):
        raise SpecParseError(f"{path}: 'idempotent' must be a bool")

    # Scope default: omitted scope means ``tc`` for the logical-probe tier.
    scope_raw = meta.get("scope", "tc")
    if scope_raw == "run":
        scope: SetupScope = "run"
    elif scope_raw == "tc":
        scope = "tc"
    else:
        raise SpecParseError(f"{path}: 'scope' must be 'run' or 'tc', got {scope_raw!r}")

    verify = meta.get("verify")
    if verify is not None and not isinstance(verify, str):
        raise SpecParseError(f"{path}: 'verify' must be a string (shell command)")

    reclaim = meta.get("reclaim")
    if reclaim is not None and not isinstance(reclaim, str):
        raise SpecParseError(f"{path}: 'reclaim' must be a string (shell command)")

    teardown = meta.get("teardown")
    if teardown is not None and not isinstance(teardown, str):
        raise SpecParseError(f"{path}: 'teardown' must be a string (shell command)")

    unknown = meta.keys() - KNOWN_SETUP_FIELDS
    if unknown:
        logger.warning(
            "setup %s: unknown frontmatter fields (ignored): %s",
            sid_raw,
            sorted(unknown),
        )

    return SetupSpec(
        id=sid_raw,
        handler=_resolve_handler(meta.get("handler"), path, base),
        requires=_as_str_list(meta.get("requires"), "requires", path),
        provides=_as_str_list(meta.get("provides"), "provides", path),
        idempotent=idem_raw,
        verify=verify,
        reclaim=reclaim,
        teardown=teardown,
        scope=scope,
        locks=_as_str_list(meta.get("locks"), "locks", path),
        markdown_path=path,
    )


# ----- Directory loaders -----------------------------------------------------


def load_all_setups(setup_dir: Path) -> dict[str, SetupSpec]:
    """Load all setup `.md` files except ``INDEX.md``.

    :returns: mapping of ``{setup_id: SetupSpec}``.
    """
    setups: dict[str, SetupSpec] = {}
    for md in sorted(setup_dir.glob("*.md")):
        if md.name == "INDEX.md":
            continue
        spec = parse_setup_spec(md)
        setups[spec.id] = spec
    return setups


def find_setup_by_id(setup_dir: Path, setup_id: str) -> SetupSpec:
    """Load a setup by setup id."""
    md = setup_dir / f"{setup_id}.md"
    if not md.exists():
        raise SpecParseError(f"setup not found: {setup_id} (searched {md})")
    return parse_setup_spec(md)
