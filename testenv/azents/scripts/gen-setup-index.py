# ruff: noqa: E501
"""Setup INDEX translated createtranslated.

`testenv/azents/setup/*.md` translated frontmatter translated translated translated filetranslated
translated translated translated translated:

1. `testenv/azents/setup/INDEX.md` translated `<!-- AUTO-GENERATED:START/END -->`
2. `testenv/azents/AGENTS.md` translated `<!-- SETUP-LIST:START/END -->`

use:

    cd testenv/azents
    uv run python scripts/gen-setup-index.py

translated translated exit 0, translated translated filetranslated updatetranslated exit 0.
translated translated setup filetranslated translated stderr translated translated + exit 1.

CI translated translated translated runtranslated translated `git diff --exit-code` translated drift translated translated.
"""

import re
import sys
from pathlib import Path

import frontmatter

ROOT = Path(__file__).resolve().parent.parent
SETUP_DIR = ROOT / "setup"
INDEX_PATH = SETUP_DIR / "INDEX.md"
AGENTS_PATH = ROOT / "AGENTS.md"

SETUP_MARKER_START = "<!-- AUTO-GENERATED:START -->"
SETUP_MARKER_END = "<!-- AUTO-GENERATED:END -->"
LIST_MARKER_START = "<!-- SETUP-LIST:START -->"
LIST_MARKER_END = "<!-- SETUP-LIST:END -->"


def _load_meta(path: Path) -> dict[str, object]:
    """frontmatter.parse() translated metadata translated return (``handler`` field translated translated)."""
    raw = path.read_text(encoding="utf-8")
    metadata, _body = frontmatter.parse(raw)
    return dict(metadata)


def collect_setups() -> list[dict[str, object]]:
    """setup/ translated translated .md (INDEX translated) translated frontmatter translated translated."""
    rows: list[dict[str, object]] = []
    for md in sorted(SETUP_DIR.glob("*.md")):
        if md.name == "INDEX.md":
            continue
        meta = _load_meta(md)
        rows.append(
            {
                "id": meta.get("id", md.stem),
                "summary": meta.get("summary", ""),
                "provides": meta.get("provides") or [],
                "requires": meta.get("requires") or [],
                "idempotent": bool(meta.get("idempotent", False)),
            }
        )
    return rows


def render_table(rows: list[dict[str, object]]) -> str:
    """translated translated string create."""
    lines = [
        "| id | provides | requires | idempotent | translated |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        provides_val = r["provides"]
        requires_val = r["requires"]
        assert isinstance(provides_val, list)
        assert isinstance(requires_val, list)
        provides = ", ".join(str(x) for x in provides_val) or "—"
        requires = ", ".join(str(x) for x in requires_val) or "—"
        mark = "✓" if r["idempotent"] else "✗"
        lines.append(f"| `{r['id']}` | {provides} | {requires} | {mark} | {r['summary']} |")
    return "\n".join(lines)


def render_list(rows: list[dict[str, object]]) -> str:
    """AGENTS.md translated translated id translated create."""
    return "\n".join(f"- `{r['id']}` — {r['summary']}" for r in rows)


def replace_between(text: str, start: str, end: str, body: str) -> str:
    """`start` translated `end` translated translated `body` translated translated."""
    pattern = re.compile(
        re.escape(start) + r".*?" + re.escape(end),
        flags=re.DOTALL,
    )
    if not pattern.search(text):
        raise ValueError(f"markers not found: {start} ... {end}")
    replacement = f"{start}\n{body}\n{end}"
    return pattern.sub(replacement, text, count=1)


def update_file(path: Path, marker_start: str, marker_end: str, body: str) -> bool:
    """filetranslated translated translated body translated translated. translated translated True."""
    current = path.read_text(encoding="utf-8")
    new = replace_between(current, marker_start, marker_end, body)
    if new == current:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def main() -> int:
    if not SETUP_DIR.exists():
        print(f"setup directory not found: {SETUP_DIR}", file=sys.stderr)
        return 1

    rows = collect_setups()
    if not rows:
        print(f"no setup files found in {SETUP_DIR}", file=sys.stderr)
        return 1

    exit_code = 0
    table = render_table(rows)
    list_body = render_list(rows)

    if INDEX_PATH.exists():
        try:
            changed = update_file(INDEX_PATH, SETUP_MARKER_START, SETUP_MARKER_END, table)
            print(f"{'updated' if changed else 'unchanged'} {INDEX_PATH}")
        except ValueError as exc:
            print(f"ERROR: {exc} in {INDEX_PATH}", file=sys.stderr)
            exit_code = 1
    else:
        print(f"ERROR: missing {INDEX_PATH}", file=sys.stderr)
        exit_code = 1

    if AGENTS_PATH.exists():
        try:
            changed = update_file(AGENTS_PATH, LIST_MARKER_START, LIST_MARKER_END, list_body)
            print(f"{'updated' if changed else 'unchanged'} {AGENTS_PATH}")
        except ValueError as exc:
            print(f"ERROR: {exc} in {AGENTS_PATH}", file=sys.stderr)
            exit_code = 1
    else:
        print(f"skipped (no {AGENTS_PATH}) — Phase 3 will create it")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
