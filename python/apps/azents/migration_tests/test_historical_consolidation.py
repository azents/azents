"""Additive Historical storage migration with paged, canonical evidence backfill."""

import datetime
import hashlib
import json

import sqlalchemy as sa
from pytest_alembic import MigrationContext
from sqlalchemy.engine import Engine

from azents.core.historical_memory import HistoricalMemoryCompletion

_OLD = "d9bff320245f"
_NEW = "3be144f78dca"
_NOW = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


def _legacy_migration_evidence_hash(completion: HistoricalMemoryCompletion) -> str:
    """Freeze revision 3be144f78dca's hash for its immutable migration fixture."""
    payload = {
        "schema_version": 1,
        "summary": completion.summary or None,
        "source_title": completion.source_title_snapshot,
        "source_activity_at": completion.source_activity_at.astimezone(
            datetime.UTC
        ).isoformat(),
        "source_tail_event_id": completion.source_tail_event_id,
        "prepared_at": completion.prepared_at.astimezone(datetime.UTC).isoformat(),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_paged_evidence_backfill_preserves_canonical_bodies_and_reverses(
    alembic_runner: MigrationContext, alembic_engine: Engine
) -> None:
    """More than one page, empty outcomes, archive exclusion and linear reversal."""
    alembic_runner.migrate_up_to(_OLD)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces(id, name, handle) "
                "VALUES (:id, 'Memory migration', 'memory-migration')"
            ),
            {"id": "w" * 32},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO agents(id, workspace_id, name, model_selection,
                    lightweight_model_selection, selectable_model_options,
                    main_model_label, lightweight_model_label, enabled, type,
                    memory_enabled)
                VALUES (:id, :workspace, 'Memory migration', '{}', '{}',
                    '[{"candidates": [{}]}]',
                    'default', 'lightweight', true, 'public', true)
                """
            ),
            {"id": "a" * 32, "workspace": "w" * 32},
        )
        for index in range(62):
            source_id = f"{index:032x}"
            connection.execute(
                sa.text(
                    """
                    INSERT INTO agent_sessions(id, workspace_id, agent_id, handle,
                        session_kind, product_mode, status, start_reason)
                    VALUES (:id, :workspace, :agent, :handle, 'root', 'team',
                        :status, 'initial')
                    """
                ),
                {
                    "id": source_id,
                    "workspace": "w" * 32,
                    "agent": "a" * 32,
                    "handle": f"migration-{index}",
                    "status": "archived" if index == 60 else "active",
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO historical_memory_sources(source_session_id,
                        admitted_at, completed_source_activity_at,
                        completed_source_tail_event_id, prepared_at,
                        source_title_snapshot, summary)
                    VALUES (:id, :now, :activity, :tail, :prepared, :title, :summary)
                    """
                ),
                {
                    "id": source_id,
                    "now": _NOW,
                    "activity": None if index == 61 else _NOW,
                    "tail": None if index == 61 else "e" * 32,
                    "prepared": None if index == 61 else _NOW,
                    "title": f"Source {index}",
                    "summary": None if index in {0, 61} else f"Canonical 한글 {index}",
                },
            )
    alembic_runner.migrate_up_to(_NEW)
    with alembic_engine.connect() as connection:
        rows = (
            connection.execute(
                sa.text(
                    "SELECT * FROM historical_memory_sources ORDER BY source_session_id"
                )
            )
            .mappings()
            .all()
        )
        work = (
            connection.execute(
                sa.text(
                    "SELECT * FROM historical_consolidation_work "
                    "ORDER BY source_session_id"
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 62 and len(work) == 60
        assert {row["source_session_id"] for row in work} == {
            f"{index:032x}" for index in range(60)
        }
        for index, row in enumerate(rows):
            assert row["availability_generation"] == 1
            if index == 61:
                assert row["summary_generation"] == 0 and row["evidence_hash"] is None
                continue
            assert row["summary_generation"] == 1
            expected = _legacy_migration_evidence_hash(
                HistoricalMemoryCompletion(
                    source_activity_at=_NOW,
                    source_tail_event_id="e" * 32,
                    prepared_at=_NOW,
                    source_title_snapshot=f"Source {index}",
                    summary=None if index == 0 else f"Canonical 한글 {index}",
                )
            )
            assert row["evidence_hash"] == expected
        before = [(row["source_session_id"], row["summary"]) for row in rows]
    alembic_runner.migrate_down_to(_OLD)
    with alembic_engine.connect() as connection:
        assert (
            list(
                connection.execute(
                    sa.text(
                        "SELECT source_session_id, summary "
                        "FROM historical_memory_sources "
                        "ORDER BY source_session_id"
                    )
                )
            )
            == before
        )
    alembic_runner.migrate_up_to(_NEW)
    with alembic_engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT count(*) FROM historical_consolidation_work")
            ).scalar_one()
            == 60
        )
