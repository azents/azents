#!/usr/bin/env python3
"""Generate documentation INDEX.md files from frontmatter."""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
FIELD_PATTERN = re.compile(r"^(\w+):[^\S\r\n]*(.*)$", re.MULTILINE)
EXCLUDED = {"INDEX.md"}
COMMON_REQUIRED_FIELDS = ("title",)
SPEC_REQUIRED_FIELDS = ("spec_type", "code_paths", "last_verified_at", "spec_version")
CORE_DOCUMENT_DIRS = ("requirements", "adr", "design")
DEVELOPMENT_SNAPSHOT_FILENAME_PATTERN = re.compile(
    r"^(?P<word>[a-z][a-z0-9]*)-(?P<date>\d{6})-"
    r"(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.md$"
)


@dataclass(frozen=True)
class DocInfo:
    """Document metadata needed for index generation."""

    rel_path: str
    title: str = ""
    spec_type: str = ""
    domain: str = ""
    owner: str = ""
    created: str = ""
    implemented: str = ""
    last_verified_at: str = ""
    spec_version: str = ""

    @property
    def top_dir(self) -> str:
        """Top-level directory name relative to docs root."""
        parts = Path(self.rel_path).parts
        return parts[0] if len(parts) > 1 else ""

    @property
    def short_id(self) -> str:
        """Return the canonical short ID for a development snapshot document."""
        if self.top_dir not in CORE_DOCUMENT_DIRS:
            return ""
        match = DEVELOPMENT_SNAPSHOT_FILENAME_PATTERN.fullmatch(
            Path(self.rel_path).name
        )
        if match is None:
            return ""
        return f"{match.group('word')}-{match.group('date')}"


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


