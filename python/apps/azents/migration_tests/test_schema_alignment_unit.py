"""Schema alignment revision checks that never connect to a database."""

import io
import json
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects.postgresql import ENUM

from azents.consts import PROJECT_ROOT
from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KIND,
    ModelMetadataSourceKind,
)
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.llm_catalog import (
    RDBImageGenerationCatalogEntry,
    RDBLLMCatalog,
    RDBLLMCatalogEntry,
)
from azents.rdb.models.model_metadata_source import RDBModelMetadataSource
from azents.rdb.models.toolkit import RDBAgentToolkitNamespaceReservation

_REVISION = "1c42cc5ce89f"
_PARENT = "c8bc0a5dcab0"


def _revision_module() -> ModuleType:
    """Load only the generated revision module through Alembic's script loader."""
    directory = ScriptDirectory.from_config(
        Config(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
    )
    revision = directory.get_revision(_REVISION)
    assert revision is not None
    return revision.module


def _offline_sql(*, upgrade: bool) -> str:
    """Render one revision with an offline dialect and an in-memory output buffer."""
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        module = _revision_module()
        if upgrade:
            module.upgrade()
        else:
            module.downgrade()
    return output.getvalue()


def test_generated_alignment_revision_remains_in_the_single_linear_chain() -> None:
    """The historical successor stays fixed while the marker follows the head."""
    directory = ScriptDirectory.from_config(
        Config(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
    )
    revision = directory.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == _PARENT
    head = directory.get_current_head()
    assert head is not None
    assert _REVISION in {
        item.revision for item in directory.iterate_revisions(head, "base")
    }
    assert (PROJECT_ROOT / "db-schemas/rdb/revision").read_text().strip() == head


def test_upgrade_validates_inventory_and_guards_before_any_schema_change() -> None:
    """Guard/ownership inventory is emitted before ENUM creation and index renames."""
    sql = _offline_sql(upgrade=True)
    assert sql.index("DO $$") < sql.index("CREATE TYPE model_metadata_source_kind")
    assert sql.index("CREATE TYPE model_metadata_source_kind") < sql.index(
        "ALTER TABLE"
    )
    assert sql.index("ALTER TABLE") < sql.index("ALTER INDEX")
    assert "session_replication_role" in sql
    assert "installed.tgenabled <> 'O'" in sql
    assert "installed.tgtype <> expected.trigger_type" in sql
    assert "guard_function.proname IS DISTINCT FROM expected.function_name" in sql
    assert "source_kind NOT IN ('genai_prices', 'litellm_json')" in sql
    assert "snapshot.source_key IS DISTINCT FROM authority.source_key" in sql
    assert "snapshot.catalog_id IS DISTINCT FROM catalog.id" in sql
    assert "azents_check_catalog_candidate" not in sql
    assert "AS ENUM ('genai_prices', 'litellm_json')" in sql
    assert "USING source_kind::model_metadata_source_kind" in sql
    assert sql.count("ALTER INDEX") == 7
    assert "DELETE FROM" not in sql
    assert "INSERT INTO" not in sql
    assert "DROP TRIGGER" not in sql
    assert "session_replication_role = replica" not in sql
    assert "ix_image_generation_catalog_entries_catalog_rank" not in sql


class _RejectedInventoryOperations:
    """Fail at the preflight boundary before any bind/DDL can be requested."""

    def __init__(self) -> None:
        self.statements: list[sa.TextClause] = []

    def execute(self, statement: sa.TextClause) -> None:
        self.statements.append(statement)
        raise RuntimeError("Source-kind inventory rejected")

    def get_bind(self) -> None:
        raise AssertionError("Rejected preflight must not obtain a DDL bind")

    def alter_column(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("Rejected preflight must not alter a column")


def test_failed_inventory_does_not_attempt_any_schema_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The upgrade stops at a rejected preflight rather than coercing old rows."""
    module = _revision_module()
    operations = _RejectedInventoryOperations()
    monkeypatch.setattr(module, "op", operations)
    with pytest.raises(RuntimeError, match="inventory rejected"):
        module.upgrade()
    assert len(operations.statements) == 1
    assert str(operations.statements[0]).lstrip().startswith("DO $$")


def test_downgrade_is_lossless_and_retains_cutover_guards() -> None:
    """Reverse current schema names/types without removing historical evidence."""
    sql = _offline_sql(upgrade=False)
    assert sql.count("ALTER INDEX") == 7
    assert "USING source_kind::text" in sql
    assert sql.index("TYPE VARCHAR(40)") < sql.index(
        "DROP TYPE model_metadata_source_kind"
    )
    assert "DROP TABLE" not in sql
    assert "DELETE FROM" not in sql
    assert "DROP TRIGGER" not in sql
    assert "ix_image_generation_catalog_entries_catalog_rank" not in sql


def test_current_models_keep_enum_labels_and_bounded_named_indexes() -> None:
    """Current mappings preserve enum compatibility and bounded index names."""
    kind = RDBModelMetadataSource.__table__.c.source_kind.type
    assert isinstance(kind, ENUM)
    assert kind.name == "model_metadata_source_kind"
    assert kind.enums == ["genai_prices", "litellm_json"]
    assert kind.create_type is False
    assert CATALOG_SOURCE_KIND is ModelMetadataSourceKind.LITELLM_JSON
    assert CATALOG_SOURCE_KIND == "litellm_json"
    assert json.dumps(CATALOG_SOURCE_KIND) == '"litellm_json"'
    assert ModelMetadataSourceKind.GENAI_PRICES == "genai_prices"
    indexes = (
        RDBHistoricalMemorySource.IX_ADMITTED_UNPREPARED,
        RDBLLMCatalog.UQ_SYSTEM_CATALOG,
        RDBLLMCatalog.UQ_INTEGRATION_CATALOG,
        RDBLLMCatalogEntry.IX_CATALOG_DISPLAY,
        RDBAgentToolkitNamespaceReservation.UQ_ACTIVE_AGENT_TOOLKIT,
    )
    assert [index.name for index in indexes] == [
        "ix_historical_memory_sources_admitted_at",
        "ix_llm_catalogs_provider_purpose",
        "ix_llm_catalogs_provider_integration_id_purpose",
        "ix_llm_catalog_entries_catalog_id_display_name",
        "ix_agent_toolkit_namespace_reservations_agent_id_toolkit_id",
    ]
    assert all(index.name is not None and len(index.name) <= 63 for index in indexes)
    assert RDBLLMCatalog.UQ_SYSTEM_CATALOG.unique is True
    assert RDBLLMCatalogEntry.UQ_CATALOG_MODEL.name == (
        "uq_llm_catalog_entries_catalog_model"
    )
    assert RDBAgentToolkitNamespaceReservation.UQ_ACTIVE_AGENT_TOOLKIT.unique is True
    assert RDBImageGenerationCatalogEntry.IX_CATALOG_RANK.name == (
        "ix_image_generation_catalog_entries_catalog_rank"
    )
