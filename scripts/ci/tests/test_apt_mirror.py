"""Mirror selection preserves package authority and all dependency settings."""

import tempfile
import unittest
from pathlib import Path

from scripts.ci.apt_mirror import use_ubuntu_archive


class AptMirrorTests(unittest.TestCase):
    def test_hosted_list_reference_selects_archive_without_touching_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "sources.list.d"
            directory.mkdir()
            path = directory / "ubuntu.sources"
            original = (
                "Types: deb\nURIs: mirror+file:/etc/apt/apt-mirrors.txt\n"
                "Suites: noble noble-updates noble-backports noble-security\n"
                "Components: main restricted universe multiverse\n"
                "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n"
            )
            path.write_text(original)
            mirror_list = root / "apt-mirrors.txt"
            mirrors = (
                "http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\n"
                "https://archive.ubuntu.com/ubuntu/\tpriority:2\n"
                "https://security.ubuntu.com/ubuntu/\tpriority:3\n"
            )
            mirror_list.write_text(mirrors)
            result = use_ubuntu_archive(root, require_selected=True)
            self.assertEqual(result.replaced_uris, 1)
            self.assertEqual(result.selected_uris, 1)
            self.assertEqual(
                path.read_text(),
                original.replace(
                    "mirror+file:/etc/apt/apt-mirrors.txt",
                    "https://archive.ubuntu.com/ubuntu",
                ),
            )
            self.assertEqual(mirror_list.read_text(), mirrors)
            repeated = use_ubuntu_archive(root, require_selected=True)
            self.assertEqual(repeated.replaced_uris, 0)
            self.assertEqual(repeated.selected_uris, 1)

    def test_legacy_list_and_deb822_continuation_preserve_other_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "sources.list"
            legacy.write_text(
                "deb [signed-by=/keys/ubuntu.gpg] "
                "mirror+file:/etc/apt/apt-mirrors.txt noble main\n"
                "deb mirror+file:/etc/apt/other-mirrors.txt noble main\n"
                "deb mirror+file:/etc/apt/apt-mirrors.txt.other noble main\n"
            )
            directory = root / "sources.list.d"
            directory.mkdir()
            source = directory / "ubuntu.sources"
            source.write_text(
                "Types: deb\nURIs:\n"
                " mirror+file:/etc/apt/apt-mirrors.txt\nSuites: noble\n"
                "Signed-By: /keys/ubuntu.gpg\n"
            )
            result = use_ubuntu_archive(root, require_selected=True)
            self.assertEqual(result.replaced_uris, 2)
            self.assertEqual(result.selected_uris, 2)
            self.assertIn(
                "deb [signed-by=/keys/ubuntu.gpg] "
                "https://archive.ubuntu.com/ubuntu noble main",
                legacy.read_text(),
            )
            self.assertIn("mirror+file:/etc/apt/other-mirrors.txt", legacy.read_text())
            self.assertIn(
                "mirror+file:/etc/apt/apt-mirrors.txt.other", legacy.read_text()
            )
            self.assertIn(
                "URIs:\n https://archive.ubuntu.com/ubuntu\n", source.read_text()
            )

    def test_required_selection_rejects_disabled_or_unknown_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "sources.list.d"
            directory.mkdir()
            path = directory / "ubuntu.sources"
            original = (
                "# URIs: https://archive.ubuntu.com/ubuntu\n"
                "Types: deb\nURIs: mirror+file:/etc/apt/apt-mirrors.txt\n"
                "Suites: noble\nEnabled: no # disabled source\n\n"
                "Types: deb\nURIs: mirror+file:/etc/apt/unknown.txt\n"
                "Suites: noble\n"
            )
            path.write_text(original)
            with self.assertRaisesRegex(ValueError, "No enabled official"):
                use_ubuntu_archive(root, require_selected=True)
            self.assertEqual(path.read_text(), original)

    def test_deb822_disabled_boolean_aliases_cannot_satisfy_selection(self) -> None:
        for enabled in ("no", "false", "0", "off", "FALSE"):
            with (
                self.subTest(enabled=enabled),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                directory = root / "sources.list.d"
                directory.mkdir()
                path = directory / "ubuntu.sources"
                original = (
                    "Types:deb\nURIs:mirror+file:/etc/apt/apt-mirrors.txt\n"
                    f"Suites:noble\nEnabled:{enabled} # disabled\n"
                )
                path.write_text(original)
                with self.assertRaisesRegex(ValueError, "No enabled official"):
                    use_ubuntu_archive(root, require_selected=True)
                self.assertEqual(path.read_text(), original)

    def test_deb822_uri_value_needs_no_whitespace_after_field_colon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "sources.list.d"
            directory.mkdir()
            path = directory / "ubuntu.sources"
            original = (
                "Types:deb\nURIs:mirror+file:/etc/apt/apt-mirrors.txt\n"
                "Suites:noble\nComponents:main\nEnabled:true\n"
                "Signed-By:/keys/ubuntu.gpg\n"
            )
            path.write_text(original)
            result = use_ubuntu_archive(root, require_selected=True)
            self.assertEqual(result.selected_uris, 1)
            self.assertEqual(result.replaced_uris, 1)
            self.assertEqual(
                path.read_text(),
                original.replace(
                    "mirror+file:/etc/apt/apt-mirrors.txt",
                    "https://archive.ubuntu.com/ubuntu",
                ),
            )
            self.assertEqual(
                use_ubuntu_archive(root, require_selected=True).selected_uris, 1
            )

    def test_deb822_changes_only_the_exact_uri_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources.list.d"
            sources.mkdir()
            path = sources / "ubuntu.sources"
            original = (
                "Types: deb\n"
                "URIs: http://azure.archive.ubuntu.com/ubuntu/\n"
                "Suites: noble noble-updates noble-backports\n"
                "Components: main restricted universe multiverse\n"
                "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n"
            )
            path.write_text(original)
            path.chmod(0o640)
            result = use_ubuntu_archive(root)
            self.assertEqual(result.changed_files, ("sources.list.d/ubuntu.sources",))
            self.assertEqual(result.replaced_uris, 1)
            self.assertEqual(
                path.read_text(),
                original.replace(
                    "http://azure.archive.ubuntu.com/ubuntu/",
                    "https://archive.ubuntu.com/ubuntu/",
                ),
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(use_ubuntu_archive(root).replaced_uris, 0)

    def test_legacy_sources_comments_and_other_repositories_remain_intact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "sources.list"
            original = (
                "# deb http://azure.archive.ubuntu.com/ubuntu noble main\n"
                "deb [arch=amd64] https://azure.archive.ubuntu.com/ubuntu noble main\n"
                "deb https://archive.ubuntu.com/ubuntu noble main "
                "# http://azure.archive.ubuntu.com/ubuntu\n"
                "deb http://security.ubuntu.com/ubuntu noble-security main\n"
                "deb https://deb.nodesource.com/node_24.x nodistro main\n"
                "deb http://azure.archive.ubuntu.com.evil/ubuntu noble main\n"
                "deb http://azure.archive.ubuntu.com/ubuntu-other noble main\n"
            )
            path.write_text(original)
            result = use_ubuntu_archive(root)
            self.assertEqual(result.replaced_uris, 1)
            self.assertEqual(
                path.read_text(),
                original.replace(
                    "[arch=amd64] https://azure.archive.ubuntu.com/ubuntu ",
                    "[arch=amd64] https://archive.ubuntu.com/ubuntu ",
                ),
            )

    def test_symlink_failure_precedes_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "sources.list"
            original = "deb http://azure.archive.ubuntu.com/ubuntu noble main\n"
            first.write_text(original)
            directory = root / "sources.list.d"
            directory.mkdir()
            target = root / "outside.sources"
            target.write_text("URIs: http://azure.archive.ubuntu.com/ubuntu\n")
            (directory / "ubuntu.sources").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlinked"):
                use_ubuntu_archive(root)
            self.assertEqual(first.read_text(), original)
            self.assertEqual(
                target.read_text(), "URIs: http://azure.archive.ubuntu.com/ubuntu\n"
            )

    def test_missing_root_fails_and_unrelated_files_are_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "directory"):
                use_ubuntu_archive(root / "missing")
            unrelated = root / "notes.txt"
            text = "http://azure.archive.ubuntu.com/ubuntu"
            unrelated.write_text(text)
            self.assertEqual(use_ubuntu_archive(root).changed_files, ())
            self.assertEqual(unrelated.read_text(), text)


if __name__ == "__main__":
    unittest.main()
