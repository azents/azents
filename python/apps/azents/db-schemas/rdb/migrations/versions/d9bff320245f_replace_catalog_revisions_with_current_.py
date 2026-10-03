"""Replace catalog revisions with current data and embedded pricing."""

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import INTEGRATION_SCOPED_CATALOG_PROVIDERS
from azents.core.model_catalog_identity import lookup_catalog_model
from azents.core.model_catalog_source import CatalogSourcePayload
from azents.core.model_pricing import (
    ModelPricingDefinition,
    ModelPricingUnavailableReason,
    normalize_model_pricing,
)

revision: str = "d9bff320245f"
down_revision: str | Sequence[str] | None = "1c42cc5ce89f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SYNC_COUNTS = ("fetched", "matched", "skipped", "hidden")
_OBSOLETE_METADATA = frozenset(
    {
        "snapshot_id",
        "source_snapshot_id",
        "source_hash",
        "raw_hash",
        "raw_document_hash",
        "canonical_hash",
        "projection_fingerprint",
        "registry_revision",
        "runtime_profile_resolver_revision",
        "resolver_revision",
        "projection_policy_revision",
        "capability_projection_revision",
        "pydantic_ai_version",
        "genai_prices_version",
    }
)


def _sync_columns() -> list[sa.Column[Any]]:
    status = postgresql.ENUM(
        "running",
        "succeeded",
        "failed",
        name="llm_catalog_attempt_status",
        create_type=False,
    )
    return [
        sa.Column("sync_work_token", sa.String(32), nullable=True),
        sa.Column("sync_status", status, nullable=True),
        sa.Column("sync_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_failure_code", sa.String(120), nullable=True),
        sa.Column("sync_failure_message", sa.Text(), nullable=True),
        sa.Column("sync_action_hint", sa.Text(), nullable=True),
        *[
            sa.Column(
                f"sync_{name}_count", sa.Integer(), nullable=False, server_default="0"
            )
            for name in _SYNC_COUNTS
        ],
        sa.Column("sync_diagnostics", postgresql.JSONB(), nullable=True),
    ]


def _table(bind: Connection, name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), autoload_with=bind)


def _hash_producer_version(value: object) -> bool:
    """Identify the old adapter's SHA-256 receipt rather than a release version."""
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdefABCDEF" for character in value[7:])
    )


def _clear_metadata(value: object) -> object:
    """Remove active revision receipts without changing model facts."""
    if isinstance(value, dict):
        return {
            key: _clear_metadata(item)
            for key, item in value.items()
            if key not in _OBSOLETE_METADATA
            and not (key == "producer_version" and _hash_producer_version(item))
        }
    if isinstance(value, list):
        return [_clear_metadata(item) for item in value]
    return value


def _drop_old_guards() -> None:
    for table, trigger in (
        ("model_metadata_sources", "guard_model_source_authority"),
        ("model_metadata_source_snapshots", "guard_model_source_snapshot"),
        ("llm_catalog_snapshots", "guard_catalog_snapshot"),
        ("llm_catalogs", "guard_catalog_authority"),
        ("llm_catalog_sync_attempts", "guard_retired_source_attempt"),
    ):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
    for signature in (
        "azents_guard_model_source_authority()",
        "azents_guard_model_source_snapshot()",
        "azents_guard_catalog_snapshot()",
        "azents_guard_catalog_authority()",
        "azents_guard_retired_source_attempt()",
        "azents_check_catalog_candidate(varchar, varchar)",
        "azents_check_catalog_source(varchar)",
    ):
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {signature}"))


def _copy_status(bind: Connection, owner: str) -> None:
    assignments = [
        "sync_status = a.status",
        "sync_started_at = a.started_at",
        "sync_finished_at = a.finished_at",
        "sync_failure_code = a.failure_code",
        "sync_failure_message = a.failure_message",
        "sync_action_hint = a.action_hint",
        "sync_diagnostics = a.diagnostics",
        *[f"sync_{name}_count = a.{name}_count" for name in _SYNC_COUNTS],
    ]
    bind.execute(
        sa.text(
            f"UPDATE {owner} AS o SET {', '.join(assignments)} "
            "FROM llm_catalog_sync_attempts AS a WHERE a.id = o.latest_attempt_id"
        )
    )


