#!/usr/bin/env python3
"""Generate documentation INDEX.md files from frontmatter."""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
FIELD_PATTERN = re.compile(r"^(\w+):\s*(.*)$", re.MULTILINE)
EXCLUDED = {"INDEX.md"}
COMMON_REQUIRED_FIELDS = ("title",)
SPEC_REQUIRED_FIELDS = ("spec_type", "code_paths", "last_verified_at", "spec_version")


@dataclass(frozen=True)
class DocInfo:
    """Document metadata needed for index generation."""

    rel_path: str
    title: str = ""
    spec_type: str = ""
    domain: str = ""
    owner: str = ""
    last_verified_at: str = ""
    spec_version: str = ""

    @property
    def top_dir(self) -> str:
        """Top-level directory name relative to docs root."""
        parts = Path(self.rel_path).parts
        return parts[0] if len(parts) > 1 else ""


def resolve_docs_root(value: str) -> Path:
    """Resolve CLI input to docs root relative to repository root."""
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Parse frontmatter fields into a key-value dictionary."""
    content = path.read_text(encoding="utf-8")
    match = FRONTMATTER_PATTERN.match(content)
    if match is None:
        return {}

    body = match.group(1)
    result: dict[str, str] = {}
    for match in FIELD_PATTERN.finditer(body):
        key = match.group(1).strip()
        value = match.group(2).strip().strip('"').strip("'")
        result[key] = value
    return result


def frontmatter_body(path: Path) -> str | None:
    """Return a document's frontmatter body."""
    content = path.read_text(encoding="utf-8")
    match = FRONTMATTER_PATTERN.match(content)
    if match is None:
        return None
    return match.group(1)


def has_list_field(body: str, field_name: str) -> bool:
    """Check whether frontmatter contains a non-empty YAML list field."""
    lines = body.splitlines()
    in_field = False
    for line in lines:
        if line.startswith(f"{field_name}:"):
            in_field = True
            continue
        if in_field:
            if line.startswith("  - ") or line.startswith("- "):
                return bool(line.lstrip(" -").strip())
            if line and not line.startswith(" "):
                return False
    return False


def validate_doc(path: Path, docs_root: Path) -> list[str]:
    """Validate frontmatter fields required for index generation."""
    errors: list[str] = []
    body = frontmatter_body(path)
    if body is None:
        return ["Missing frontmatter block delimited by ---"]

    fields = parse_frontmatter(path)
    for field_name in COMMON_REQUIRED_FIELDS:
        if not fields.get(field_name):
            errors.append(f"Missing `{field_name}` frontmatter field")

    rel_path = path.relative_to(docs_root).as_posix()
    if rel_path.startswith("spec/"):
        for field_name in SPEC_REQUIRED_FIELDS:
            if field_name == "code_paths":
                if not has_list_field(body, field_name):
                    errors.append("Missing non-empty `code_paths` frontmatter list")
            elif not fields.get(field_name):
                errors.append(f"Missing `{field_name}` frontmatter field")

        spec_type = fields.get("spec_type")
        if spec_type not in {"domain", "flow"}:
            errors.append("`spec_type` must be `domain` or `flow`")
        if spec_type == "domain" and not fields.get("domain"):
            errors.append("Missing `domain` frontmatter field for domain spec")

    return errors


def validate_docs(docs_root: Path) -> list[str]:
    """Return markdown frontmatter errors under docs root."""
    errors: list[str] = []
    for path in docs_root.rglob("*.md"):
        if path.is_symlink() or not path.is_file() or path.name in EXCLUDED:
            continue
        for error in validate_doc(path, docs_root):
            rel_path = path.relative_to(ROOT).as_posix()
            errors.append(f"{rel_path}: {error}")
    return errors


def load_docs(docs_root: Path) -> list[DocInfo]:
    """Parse all markdown files under docs root into DocInfo list."""
    docs: list[DocInfo] = []
    for path in docs_root.rglob("*.md"):
        if path.is_symlink() or not path.is_file() or path.name in EXCLUDED:
            continue

        rel_path = path.relative_to(docs_root).as_posix()
        fm = parse_frontmatter(path)
        docs.append(
            DocInfo(
                rel_path=rel_path,
                title=fm.get("title", ""),
                spec_type=fm.get("spec_type", ""),
                domain=fm.get("domain", ""),
                owner=fm.get("owner", ""),
                last_verified_at=fm.get("last_verified_at", ""),
                spec_version=fm.get("spec_version", ""),
            )
        )
    return sorted(docs, key=lambda doc: doc.rel_path)


def title_only(doc: DocInfo) -> str:
    """Return display title for a document."""
    return doc.title or doc.rel_path


