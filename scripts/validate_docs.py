"""Validate Azents document metadata and development-snapshot relationships."""

import argparse
import csv
import re
import sys
from io import StringIO
from pathlib import Path
from typing import TypeAlias

ROOT = Path(__file__).resolve().parents[1]

FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
FIELD_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):[^\S\r\n]*(.*)$")
EXCLUDED = {"INDEX.md", "CLAUDE.md"}
COMMON_REQUIRED_FIELDS = ("title",)
CORE_DOCUMENT_DIRS = ("requirements", "adr", "design")
DEVELOPMENT_SNAPSHOT_FILENAME_PATTERN = re.compile(
    r"^(?P<word>[a-z][a-z0-9]*)-(?P<date>\d{6})-"
    r"(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)\.md$"
)

FrontmatterValue: TypeAlias = str | tuple[str, ...]


def resolve_docs_root(value: str) -> Path:
    """Resolve CLI input to a documentation root."""
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def frontmatter_body(path: Path) -> str | None:
    """Return a document's frontmatter body."""
    content = path.read_text(encoding="utf-8")
    match = FRONTMATTER_PATTERN.match(content)
    if match is None:
        return None
    return match.group(1)


def _strip_yaml_scalar(value: str) -> str:
    """Strip the simple quoting used by repository frontmatter scalars."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_inline_list(value: str) -> tuple[str, ...]:
    """Parse the repository's simple YAML inline-list form."""
    inner = value[1:-1].strip()
    if not inner:
        return ()
    reader = csv.reader(StringIO(inner), skipinitialspace=True)
    return tuple(_strip_yaml_scalar(item) for item in next(reader) if item.strip())


def parse_frontmatter(path: Path) -> dict[str, FrontmatterValue]:
    """Parse scalar and list frontmatter fields without requiring a YAML runtime."""
    body = frontmatter_body(path)
    if body is None:
        return {}

    result: dict[str, FrontmatterValue] = {}
    active_list: str | None = None
    for line in body.splitlines():
        if active_list is not None and line.startswith(("  - ", "- ")):
            current = result.get(active_list, ())
            assert isinstance(current, tuple)
            result[active_list] = (*current, _strip_yaml_scalar(line.split("-", 1)[1]))
            continue

        match = FIELD_PATTERN.match(line)
        if match is None:
            if line and not line.startswith((" ", "\t")):
                active_list = None
            continue

        key = match.group(1)
        value = match.group(2).strip()
        if not value:
            result[key] = ()
            active_list = key
        elif value.startswith("[") and value.endswith("]"):
            result[key] = _parse_inline_list(value)
            active_list = None
        else:
            result[key] = _strip_yaml_scalar(value)
            active_list = None
    return result


def scalar(fields: dict[str, FrontmatterValue], name: str) -> str:
    """Read a scalar frontmatter field."""
    value = fields.get(name, "")
    return value if isinstance(value, str) else ""


def validate_snapshot_document(
    path: Path,
    rel_path: str,
    fields: dict[str, FrontmatterValue],
) -> list[str]:
    """Validate a current-format Requirements, ADR, or Design document."""
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
            role = scalar(fields, "document_role")
            document_type = scalar(fields, "document_type")
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

    document_role = scalar(fields, "document_role")
    document_type = scalar(fields, "document_type")
    if not document_role:
        errors.append("Missing `document_role` frontmatter field")
    if not document_type:
        errors.append("Missing `document_type` frontmatter field")
    if document_role and document_role not in {"primary", "supporting"}:
        errors.append("`document_role` must be `primary` or `supporting`")
    if document_type and not document_role:
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

    snapshot_id = scalar(fields, "snapshot_id")
    if not snapshot_id:
        errors.append("Missing `snapshot_id` frontmatter field")
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

    created = scalar(fields, "created")
    created_match = re.fullmatch(r"20(\d{2})-(\d{2})-(\d{2})", created)
    if created and created_match is None:
        errors.append("`created` must use `YYYY-MM-DD`")
    elif top_dir == "requirements" and created_match is not None:
        created_short = "".join(created_match.groups())
        if filename_match.group("date") != created_short:
            errors.append("Requirements filename date must match the `created` date")

    return errors


def validate_doc(path: Path, docs_root: Path) -> list[str]:
    """Validate frontmatter required by the documentation system."""
    errors: list[str] = []
    if frontmatter_body(path) is None:
        return ["Missing frontmatter block delimited by ---"]

    fields = parse_frontmatter(path)
    for field_name in COMMON_REQUIRED_FIELDS:
        if not scalar(fields, field_name):
            errors.append(f"Missing `{field_name}` frontmatter field")

    rel_path = path.relative_to(docs_root).as_posix()
    top_dir = Path(rel_path).parts[0] if len(Path(rel_path).parts) > 1 else ""
    if top_dir in CORE_DOCUMENT_DIRS:
        errors.extend(validate_snapshot_document(path, rel_path, fields))

    return errors


def _markdown_paths(docs_root: Path) -> list[Path]:
    """Return document files in deterministic order."""
    return sorted(
        path
        for path in docs_root.rglob("*.md")
        if not path.is_symlink() and path.is_file() and path.name not in EXCLUDED
    )


def validate_docs(docs_root: Path) -> list[str]:
    """Return frontmatter and development-snapshot relationship errors."""
    errors: list[str] = []
    snapshots: dict[str, dict[str, tuple[Path, dict[str, FrontmatterValue]]]] = {}
    for path in _markdown_paths(docs_root):
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
        if scalar(fields, "document_role") == "supporting":
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
            for entry in snapshot.values():
                path = entry[0]
                if path.name == anchor_path.name:
                    continue
                path_rel = path.relative_to(ROOT).as_posix()
                anchor_rel = anchor_path.relative_to(ROOT).as_posix()
                errors.append(
                    f"{path_rel}: Development snapshot basename must match {anchor_rel}"
                )

        requirements_implemented = (
            scalar(requirements[1], "implemented") if requirements is not None else ""
        )
        design_implemented = (
            scalar(design[1], "implemented") if design is not None else ""
        )
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


def main(argv: list[str] | None = None) -> int:
    """Run mechanical validation without catalog or semantic discovery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-root", default="docs/azents")
    args = parser.parse_args(argv)
    docs_root = resolve_docs_root(args.docs_root)
    if not docs_root.is_dir():
        print(f"Documentation root does not exist: {docs_root}", file=sys.stderr)
        return 2
    errors = validate_docs(docs_root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Validated document metadata and development snapshots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