def _clear_current_receipts(bind: Connection) -> None:
    """Retain current failure facts without obsolete data revision receipts."""
    for name, identity, columns in (
        ("model_metadata_sources", "source_key", ("sync_diagnostics",)),
        ("llm_catalogs", "id", ("sync_diagnostics", "diagnostics")),
    ):
        table = _table(bind, name)
        for row in bind.execute(table.select()).mappings():
            values = {
                column: _clear_metadata(row[column])
                for column in columns
                if row[column] is not None
            }
            if values:
                bind.execute(
                    table.update()
                    .where(table.c[identity] == row[identity])
                    .values(**values)
                )


def _price_definitions(bind: Connection) -> dict[tuple[str, str], dict[str, object]]:
    """Normalize only the explicitly current allowed source, never retired history."""
    current = (
        bind.execute(
            sa.text(
                "SELECT s.* FROM model_metadata_source_snapshots s "
                "JOIN model_metadata_sources o ON o.current_snapshot_id = s.id "
                "WHERE o.source_key = 'litellm_catalog' "
                "AND s.source_key = 'litellm_catalog' "
                "AND s.source_kind = 'litellm_json' "
                "AND s.source_schema_version = '1'"
            )
        )
        .mappings()
        .one_or_none()
    )
    payload = None
    collected_at = None
    source_key = None
    if current is not None:
        payload = CatalogSourcePayload.model_validate_json(
            json.dumps(current["payload"])
        )
        collected_at = current["created_at"]
        source_key = "litellm_catalog"
        source_models = _table(bind, "model_metadata_source_models")
        rows = [
            {
                "source_key": source_key,
                "provider": model.provider,
                "source_model_key": model.source_key,
                "model_data": model.model_dump(mode="json"),
                "pricing": normalize_model_pricing(
                    source_key=source_key, source_model=model, collected_at=collected_at
                ).model_dump(mode="json"),
                "collected_at": collected_at,
            }
            for model in payload.models
        ]
        if rows:
            bind.execute(source_models.insert(), rows)
        bind.execute(
            sa.text(
                "UPDATE model_metadata_sources SET source_kind = 'litellm_json', "
                "source_schema_version = '1', source_url = :url, "
                "producer_name = :producer, "
                "producer_version = :version, provider_count = :providers, "
                "model_count = :models, last_success_at = :collected "
                "WHERE source_key = 'litellm_catalog'"
            ),
            {
                "url": current["source_url"],
                "producer": current["producer_name"],
                "version": (
                    None
                    if _hash_producer_version(current["producer_version"])
                    else current["producer_version"]
                ),
                "providers": payload.provider_count,
                "models": payload.model_count,
                "collected": collected_at,
            },
        )
    entries = _table(bind, "llm_catalog_entries")
    prices: dict[tuple[str, str], dict[str, object]] = {}
    for row in bind.execute(entries.select()).mappings():
        provider = LLMProvider(row["provider"])
        model = (
            lookup_catalog_model(
                payload,
                provider=provider,
                model_identifier=row["provider_model_identifier"],
            )
            if payload is not None
            else None
        )
        pricing = normalize_model_pricing(
            source_key=source_key, source_model=model, collected_at=collected_at
        ).model_dump(mode="json")
        bind.execute(
            entries.update()
            .where(entries.c.id == row["id"])
            .values(
                pricing=pricing,
                source_metadata=_clear_metadata(row["source_metadata"]),
                projection_metadata=_clear_metadata(row["projection_metadata"]),
            )
        )
        prices[(row["catalog_id"], row["provider_model_identifier"])] = pricing
    images = _table(bind, "image_generation_catalog_entries")
    for row in bind.execute(images.select()).mappings():
        bind.execute(
            images.update()
            .where(images.c.id == row["id"])
            .values(
                source_metadata=_clear_metadata(row["source_metadata"]),
                projection_metadata=_clear_metadata(row["projection_metadata"]),
            )
        )
    return prices


