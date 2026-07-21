"""Tests for development snapshot documentation validation."""

import tempfile
import unittest
from pathlib import Path

from scripts import gen_docs_index


class DevelopmentSnapshotValidationTest(unittest.TestCase):
    """Validate new snapshot relationships and legacy compatibility."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix=".tmp-docs-index-tests-",
            dir=gen_docs_index.ROOT,
        )
        self.docs_root = Path(self.temp_dir.name) / "docs"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_doc(
        self,
        rel_path: str,
        *,
        created: str = "2026-07-21",
        implemented: str = "",
        include_tags: bool = True,
    ) -> None:
        path = self.docs_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "---",
            f'title: "{path.stem}"',
            f"created: {created}",
        ]
        if implemented:
            fields.append(f"implemented: {implemented}")
        if include_tags:
            fields.append("tags: [documentation]")
        fields.extend(["---", "", f"# {path.stem}", ""])
        path.write_text("\n".join(fields), encoding="utf-8")

    def errors(self) -> list[str]:
        return gen_docs_index.validate_docs(self.docs_root)

    def test_allows_progressive_snapshot_states(self) -> None:
        basename = "docids-260721-shared-development-snapshot-identifiers.md"
        self.write_doc(f"requirements/{basename}")
        self.assertEqual(self.errors(), [])

        self.write_doc(f"adr/{basename}")
        self.assertEqual(self.errors(), [])

        self.write_doc(f"design/{basename}")
        self.assertEqual(self.errors(), [])

        self.write_doc(
            f"requirements/{basename}",
            implemented="2026-07-21",
        )
        self.write_doc(
            f"design/{basename}",
            implemented="2026-07-21",
        )
        self.assertEqual(self.errors(), [])

    def test_allows_multiple_independent_snapshots(self) -> None:
        for basename in (
            "slack-260721-channel-agent-conversation.md",
            "memory-260721-agent-memory-management.md",
        ):
            for top_dir in gen_docs_index.CORE_DOCUMENT_DIRS:
                self.write_doc(f"{top_dir}/{basename}")

        self.assertEqual(self.errors(), [])

    def test_allows_later_adr_and_design_created_dates(self) -> None:
        basename = "docids-260719-shared-identifiers.md"
        self.write_doc(f"requirements/{basename}", created="2026-07-19")
        self.write_doc(f"adr/{basename}", created="2026-07-20")
        self.write_doc(f"design/{basename}", created="2026-07-21")

        self.assertEqual(self.errors(), [])

    def test_allows_legacy_adr_and_design_names(self) -> None:
        self.write_doc("adr/0181-existing-decision.md")
        self.write_doc("design/existing-feature.md")

        self.assertEqual(self.errors(), [])

    def test_rejects_adr_without_requirements(self) -> None:
        self.write_doc("adr/docids-260721-shared-identifiers.md")

        self.assertTrue(
            any(
                "must create Requirements before ADR or Design" in error
                for error in self.errors()
            )
        )

    def test_rejects_design_before_adr(self) -> None:
        basename = "docids-260721-shared-identifiers.md"
        self.write_doc(f"requirements/{basename}")
        self.write_doc(f"design/{basename}")

        self.assertTrue(
            any("must create ADR before Design" in error for error in self.errors())
        )

    def test_rejects_mismatched_snapshot_basenames(self) -> None:
        self.write_doc("requirements/docids-260721-shared-identifiers.md")
        self.write_doc("adr/docids-260721-different-identifiers.md")

        self.assertTrue(
            any(
                "Development snapshot basename must match" in error
                for error in self.errors()
            )
        )

    def test_rejects_duplicate_short_id_in_one_document_type(self) -> None:
        self.write_doc("requirements/docids-260721-shared-identifiers.md")
        self.write_doc("requirements/docids-260721-other-identifiers.md")

        self.assertTrue(
            any(
                "Duplicate Requirements snapshot ID" in error for error in self.errors()
            )
        )

    def test_rejects_incomplete_implemented_snapshot(self) -> None:
        self.write_doc(
            "requirements/docids-260721-shared-identifiers.md",
            implemented="2026-07-21",
        )

        self.assertTrue(
            any("Implemented development snapshot" in error for error in self.errors())
        )

    def test_rejects_one_sided_implemented_date(self) -> None:
        basename = "docids-260719-shared-identifiers.md"
        self.write_doc(
            f"requirements/{basename}",
            created="2026-07-19",
            implemented="2026-07-21",
        )
        self.write_doc(f"adr/{basename}", created="2026-07-20")
        self.write_doc(f"design/{basename}", created="2026-07-21")

        self.assertTrue(
            any(
                "must use the same `implemented` date" in error
                for error in self.errors()
            )
        )

    def test_rejects_different_implemented_dates(self) -> None:
        basename = "docids-260719-shared-identifiers.md"
        self.write_doc(
            f"requirements/{basename}",
            created="2026-07-19",
            implemented="2026-07-20",
        )
        self.write_doc(f"adr/{basename}", created="2026-07-20")
        self.write_doc(
            f"design/{basename}",
            created="2026-07-21",
            implemented="2026-07-21",
        )

        self.assertTrue(
            any(
                "must use the same `implemented` date" in error
                for error in self.errors()
            )
        )

    def test_rejects_filename_created_date_mismatch(self) -> None:
        self.write_doc(
            "requirements/docids-260721-shared-identifiers.md",
            created="2026-07-20",
        )

        self.assertTrue(
            any(
                "Requirements filename date must match the `created` date" in error
                for error in self.errors()
            )
        )


if __name__ == "__main__":
    unittest.main()
