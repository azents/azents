"""Select the official Ubuntu archive for the existing CI dependency install."""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

AZURE_UBUNTU = re.compile(
    r"(?<!\S)https?://azure\.archive\.ubuntu\.com/ubuntu(?P<slash>/?)(?=\s|$)"
)


@dataclass(frozen=True)
class MirrorUpdate:
    changed_files: tuple[str, ...]
    replaced_uris: int


def use_ubuntu_archive(source_root: Path) -> MirrorUpdate:
    """Preserve every source setting except the exact Azure mirror URI."""
    if not source_root.is_dir():
        raise ValueError("APT sources root must be a directory")
    candidates = [source_root / "sources.list"]
    candidates += sorted((source_root / "sources.list.d").glob("*.list"))
    candidates += sorted((source_root / "sources.list.d").glob("*.sources"))
    updates: list[tuple[Path, str, int]] = []
    for path in candidates:
        if not path.is_file():
            continue
        lines: list[str] = []
        replacements = 0
        for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
            if line.lstrip().startswith("#"):
                lines.append(line)
                continue
            active, separator, comment = line.partition("#")
            rewritten, count = AZURE_UBUNTU.subn(
                r"https://archive.ubuntu.com/ubuntu\g<slash>", active
            )
            lines.append(rewritten + separator + comment)
            replacements += count
        if replacements:
            if path.is_symlink() or not path.resolve().is_relative_to(
                source_root.resolve()
            ):
                raise ValueError("Refusing to rewrite a symlinked APT source")
            updates.append((path, "".join(lines), replacements))
    for path, rewritten, _ in updates:
        path.write_text(rewritten, encoding="utf-8")
    return MirrorUpdate(
        tuple(str(path.relative_to(source_root)) for path, _, _ in updates),
        sum(count for _, _, count in updates),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-root", required=True, type=Path)
    arguments = parser.parse_args()
    sys.stdout.write(
        json.dumps(asdict(use_ubuntu_archive(arguments.sources_root))) + "\n"
    )


if __name__ == "__main__":
    main()