def _initialize_selected_prices(
    bind: Connection, prices: Mapping[tuple[str, str], dict[str, object]]
) -> None:
    """Fill only missing future-selected prices, preserving all existing data."""
    catalogs = list(
        bind.execute(
            sa.text(
                "SELECT id, scope::text, provider::text, provider_integration_id "
                "FROM llm_catalogs "
                "WHERE purpose = 'conversation'"
            )
        ).mappings()
    )
    integrations = {
        row["id"]: row
        for row in bind.execute(
            sa.text(
                "SELECT id, provider::text, workspace_id FROM llm_provider_integrations"
            )
        ).mappings()
    }
    session_workspaces = {
        row["id"]: row["workspace_id"]
        for row in bind.execute(
            sa.text("SELECT id, workspace_id FROM agent_sessions")
        ).mappings()
    }
    unavailable = ModelPricingDefinition(
        rules=None,
        unavailable_reason=ModelPricingUnavailableReason.MODEL_UNMATCHED,
        source_key=None,
        source_model_key=None,
        collected_at=None,
    ).model_dump(mode="json")

    def selected(value: dict[str, object], workspace_id: str) -> dict[str, object]:
        if "pricing" in value:
            if value["pricing"] is not None:
                ModelPricingDefinition.model_validate(value["pricing"])
            return value
        provider = LLMProvider(value["provider"])
        model = value["model_identifier"]
        integration_id = value["llm_provider_integration_id"]
        if not isinstance(model, str) or not isinstance(integration_id, str):
            raise ValueError("Stored selected model has an invalid exact identity.")
        integration = integrations.get(integration_id)
        price = unavailable
        if (
            integration is not None
            and integration["provider"] == provider.value
            and integration["workspace_id"] == workspace_id
        ):
            for catalog in catalogs:
                scoped = (
                    catalog["scope"] == "integration"
                    and catalog["provider_integration_id"] == integration_id
                    if provider in INTEGRATION_SCOPED_CATALOG_PROVIDERS
                    else catalog["scope"] == "system"
                    and catalog["provider"] == provider.value
                )
                if scoped:
                    price = prices.get((catalog["id"], model), unavailable)
                    break
        return {**value, "pricing": copy.deepcopy(price)}

    def transform(value: object, workspace_id: str) -> object:
        if isinstance(value, list):
            return [transform(item, workspace_id) for item in value]
        if not isinstance(value, dict):
            return value
        if {"provider", "model_identifier", "llm_provider_integration_id"}.issubset(
            value
        ):
            return selected(value, workspace_id)
        if "operation_id" in value and isinstance(value.get("candidates"), list):
            outcomes = value.get("outcomes")
            if not isinstance(outcomes, list):
                raise ValueError("Stored model operation has invalid outcomes.")
            if value.get("terminal_reason") is not None or any(
                isinstance(item, dict) and item.get("status") == "succeeded"
                for item in outcomes
            ):
                return value
            pending = {
                item["candidate_ordinal"]
                for item in outcomes
                if isinstance(item, dict) and item.get("status") == "pending"
            }
            candidates = [
                transform(item, workspace_id)
                if isinstance(item, dict) and item.get("ordinal") in pending
                else item
                for item in value["candidates"]
            ]
            return {**value, "candidates": candidates}
        return {key: transform(item, workspace_id) for key, item in value.items()}

    for name, identity, columns, predicate in (
        (
            "agents",
            "id",
            (
                "model_selection",
                "lightweight_model_selection",
                "selectable_model_options",
            ),
            "TRUE",
        ),
        (
            "workspace_model_settings",
            "workspace_id",
            (
                "default_model_selection",
                "default_lightweight_model_selection",
                "default_selectable_model_options",
            ),
            "TRUE",
        ),
        (
            "agent_sessions",
            "id",
            ("current_model_selection", "title_model_operation_state"),
            "TRUE",
        ),
        (
            "agent_runs",
            "id",
            ("model_operation_state",),
            "status IN ('pending', 'running')",
        ),
        (
            "historical_memory_sources",
            "source_session_id",
            ("model_operation_state",),
            "prepared_at IS NULL",
        ),
    ):
        table = _table(bind, name)
        query = table.select().where(sa.text(predicate))
        for row in bind.execute(query).mappings():
            if name == "agent_runs":
                workspace_id = session_workspaces[row["session_id"]]
            elif name == "historical_memory_sources":
                workspace_id = session_workspaces[row["source_session_id"]]
            else:
                workspace_id = row["workspace_id"]
            updates = {
                column: transform(row[column], workspace_id)
                for column in columns
                if row[column] is not None
            }
            updates = {
                key: value for key, value in updates.items() if value != row[key]
            }
            if updates:
                bind.execute(
                    table.update()
                    .where(table.c[identity] == row[identity])
                    .values(**updates)
                )


