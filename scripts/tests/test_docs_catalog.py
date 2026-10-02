"""Tests for documentation frontmatter validation and catalog queries."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts import docs_catalog


class DocsCatalogTest(unittest.TestCase):
    """Validate snapshot relationships and frontmatter-backed discovery."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix=".tmp-docs-catalog-tests-",
            dir=docs_catalog.ROOT,
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
        document_role: str = "",
        document_type: str = "",
        include_snapshot_metadata: bool = True,
        include_tags: bool = True,
        tags: tuple[str, ...] = ("documentation",),
        spec_type: str = "",
        domain: str = "",
        code_paths: tuple[str, ...] = (),
        last_verified_at: str = "",
        spec_version: str = "",
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
        if document_role:
            fields.append(f"document_role: {document_role}")
        if document_type:
            fields.append(f"document_type: {document_type}")
        if include_snapshot_metadata:
            match = docs_catalog.DEVELOPMENT_SNAPSHOT_FILENAME_PATTERN.fullmatch(
                path.name
            )
            if match is not None and not document_role:
                fields.append("document_role: primary")
            if match is not None and not document_type:
                fields.append(f"document_type: {path.parent.name}")
            if match is not None:
                fields.append(
                    f"snapshot_id: {match.group('word')}-{match.group('date')}"
                )
        if include_tags:
            fields.append(f"tags: [{', '.join(tags)}]")
        if spec_type:
            fields.append(f"spec_type: {spec_type}")
        if domain:
            fields.append(f"domain: {domain}")
        if code_paths:
            fields.append("code_paths:")
            fields.extend(f"  - {code_path}" for code_path in code_paths)
        if last_verified_at:
            fields.append(f"last_verified_at: {last_verified_at}")
        if spec_version:
            fields.append(f"spec_version: {spec_version}")
        fields.extend(["---", "", f"# {path.stem}", ""])
        path.write_text("\n".join(fields), encoding="utf-8")

    def errors(self) -> list[str]:
        return docs_catalog.validate_docs(self.docs_root)

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
            for top_dir in docs_catalog.CORE_DOCUMENT_DIRS:
                self.write_doc(f"{top_dir}/{basename}")

        self.assertEqual(self.errors(), [])

    def test_allows_later_adr_and_design_created_dates(self) -> None:
        basename = "docids-260719-shared-identifiers.md"
        self.write_doc(f"requirements/{basename}", created="2026-07-19")
        self.write_doc(f"adr/{basename}", created="2026-07-20")
        self.write_doc(f"design/{basename}", created="2026-07-21")

        self.assertEqual(self.errors(), [])

    def test_rejects_legacy_adr_and_unclassified_design_names(self) -> None:
        self.write_doc("adr/0181-existing-decision.md")
        self.write_doc("design/existing-feature.md")

        errors = self.errors()
        self.assertTrue(any("ADR filename must match" in error for error in errors))
        self.assertTrue(
            any(
                "Noncanonical Design filenames require explicit" in error
                for error in errors
            )
        )

    def test_allows_explicit_supporting_design_name(self) -> None:
        self.write_doc(
            "design/existing-feature.md",
            document_role="supporting",
            document_type="supporting-plan",
        )

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

    def test_rejects_primary_snapshot_without_explicit_metadata(self) -> None:
        basename = "docids-260721-shared-identifiers.md"
        self.write_doc(
            f"requirements/{basename}",
            include_snapshot_metadata=False,
        )

        errors = self.errors()
        self.assertTrue(
            any(
                "Missing `document_role` frontmatter field" in error for error in errors
            )
        )
        self.assertTrue(
            any(
                "Missing `document_type` frontmatter field" in error for error in errors
            )
        )
        self.assertTrue(
            any("Missing `snapshot_id` frontmatter field" in error for error in errors)
        )

    def test_loads_tags_and_code_paths_for_queries(self) -> None:
        self.write_doc(
            "spec/domain/agent.md",
            tags=("backend", "agent"),
            spec_type="domain",
            domain="agent",
            code_paths=("python/apps/azents/src/azents/services/agent_service.py",),
            last_verified_at="2026-09-01",
            spec_version="1",
        )

        docs = docs_catalog.load_docs(self.docs_root)

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].tags, ("backend", "agent"))
        self.assertEqual(
            docs[0].code_paths,
            ("python/apps/azents/src/azents/services/agent_service.py",),
        )
        self.assertEqual(self.errors(), [])

    def test_rejects_invalid_spec_verification_date(self) -> None:
        self.write_doc(
            "spec/flow/example.md",
            spec_type="flow",
            code_paths=("python/apps/azents/src/azents/engine",),
            last_verified_at="not-a-date",
            spec_version="1",
        )

        self.assertTrue(
            any(
                "`last_verified_at` must use `YYYY-MM-DD`" in error
                for error in self.errors()
            )
        )

    def test_filters_by_type_tag_snapshot_and_related_code_path(self) -> None:
        basename = "agent-260721-agent-management.md"
        for top_dir in docs_catalog.CORE_DOCUMENT_DIRS:
            self.write_doc(
                f"{top_dir}/{basename}",
                tags=("agent", "architecture"),
            )
        self.write_doc(
            "spec/domain/agent.md",
            tags=("agent", "backend"),
            spec_type="domain",
            domain="agent",
            code_paths=("python/apps/azents/src/azents/services",),
            last_verified_at="2026-09-01",
            spec_version="1",
        )
        docs = docs_catalog.load_docs(self.docs_root)

        filtered = docs_catalog._filter_docs(
            docs,
            catalog_type="spec",
            spec_type="domain",
            tags=["agent"],
        )
        snapshot = [doc for doc in docs if doc.short_id == "agent-260721"]
        related = [
            doc
            for doc in docs
            if any(
                docs_catalog._path_related(
                    "python/apps/azents/src/azents/services/agent_service.py",
                    code_path,
                )
                for code_path in doc.code_paths
            )
        ]

        self.assertEqual([doc.rel_path for doc in filtered], ["spec/domain/agent.md"])
        self.assertEqual(len(snapshot), 3)
        self.assertEqual([doc.rel_path for doc in related], ["spec/domain/agent.md"])

    def test_json_output_contains_catalog_metadata(self) -> None:
        self.write_doc(
            "spec/flow/example.md",
            tags=("flow",),
            spec_type="flow",
            code_paths=("python/apps/azents/src/azents/engine",),
            last_verified_at="2026-09-01",
            spec_version="2",
        )
        docs = docs_catalog.load_docs(self.docs_root)

        payload = json.loads(docs_catalog.render_docs(docs, "json"))

        self.assertEqual(payload[0]["catalog_type"], "spec")
        self.assertEqual(payload[0]["tags"], ["flow"])
        self.assertEqual(
            payload[0]["code_paths"],
            ["python/apps/azents/src/azents/engine"],
        )


if __name__ == "__main__":
    unittest.main()
