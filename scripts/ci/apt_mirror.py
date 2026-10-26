"""Select the official Ubuntu archive for the existing CI dependency install."""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

AZURE_UBUNTU = re.compile(
    r"(?<!\S)(?:https?://azure\.archive\.ubuntu\.com/ubuntu(?P<slash>/?)"
    r"|mirror\+file:/etc/apt/apt-mirrors\.txt)(?=\s|$)"
)
OFFICIAL_UBUNTU = re.compile(r"(?<!\S)https://archive\.ubuntu\.com/ubuntu/?(?=\s|$)")


@dataclass(frozen=True)
class MirrorUpdate:
    changed_files: tuple[str, ...]
    replaced_uris: int
    selected_uris: int


@dataclass(frozen=True)
class SourceRewrite:
    content: str
    replaced_uris: int
    selected_uris: int


def rewrite_source(content: str, *, deb822: bool) -> SourceRewrite:
    """Rewrite URI fields of enabled sources, preserving all other source bytes."""
    rewritten_blocks: list[str] = []
    replacements = 0
    selected = 0
    for block in re.split(r"(\n[ \t]*\n)", content):
        enabled_values = (
            [
                line.partition("#")[0].partition(":")[2].strip().casefold()
                for line in block.splitlines()
                if line.partition(":")[0].casefold() == "enabled"
            ]
            if deb822
            else []
        )
        if any(
            value not in {"yes", "true", "1", "on", "no", "false", "0", "off"}
            for value in enabled_values
        ):
            raise ValueError("Unsupported Enabled value in an APT source")
        if any(value in {"no", "false", "0", "off"} for value in enabled_values):
            rewritten_blocks.append(block)
            continue
        lines: list[str] = []
        uri_field = False
        for line in block.splitlines(keepends=True):
            active, separator, comment = line.partition("#")
            prefix = ""
            if deb822:
                if active and not active[0].isspace():
                    uri_field = active.partition(":")[0].lower() == "uris"
                    if uri_field:
                        field, colon, active = active.partition(":")
                        prefix = field + colon
                is_uri = uri_field
            else:
                tokens = active.split()
                is_uri = bool(tokens) and tokens[0] in {"deb", "deb-src"}
            if is_uri:
                active, count = AZURE_UBUNTU.subn(
                    r"https://archive.ubuntu.com/ubuntu\g<slash>", active
                )
                replacements += count
                selected += len(OFFICIAL_UBUNTU.findall(active))
            lines.append(prefix + active + separator + comment)
        rewritten_blocks.append("".join(lines))
    return SourceRewrite("".join(rewritten_blocks), replacements, selected)


def use_ubuntu_archive(
    source_root: Path, *, require_selected: bool = False
) -> MirrorUpdate:
    """Select direct or hosted-runner mirror-list sources without changing trust."""
    if not source_root.is_dir():
        raise ValueError("APT sources root must be a directory")
    candidates = [source_root / "sources.list"]
    candidates += sorted((source_root / "sources.list.d").glob("*.list"))
    candidates += sorted((source_root / "sources.list.d").glob("*.sources"))
    updates: list[tuple[Path, str, int]] = []
    selected = 0
    for path in candidates:
        if not path.is_file():
            continue
        rewritten = rewrite_source(
            path.read_text(encoding="utf-8"), deb822=path.suffix == ".sources"
        )
        if rewritten.replaced_uris or rewritten.selected_uris:
            if path.is_symlink() or not path.resolve().is_relative_to(
                source_root.resolve()
            ):
                raise ValueError("Refusing to rewrite a symlinked APT source")
        selected += rewritten.selected_uris
        if rewritten.replaced_uris:
            updates.append((path, rewritten.content, rewritten.replaced_uris))
    if require_selected and not selected:
        raise ValueError("No enabled official Ubuntu archive source was selected")
    for path, rewritten, _ in updates:
        path.write_text(rewritten, encoding="utf-8")
    return MirrorUpdate(
        tuple(str(path.relative_to(source_root)) for path, _, _ in updates),
        sum(count for _, _, count in updates),
        selected,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-root", required=True, type=Path)
    parser.add_argument("--require-selected", action="store_true")
    arguments = parser.parse_args()
    result = use_ubuntu_archive(
        arguments.sources_root, require_selected=arguments.require_selected
    )
    sys.stdout.write(json.dumps(asdict(result)) + "\n")


if __name__ == "__main__":
    main()