def _current_guards() -> None:
    op.execute(
        sa.text("""
        CREATE FUNCTION azents_guard_current_model_source()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF NEW.source_key <> 'litellm_catalog'
             OR NEW.source_kind <> 'litellm_json'
             OR NEW.source_schema_version <> '1' THEN
            RAISE EXCEPTION 'Current model source uses an incompatible contract.'
              USING ERRCODE='23514';
          END IF;
          IF TG_OP = 'UPDATE' AND NEW.source_key IS DISTINCT FROM OLD.source_key THEN
            RAISE EXCEPTION 'Current source ownership is immutable.'
              USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_current_model_source
          BEFORE INSERT OR UPDATE ON model_metadata_sources
          FOR EACH ROW EXECUTE FUNCTION azents_guard_current_model_source();

        CREATE FUNCTION azents_guard_current_source_model()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF NEW.model_data->>'provider' IS DISTINCT FROM NEW.provider
             OR NEW.model_data->>'source_key' IS DISTINCT FROM NEW.source_model_key
             OR NEW.pricing->>'source_key' IS DISTINCT FROM NEW.source_key
             OR NEW.pricing->>'source_model_key' IS DISTINCT FROM NEW.source_model_key
          THEN
            RAISE EXCEPTION 'Current source model identity does not match its owner.'
              USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_current_source_model
          BEFORE INSERT OR UPDATE ON model_metadata_source_models
          FOR EACH ROW EXECUTE FUNCTION azents_guard_current_source_model();

        CREATE FUNCTION azents_guard_current_catalog_owner()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP = 'UPDATE' AND (
             NEW.id IS DISTINCT FROM OLD.id OR NEW.scope IS DISTINCT FROM OLD.scope
             OR NEW.provider IS DISTINCT FROM OLD.provider
             OR NEW.purpose IS DISTINCT FROM OLD.purpose
             OR NEW.provider_integration_id
                IS DISTINCT FROM OLD.provider_integration_id)
          THEN
            RAISE EXCEPTION 'Current catalog ownership is immutable.'
              USING ERRCODE='23514';
          END IF;
          IF (NEW.scope='system' AND NEW.provider_integration_id IS NOT NULL)
             OR (NEW.scope='integration' AND NOT EXISTS (
               SELECT 1 FROM llm_provider_integrations i
               WHERE i.id=NEW.provider_integration_id AND i.provider=NEW.provider)) THEN
            RAISE EXCEPTION 'Current catalog scope does not match its integration.'
              USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_current_catalog_owner
          BEFORE INSERT OR UPDATE ON llm_catalogs
          FOR EACH ROW EXECUTE FUNCTION azents_guard_current_catalog_owner();

        CREATE FUNCTION azents_guard_current_catalog_entry()
        RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE owner llm_catalogs%ROWTYPE; BEGIN
          SELECT * INTO owner FROM llm_catalogs WHERE id=NEW.catalog_id;
          IF NOT FOUND OR owner.purpose <> TG_ARGV[0]::llm_catalog_purpose
             OR owner.provider IS DISTINCT FROM NEW.provider
             OR owner.provider_integration_id
                IS DISTINCT FROM NEW.provider_integration_id
          THEN
            RAISE EXCEPTION 'Model entry does not match catalog owner or purpose.'
              USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_current_conversation_entry
          BEFORE INSERT OR UPDATE ON llm_catalog_entries
          FOR EACH ROW EXECUTE FUNCTION
            azents_guard_current_catalog_entry('conversation');
        CREATE TRIGGER guard_current_image_entry
          BEFORE INSERT OR UPDATE ON image_generation_catalog_entries
          FOR EACH ROW EXECUTE FUNCTION
            azents_guard_current_catalog_entry('image_generation');

        CREATE FUNCTION azents_invalidate_current_image_catalog()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF NEW.catalog_configuration_version
             IS DISTINCT FROM OLD.catalog_configuration_version THEN
            PERFORM id FROM llm_catalogs WHERE provider_integration_id=NEW.id
              AND purpose='image_generation' ORDER BY id FOR UPDATE;
            UPDATE llm_catalogs SET image_usable=false
              WHERE provider_integration_id=NEW.id
              AND purpose='image_generation';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER invalidate_current_image_catalog
          AFTER UPDATE ON llm_provider_integrations
          FOR EACH ROW EXECUTE FUNCTION azents_invalidate_current_image_catalog();
    """)
    )


