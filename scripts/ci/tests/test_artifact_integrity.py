"""Authenticate GitHub ZIP bytes and their exact extracted evidence on replay."""

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.ci.collect import collect
from scripts.ci.evidence import (
    archive_file_hashes,
    artifacts_for_run,
    file_hashes,
    verify_collection,
)
from scripts.ci.tests.test_observability import sample, stamp_provenance
from scripts.ci.workflow_report import decode_run


class ArtifactIntegrityTest(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        artifact = root / "artifacts/ci-observability-python-azents-1"
        artifact.mkdir(parents=True)
        (artifact / "junit.xml").write_text("<testsuite/>")
        stamp_provenance(root, 1)
        return artifact

    def test_authenticated_archive_and_extraction_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            self.assertEqual(
                verify_collection(root, decode_run(sample())),
                {"ci-observability-python-azents-1"},
            )

    def test_rewritten_extraction_and_local_manifest_cannot_hide_substitution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self.fixture(root)
            (artifact / "junit.xml").write_text("<testsuite><testcase/></testsuite>")
            manifest = json.loads((root / "collection.json").read_text())
            manifest["file_hashes"] = file_hashes(root / "artifacts")
            (root / "collection.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "authenticated archives"):
                verify_collection(root, decode_run(sample()))

    def test_missing_or_changed_saved_archive_fails_closed(self) -> None:
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.fixture(root)
                archive = root / "artifact-1.zip"
                if missing:
                    archive.unlink()
                    expected = FileNotFoundError
                else:
                    archive.write_bytes(b"different downloaded archive")
                    expected = ValueError
                with self.assertRaises(expected):
                    verify_collection(root, decode_run(sample()))

    def test_api_digest_is_required_and_strict(self) -> None:
        for digest in (None, "", "md5:" + "a" * 32, "sha256:" + "G" * 64, True):
            with self.subTest(digest=digest), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.fixture(root)
                inventory = json.loads((root / "artifact-inventory.json").read_text())
                inventory[0]["artifacts"][0]["digest"] = digest
                with self.assertRaisesRegex(ValueError, "digest"):
                    artifacts_for_run(inventory, decode_run(sample()))

    def test_authenticated_unsafe_or_duplicate_paths_are_rejected(self) -> None:
        for name in ("../escape", "/absolute", "folder/../../escape", "x\\escape"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.fixture(root)
                archive = root / "artifact-1.zip"
                with zipfile.ZipFile(archive, "w") as zipped:
                    zipped.writestr(name, "not extracted")
                inventory = json.loads((root / "artifact-inventory.json").read_text())
                inventory[0]["artifacts"][0]["digest"] = (
                    "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
                )
                [artifact] = artifacts_for_run(inventory, decode_run(sample()))
                with self.assertRaisesRegex(ValueError, "Unsafe or duplicate"):
                    archive_file_hashes(archive, artifact)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            archive = root / "artifact-1.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("folder/file", "first")
                zipped.writestr("folder/./file", "second")
            inventory = json.loads((root / "artifact-inventory.json").read_text())
            inventory[0]["artifacts"][0]["digest"] = (
                "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
            )
            [artifact] = artifacts_for_run(inventory, decode_run(sample()))
            with self.assertRaisesRegex(ValueError, "Unsafe or duplicate"):
                archive_file_hashes(archive, artifact)

    def test_collector_rejects_wrong_valid_zip_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root / "source")
            inventory = (root / "source/artifact-inventory.json").read_text()
            downloaded = io.BytesIO()
            with zipfile.ZipFile(downloaded, "w") as zipped:
                zipped.writestr("junit.xml", "<testsuite><testcase/></testsuite>")
            destination = root / "destination"
            # The subprocess boundary writes untrusted download bytes, not a workflow.
            with (
                patch(
                    "scripts.ci.collect.gh",
                    side_effect=[json.dumps(sample()), inventory],
                ),
                patch("scripts.ci.collect.subprocess.run") as download,
            ):

                def write_download(*_args: object, **kwargs: object) -> None:
                    stream = kwargs["stdout"]
                    assert isinstance(stream, io.BufferedWriter)
                    stream.write(downloaded.getvalue())

                download.side_effect = write_download
                with self.assertRaisesRegex(ValueError, "archive SHA256 mismatch"):
                    collect("azents/azents", 100, 1, destination)
            self.assertFalse((destination / "collection.json").exists())
            self.assertEqual(list((destination / "artifacts").iterdir()), [])

    def test_authenticated_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            archive = root / "artifact-1.zip"
            link = zipfile.ZipInfo("link")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(link, "../outside")
            inventory = json.loads((root / "artifact-inventory.json").read_text())
            inventory[0]["artifacts"][0]["digest"] = (
                "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
            )
            [artifact] = artifacts_for_run(inventory, decode_run(sample()))
            with self.assertRaisesRegex(ValueError, "Unsafe or duplicate"):
                archive_file_hashes(archive, artifact)

    def test_collector_preserves_exact_archive_and_replayable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root / "source")
            archive_bytes = (root / "source/artifact-1.zip").read_bytes()
            inventory = (root / "source/artifact-inventory.json").read_text()
            destination = root / "destination"
            with (
                patch(
                    "scripts.ci.collect.gh",
                    side_effect=[json.dumps(sample()), inventory],
                ),
                patch("scripts.ci.collect.subprocess.run") as download,
            ):

                def write_download(*_args: object, **kwargs: object) -> None:
                    stream = kwargs["stdout"]
                    assert isinstance(stream, io.BufferedWriter)
                    stream.write(archive_bytes)

                download.side_effect = write_download
                collect("azents/azents", 100, 1, destination)
            self.assertEqual(
                (destination / "artifact-1.zip").read_bytes(), archive_bytes
            )
            self.assertEqual(
                verify_collection(destination, decode_run(sample())),
                {"ci-observability-python-azents-1"},
            )