def render_main_index(docs: list[DocInfo], docs_root: Path, project_name: str) -> str:
    """Generate INDEX.md content for the documentation root."""
    base = docs_root / "INDEX.md"

    def link(doc: DocInfo) -> str:
        target = (docs_root / doc.rel_path).resolve()
        rel = target.relative_to(base.parent.resolve())
        return f"[{title_only(doc)}]({rel.as_posix()})"

    lines: list[str] = []
    lines.append("---")
    lines.append(f'title: "{project_name} Documentation Index"')
    lines.append("---")
    lines.append("")
    lines.append(f"# {project_name} Documentation Index")
    lines.append("")
    lines.append("> ⚙️ _Automatically generated by `scripts/gen_docs_index.py`._")
    lines.append(
        "> _Do not edit directly. Update each document's frontmatter instead._"
    )
    lines.append("")
    lines.append("Documentation structure: [AGENTS.md](./AGENTS.md)")
    lines.append("")
    lines.append(
        "Design documents are accumulated records and are not listed individually in this index. See the design section of AGENTS.md for structure and discovery rules."
    )
    lines.append("")

    def section(
        title: str, filtered: list[DocInfo], extra_cols: list[str] | None = None
    ) -> None:
        if not filtered:
            return
        lines.append(f"## {title}")
        lines.append("")
        if extra_cols:
            header = ["Title"] + extra_cols
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|" + "|".join(["---"] * len(header)) + "|")
            for doc in filtered:
                row = [link(doc)]
                for col in extra_cols:
                    row.append(getattr(doc, col.lower().replace(" ", "_"), "") or "-")
                lines.append("| " + " | ".join(row) + " |")
        else:
            for doc in filtered:
                lines.append(f"- {link(doc)}")
        lines.append("")

    domain_specs = [
        doc for doc in docs if doc.top_dir == "spec" and doc.spec_type == "domain"
    ]
    section(
        "Living Specs — Domain",
        domain_specs,
        ["Domain", "Owner", "Last Verified At", "Spec Version"],
    )

    flow_specs = [
        doc for doc in docs if doc.top_dir == "spec" and doc.spec_type == "flow"
    ]
    section(
        "Living Specs — Flow", flow_specs, ["Owner", "Last Verified At", "Spec Version"]
    )

    adrs = [doc for doc in docs if doc.top_dir == "adr"]
    section("Architecture Decision Records (ADR)", adrs)

    research = [doc for doc in docs if doc.top_dir == "research"]
    section("Research", research)

    runbook = [doc for doc in docs if doc.top_dir == "runbook"]
    section("Runbook (Operations · QA Guides)", runbook)

    reference = [doc for doc in docs if doc.top_dir == "reference"]
    section("Reference (API · CLI · Environment Variables)", reference)

    issues = [doc for doc in docs if doc.top_dir == "issues"]
    section("Issues (Bug Tracking)", issues)

    notes = [doc for doc in docs if doc.top_dir == "notes"]
    section("Notes (Blueprints · Discussion Summaries)", notes)

    roots = [doc for doc in docs if not doc.top_dir]
    section("Documentation Rules · Overview", roots)

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def render_spec_index(docs: list[DocInfo], docs_root: Path, project_name: str) -> str:
    """Generate spec/INDEX.md content."""
    base = docs_root / "spec" / "INDEX.md"
    spec_docs = [doc for doc in docs if doc.top_dir == "spec"]

    def link(doc: DocInfo) -> str:
        target = (docs_root / doc.rel_path).resolve()
        rel = target.relative_to(base.parent.resolve())
        return f"[{title_only(doc)}]({rel.as_posix()})"

    lines: list[str] = []
    lines.append("---")
    lines.append(f'title: "{project_name} Living Spec Index"')
    lines.append("---")
    lines.append("")
    lines.append(f"# {project_name} Living Spec Index")
    lines.append("")
    lines.append("> ⚙️ _Automatically generated by `scripts/gen_docs_index.py`._")
    lines.append("")
    lines.append("Details of all living specs. Synchronized from frontmatter.")
    lines.append("")

    domain = [doc for doc in spec_docs if doc.spec_type == "domain"]
    flow = [doc for doc in spec_docs if doc.spec_type == "flow"]

    if domain:
        lines.append("## Domain Specs")
        lines.append("")
        lines.append("| Domain | Title | Owner | Last Verified | Version |")
        lines.append("|---|---|---|---|---|")
        for doc in sorted(domain, key=lambda item: item.domain or item.rel_path):
            lines.append(
                f"| {doc.domain or '-'} | {link(doc)} | {doc.owner or '-'} | {doc.last_verified_at or '-'} | {doc.spec_version or '-'} |"
            )
        lines.append("")

    if flow:
        lines.append("## Flow Specs")
        lines.append("")
        lines.append("| Title | Owner | Last Verified | Version |")
        lines.append("|---|---|---|---|")
        for doc in sorted(flow, key=lambda item: item.rel_path):
            lines.append(
                f"| {link(doc)} | {doc.owner or '-'} | {doc.last_verified_at or '-'} | {doc.spec_version or '-'} |"
            )
        lines.append("")

    if not domain and not flow:
        lines.append("_No spec documents yet._")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def write_if_changed(path: Path, new_content: str, check_only: bool) -> bool:
    """Write when file content changes; in check mode only return whether change is needed."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing == new_content:
        return False
    if check_only:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")
    return True


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs-root",
        required=True,
        help="Repository-relative docs root to index, e.g. docs/azents",
    )
    parser.add_argument(
        "--project-name",
        required=True,
        help="Project display name for generated titles",
    )
    parser.add_argument(
        "--check", action="store_true", help="Check whether indexes are current"
    )
    args = parser.parse_args(argv[1:])

    docs_root = resolve_docs_root(args.docs_root)

    validation_errors = validate_docs(docs_root)
    if validation_errors:
        for error in validation_errors:
            print(error, file=sys.stderr)
        return 1

    docs = load_docs(docs_root)

    main_index = docs_root / "INDEX.md"
    spec_index = docs_root / "spec" / "INDEX.md"

    main_changed = write_if_changed(
        main_index,
        render_main_index(docs, docs_root, args.project_name),
        args.check,
    )
    spec_changed = write_if_changed(
        spec_index,
        render_spec_index(docs, docs_root, args.project_name),
        args.check,
    )

    if args.check and (main_changed or spec_changed):
        print(
            "Docs indexes are stale. Run `python scripts/gen_docs_index.py --docs-root <path> --project-name <name>`.",
            file=sys.stderr,
        )
        return 1

    if not args.check:
        print(
            f"INDEX update: main={'CHANGED' if main_changed else 'unchanged'}, "
            f"spec={'CHANGED' if spec_changed else 'unchanged'}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