def upgrade() -> None:
    """Convert current data only after old catalog work is quiescent."""
    bind = op.get_bind()
    running = bind.scalar(
        sa.text("SELECT count(*) FROM llm_catalog_sync_attempts WHERE status='running'")
    )
    if running:
        raise RuntimeError(
            "catalog synchronization is still running; quiesce old readers, "
            "writers and queued work before migration"
        )
    malformed = bind.scalar(
        sa.text("""
        SELECT EXISTS (
          SELECT 1 FROM llm_catalogs c
          WHERE (c.scope='system' AND c.provider_integration_id IS NOT NULL)
             OR (c.scope='integration' AND NOT EXISTS (
               SELECT 1 FROM llm_provider_integrations i
               WHERE i.id=c.provider_integration_id AND i.provider=c.provider))
          UNION ALL
          SELECT 1 FROM llm_catalog_entries e
          JOIN llm_catalogs c ON c.id=e.catalog_id
          WHERE e.snapshot_id=c.current_snapshot_id AND (
            c.purpose <> 'conversation' OR e.provider IS DISTINCT FROM c.provider
            OR e.provider_integration_id IS DISTINCT FROM c.provider_integration_id)
          UNION ALL
          SELECT 1 FROM image_generation_catalog_entries e
          JOIN llm_catalogs c ON c.id=e.catalog_id
          WHERE e.snapshot_id=c.current_snapshot_id AND (
            c.purpose <> 'image_generation' OR e.provider IS DISTINCT FROM c.provider
            OR e.provider_integration_id IS DISTINCT FROM c.provider_integration_id)
        )
        """)
    )
    if malformed:
        raise ValueError("Current catalog rows have inconsistent ownership or purpose.")
    _drop_old_guards()
    for table in ("model_metadata_sources", "llm_catalogs"):
        for column in _sync_columns():
            op.add_column(table, column)
        op.add_column(
            table,
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        )
    for column in (
        sa.Column(
            "source_kind",
            postgresql.ENUM(
                "genai_prices",
                "litellm_json",
                name="model_metadata_source_kind",
                create_type=False,
            ),
            nullable=False,
            server_default="litellm_json",
        ),
        sa.Column(
            "source_schema_version", sa.String(20), nullable=False, server_default="1"
        ),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("producer_name", sa.String(80), nullable=True),
        sa.Column("producer_version", sa.String(80), nullable=True),
        sa.Column("provider_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_count", sa.Integer(), nullable=False, server_default="0"),
    ):
        op.add_column("model_metadata_sources", column)
    for name in ("entry_count", "visible_count", "hidden_count"):
        op.add_column(
            "llm_catalogs",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )
    op.add_column(
        "llm_catalogs", sa.Column("image_usable", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "llm_catalogs", sa.Column("diagnostics", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "llm_catalog_entries", sa.Column("pricing", postgresql.JSONB(), nullable=True)
    )
    for name in ("llm_catalog_entries", "image_generation_catalog_entries"):
        op.add_column(
            name,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        bind.execute(
            sa.text(
                f"DELETE FROM {name} e WHERE NOT EXISTS (SELECT 1 FROM llm_catalogs c "
                "WHERE c.id=e.catalog_id AND c.current_snapshot_id=e.snapshot_id)"
            )
        )
        bind.execute(
            sa.text(
                f"UPDATE {name} e SET updated_at=s.created_at "
                "FROM llm_catalog_snapshots s "
                "WHERE s.id=e.snapshot_id"
            )
        )
    _copy_status(bind, "model_metadata_sources")
    _copy_status(bind, "llm_catalogs")
    bind.execute(
        sa.text(
            "UPDATE llm_catalogs c SET entry_count=s.entry_count, "
            "visible_count=s.visible_count, hidden_count=s.hidden_count, "
            "last_success_at=s.created_at, diagnostics=s.diagnostics "
            "FROM llm_catalog_snapshots s WHERE s.id=c.current_snapshot_id"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE llm_catalogs c SET image_usable = "
            "(c.current_snapshot_id IS NOT NULL AND EXISTS ("
            "SELECT 1 FROM llm_catalog_snapshots s JOIN llm_provider_integrations i "
            "ON i.id=c.provider_integration_id WHERE s.id=c.current_snapshot_id "
            "AND i.enabled AND s.catalog_configuration_version="
            "i.catalog_configuration_version)) "
            "WHERE c.purpose='image_generation'"
        )
    )
    op.create_table(
        "model_metadata_source_models",
        sa.Column(
            "source_key",
            sa.String(120),
            sa.ForeignKey("model_metadata_sources.source_key", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("source_model_key", sa.Text(), primary_key=True),
        sa.Column("model_data", postgresql.JSONB(), nullable=False),
        sa.Column("pricing", postgresql.JSONB(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    )
    _clear_current_receipts(bind)
    bind.execute(
        sa.text("""
        UPDATE llm_catalogs c SET diagnostics =
          COALESCE(c.diagnostics, '{}'::jsonb) ||
          jsonb_build_object('projection_version', jsonb_build_object(
            'schema_version', s.projection_schema_version,
            'resolver_revision', s.runtime_profile_resolver_revision))
        FROM llm_catalog_snapshots s
        WHERE s.id=c.current_snapshot_id AND c.purpose='conversation'
        """)
    )
    prices = _price_definitions(bind)
    _initialize_selected_prices(bind, prices)
    bind.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
    inspector = sa.inspect(bind)
    for name in (
        "model_metadata_sources",
        "llm_catalogs",
        "llm_catalog_entries",
        "image_generation_catalog_entries",
    ):
        for fk in inspector.get_foreign_keys(name):
            if set(fk["constrained_columns"]) & {
                "current_snapshot_id",
                "latest_attempt_id",
                "snapshot_id",
            }:
                constraint_name = fk["name"]
                if constraint_name is None:
                    raise ValueError("Legacy catalog foreign key has no name.")
                op.drop_constraint(constraint_name, name, type_="foreignkey")
    op.drop_index(
        "ix_llm_catalog_entries_catalog_id_provider_model_identifier",
        table_name="llm_catalog_entries",
    )
    for name in ("llm_catalog_entries", "image_generation_catalog_entries"):
        op.drop_column(name, "snapshot_id")
        op.create_unique_constraint(
            f"uq_{name}_catalog_model",
            name,
            ["catalog_id", "provider_model_identifier"],
        )
    op.alter_column("llm_catalog_entries", "pricing", nullable=False)
    for name in ("model_metadata_sources", "llm_catalogs"):
        op.drop_column(name, "current_snapshot_id")
        op.drop_column(name, "latest_attempt_id")
    op.drop_table("llm_catalog_sync_attempts")
    op.drop_table("llm_catalog_snapshots")
    op.drop_table("model_metadata_source_snapshots")
    bind.execute(
        sa.text(
            "DELETE FROM model_metadata_sources WHERE source_key <> 'litellm_catalog'"
        )
    )
    op.create_check_constraint(
        "ck_llm_catalogs_image_usability_purpose",
        "llm_catalogs",
        "(purpose='image_generation' AND image_usable IS NOT NULL) "
        "OR (purpose='conversation' AND image_usable IS NULL)",
    )
    op.alter_column("model_metadata_sources", "source_kind", server_default=None)
    op.alter_column(
        "model_metadata_sources", "source_schema_version", server_default=None
    )
    _current_guards()


def downgrade() -> None:
    """Removed catalog history requires a matching schema/data backup."""
    raise RuntimeError(
        "irreversible current-catalog migration; stop writers and restore "
        "a matching schema/data backup or apply a forward fix"
    )