def validate_snapshot_document(
    path: Path,
    rel_path: str,
    fields: dict[str, str],
) -> list[str]:
    """Validate a new-format Requirements, ADR, or Design document."""
    errors: list[str] = []
    top_dir = Path(rel_path).parts[0]
    filename_match = DEVELOPMENT_SNAPSHOT_FILENAME_PATTERN.fullmatch(path.name)

    if top_dir == "requirements" and filename_match is None:
        errors.append("Requirements filename must match `{word}-{YYMMDD}-{slug}.md`")
        return errors
    if top_dir == "adr" and filename_match is None:
        errors.append("ADR filename must match `{word}-{YYMMDD}-{slug}.md`")
        return errors
    if filename_match is None:
        if top_dir == "design":
            role = fields.get("document_role", "")
            document_type = fields.get("document_type", "")
            if role != "supporting" or not document_type.startswith("supporting-"):
                errors.append(
                    "Noncanonical Design filenames require explicit "
                    "`document_role: supporting` and `document_type: supporting-*`"
                )
        return errors

    if len(Path(rel_path).parts) != 2:
        errors.append(
            f"New snapshot {top_dir} documents must be directly under `{top_dir}/`"
        )

    document_role = fields.get("document_role", "")
    document_type = fields.get("document_type", "")
    if document_role and document_role not in {"primary", "supporting"}:
        errors.append("`document_role` must be `primary` or `supporting`")
    if document_type and document_role == "":
        errors.append("`document_type` requires a matching `document_role`")
    if document_role == "supporting":
        if top_dir != "design":
            errors.append(
                "Supporting snapshot documents are only allowed under `design/`"
            )
        if not document_type.startswith("supporting-"):
            errors.append(
                "Supporting Design documents must use a `supporting-*` document_type"
            )
    elif document_role == "primary" and document_type and document_type != top_dir:
        errors.append(
            f"Primary {top_dir} documents must use `document_type: {top_dir}`"
        )

    snapshot_id = fields.get("snapshot_id", "")
    expected_snapshot_id = (
        f"{filename_match.group('word')}-{filename_match.group('date')}"
    )
    if snapshot_id and snapshot_id != expected_snapshot_id:
        errors.append(
            f"`snapshot_id` must match the filename snapshot ID `{expected_snapshot_id}`"
        )

    for field_name in ("created", "tags"):
        if not fields.get(field_name):
            errors.append(f"Missing `{field_name}` frontmatter field")

    created = fields.get("created", "")
    created_match = re.fullmatch(r"20(\d{2})-(\d{2})-(\d{2})", created)
    if created and created_match is None:
        errors.append("`created` must use `YYYY-MM-DD`")
    elif top_dir == "requirements" and created_match is not None:
        created_short = "".join(created_match.groups())
        if filename_match.group("date") != created_short:
            errors.append("Requirements filename date must match the `created` date")

    return errors


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
    top_dir = Path(rel_path).parts[0] if len(Path(rel_path).parts) > 1 else ""
    if top_dir in CORE_DOCUMENT_DIRS:
        errors.extend(validate_snapshot_document(path, rel_path, fields))

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
    snapshots: dict[str, dict[str, tuple[Path, dict[str, str]]]] = {}
    for path in docs_root.rglob("*.md"):
        if path.is_symlink() or not path.is_file() or path.name in EXCLUDED:
            continue
        for error in validate_doc(path, docs_root):
            rel_path = path.relative_to(ROOT).as_posix()
            errors.append(f"{rel_path}: {error}")

        rel_path = path.relative_to(docs_root).as_posix()
        parts = Path(rel_path).parts
        top_dir = parts[0] if len(parts) > 1 else ""
        filename_match = DEVELOPMENT_SNAPSHOT_FILENAME_PATTERN.fullmatch(path.name)
        if top_dir not in CORE_DOCUMENT_DIRS or filename_match is None:
            continue

        fields = parse_frontmatter(path)
        if fields.get("document_role") == "supporting":
            continue

        short_id = f"{filename_match.group('word')}-{filename_match.group('date')}"
        snapshot = snapshots.setdefault(short_id, {})
        previous = snapshot.get(top_dir)
        if previous is not None:
            current_rel = path.relative_to(ROOT).as_posix()
            previous_rel = previous[0].relative_to(ROOT).as_posix()
            errors.append(
                f"{current_rel}: Duplicate {top_dir.title()} snapshot ID "
                f"`{short_id}` already used by {previous_rel}"
            )
            continue
        snapshot[top_dir] = (path, fields)

    for short_id, snapshot in sorted(snapshots.items()):
        requirements = snapshot.get("requirements")
        adr = snapshot.get("adr")
        design = snapshot.get("design")

        if requirements is None and (adr is not None or design is not None):
            source = adr or design
            assert source is not None
            source_rel = source[0].relative_to(ROOT).as_posix()
            errors.append(
                f"{source_rel}: Development snapshot `{short_id}` must create "
                "Requirements before ADR or Design"
            )

        if design is not None and adr is None:
            design_rel = design[0].relative_to(ROOT).as_posix()
            errors.append(
                f"{design_rel}: Development snapshot `{short_id}` must create "
                "ADR before Design"
            )

        anchor = requirements or adr
        if anchor is not None:
            anchor_path = anchor[0]
            for top_dir, entry in snapshot.items():
                path = entry[0]
                if path.name == anchor_path.name:
                    continue
                path_rel = path.relative_to(ROOT).as_posix()
                anchor_rel = anchor_path.relative_to(ROOT).as_posix()
                errors.append(
                    f"{path_rel}: Development snapshot basename must match {anchor_rel}"
                )

        requirements_implemented = ""
        if requirements is not None:
            requirements_implemented = requirements[1].get("implemented", "")
        design_implemented = ""
        if design is not None:
            design_implemented = design[1].get("implemented", "")
        if requirements_implemented or design_implemented:
            reference_entry = requirements if requirements_implemented else design
            assert reference_entry is not None
            reference_rel = reference_entry[0].relative_to(ROOT).as_posix()
            if set(snapshot) != set(CORE_DOCUMENT_DIRS):
                errors.append(
                    f"{reference_rel}: Implemented development snapshot `{short_id}` "
                    "must include matching Requirements, ADR, and Design documents"
                )
            elif requirements_implemented != design_implemented:
                errors.append(
                    f"{reference_rel}: Requirements and Design for development "
                    f"snapshot `{short_id}` must use the same `implemented` date"
                )
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
                created=fm.get("created", ""),
                implemented=fm.get("implemented", ""),
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

    requirements = [doc for doc in docs if doc.top_dir == "requirements"]
    section(
        "Requirements Snapshots",
        requirements,
        ["Short ID", "Created", "Implemented"],
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
