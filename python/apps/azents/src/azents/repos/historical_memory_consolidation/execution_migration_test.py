"""Real predecessor-to-current migration preservation and obsolete-state removal."""

import asyncio
import datetime
import json

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer
from uuid6 import uuid7

from azents.consts import PROJECT_ROOT
from azents.core.enums import EventKind
from azents.core.historical_memory_legacy_audit import (
    MemoryLegacyCostMethod,
    MemoryLegacyRecordedOutcome,
)
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_legacy_audit import (
    RDBMemoryLegacyJob,
    RDBMemoryLegacyModelUsage,
)
from azents.rdb.models.memory import RDBAgentMemory
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.session_execution.repository_test import _create_execution_subject
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate


async def test_migration_keeps_current_pending_sources_saved_and_common_audit(
    check_docker_availability: None,
) -> None:
    """Discard authoring history without losing current truth or outstanding changes."""
    del check_docker_availability
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        config = Config(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
        config.set_main_option("sqlalchemy.url", postgres.get_connection_url())
        await asyncio.to_thread(command.upgrade, config, "6a05f4a01f6f")
        engine = create_async_engine(postgres.get_connection_url())
        manager = create_read_write_session_manager(engine)
        unit_id, selected_id, discarded_id = (uuid7().hex for _ in range(3))
        pending_id, considered_id, published_id = (uuid7().hex for _ in range(3))
        unallocated_personal_work = uuid7().hex
        success_job, failed_job, unmatched_job = (uuid7().hex for _ in range(3))
        known_dispatch, unknown_dispatch, absent_dispatch = (
            uuid7().hex for _ in range(3)
        )
        now = datetime.datetime.now(datetime.UTC)
        try:
            async with manager() as session:
                subject = await _create_execution_subject(
                    session, handle=f"migration-{uuid7().hex}"
                )
                user = await UserRepository().create(
                    session, UserCreate(email=f"{uuid7().hex}@example.test")
                )
                source = RDBHistoricalMemorySource(
                    source_session_id=subject.agent_session.id, admitted_at=now
                )
                source.prepared_at = now
                source.completed_source_activity_at = now
                source.completed_source_tail_event_id = uuid7().hex
                source.summary = "Canonical prepared summary"
                saved = RDBAgentMemory(
                    agent_id=subject.agent_id,
                    scope="agent",
                    type="knowledge",
                    name="migration-saved",
                    description="Canonical saved data",
                    content="Saved memory survives",
                    user_id=None,
                )
                event = RDBEvent(
                    session_id=subject.agent_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload={"text": "Common audit survives"},
                )
                snapshot = RDBToolkitState(
                    agent_id=subject.agent_id,
                    session_id=subject.agent_session.id,
                    toolkit_namespace="memory",
                    state_name="context_snapshot",
                    state_json={"revision_id": selected_id},
                    schema_version=2,
                )
                unrelated = RDBToolkitState(
                    agent_id=subject.agent_id,
                    session_id=subject.agent_session.id,
                    toolkit_namespace="unrelated",
                    state_name="keep",
                    state_json={"value": "preserved"},
                    schema_version=1,
                )
                session.write_session.add_all(
                    [source, saved, event, snapshot, unrelated]
                )
                await session.write_session.flush()
                await session.write_session.execute(
                    sa.text("""
                    INSERT INTO historical_consolidation_units
                        (id, agent_id, workspace_id, scope, published_revision_id)
                    VALUES (:unit, :agent, :workspace, 'TEAM', :revision)
                """),
                    {
                        "unit": unit_id,
                        "agent": subject.agent_id,
                        "workspace": subject.agent_session.workspace_id,
                        "revision": selected_id,
                    },
                )
                for revision_id, body in (
                    (selected_id, "The selected current result"),
                    (discarded_id, "Obsolete prior result"),
                ):
                    await session.write_session.execute(
                        sa.text("""
                        INSERT INTO historical_consolidation_revisions
                            (id, unit_id, attempt_id, markdown, rendered_block)
                        VALUES (:id, :unit, :attempt, :body, :body)
                    """),
                        {
                            "id": revision_id,
                            "unit": unit_id,
                            "attempt": success_job
                            if revision_id == selected_id
                            else uuid7().hex,
                            "body": body,
                        },
                    )
                for work_id, state, generation in (
                    (pending_id, "PENDING", 1),
                    (considered_id, "CONSIDERED", 2),
                    (published_id, "PUBLISHED", 3),
                ):
                    await session.write_session.execute(
                        sa.text("""
                        INSERT INTO historical_consolidation_work
                            (id, agent_id, workspace_id, scope, source_session_id,
                             summary_generation, availability_generation, kind, state)
                        VALUES (:id, :agent, :workspace, 'TEAM', :source,
                                :generation, 1, 'PREPARED',
                                CAST(:state AS consolidation_work_state))
                    """),
                        {
                            "id": work_id,
                            "agent": subject.agent_id,
                            "workspace": subject.agent_session.workspace_id,
                            "source": source.source_session_id,
                            "generation": generation,
                            "state": state,
                        },
                    )
                await session.write_session.execute(
                    sa.text("""
                        INSERT INTO historical_consolidation_work
                            (id, agent_id, workspace_id, scope, associated_user_id,
                             source_session_id, summary_generation,
                             availability_generation, kind, state)
                        VALUES (:id, :agent, :workspace, 'USER', :user, :source,
                                0, 1, 'REMOVED', 'PENDING')
                    """),
                    {
                        "id": unallocated_personal_work,
                        "agent": subject.agent_id,
                        "workspace": subject.agent_session.workspace_id,
                        "user": user.id,
                        "source": uuid7().hex,
                    },
                )
                for (
                    job_id,
                    outcome,
                    revision,
                    failure,
                    requests,
                    tools,
                    inputs,
                    outputs,
                ) in (
                    (success_job, "COMPLETED", selected_id, None, 2, 3, 21, 8),
                    (failed_job, "FAILED", None, "provider_authentication", 1, 0, 0, 0),
                    (unmatched_job, "COMPLETED", selected_id, None, 0, 0, 0, 0),
                ):
                    await session.write_session.execute(
                        sa.text("""
                        INSERT INTO historical_consolidation_attempts
                            (id, unit_id, owner_generation, owner_token, deadline_at,
                             pass_upper_sequence, state, created_at, finished_at,
                             completed_revision_id, failure_code, model_requests,
                             tool_calls, input_tokens, output_tokens)
                        VALUES (:id, :unit, 1, :token, :deadline, 1,
                                CAST(:outcome AS consolidation_attempt_state),
                                :now, :now, :revision, :failure, :requests,
                                :tools, :inputs, :outputs)
                    """),
                        {
                            "id": job_id,
                            "unit": unit_id,
                            "token": uuid7().hex,
                            "deadline": now + datetime.timedelta(minutes=10),
                            "now": now,
                            "outcome": outcome,
                            "revision": revision,
                            "failure": failure,
                            "requests": requests,
                            "tools": tools,
                            "inputs": inputs,
                            "outputs": outputs,
                        },
                    )
                normalized_usage = {
                    "prompt_tokens": 21,
                    "completion_tokens": 8,
                    "total_tokens": 29,
                    "cached_tokens": 2,
                    "cache_creation_tokens": 3,
                    "reasoning_tokens": 4,
                    "cost_usd": 0.001,
                    "cost_method": "estimated",
                    "cost_source_key": "synthetic/catalog",
                    "cost_collected_at": now.isoformat(),
                    "cost_source_model_key": "legacy-cost-model",
                    "cost_estimator_version": "original-estimator",
                    "unsafe_provider_body": "Must not migrate provider text",
                }
                for (
                    job_id,
                    dispatch_id,
                    number,
                    reserved_in,
                    reserved_out,
                    recorded,
                    usage,
                ) in (
                    (success_job, known_dispatch, 1, 100, 64, True, normalized_usage),
                    (success_job, unknown_dispatch, 2, 200, None, True, None),
                    (failed_job, absent_dispatch, 1, 90, None, False, None),
                ):
                    await session.write_session.execute(
                        sa.text("""
                        INSERT INTO historical_consolidation_model_dispatches
                            (attempt_id, dispatch_id, request_number,
                             reserved_input_tokens, reserved_output_tokens,
                             usage_recorded, usage_json)
                        VALUES (:job, :dispatch, :number, :inputs, :outputs,
                                :recorded, CAST(:usage AS jsonb))
                    """),
                        {
                            "job": job_id,
                            "dispatch": dispatch_id,
                            "number": number,
                            "inputs": reserved_in,
                            "outputs": reserved_out,
                            "recorded": recorded,
                            "usage": None if usage is None else json.dumps(usage),
                        },
                    )
            await asyncio.to_thread(command.upgrade, config, "95521a5a1bbc")
            async with manager() as session:
                result = (
                    await session.read_session.execute(
                        sa.text(
                            "SELECT markdown, rendered_block "
                            "FROM memory_units WHERE id = :id"
                        ),
                        {"id": unit_id},
                    )
                ).one()
                assert (
                    result.markdown
                    == result.rendered_block
                    == "The selected current result"
                )
                work = (
                    await session.read_session.execute(
                        sa.text("SELECT id, admitted_session_id FROM memory_work")
                    )
                ).all()
                assert {row.id for row in work} == {
                    pending_id,
                    considered_id,
                    unallocated_personal_work,
                }
                assert all(row.admitted_session_id is None for row in work)
                personal = (
                    await session.read_session.execute(
                        sa.text("""
                    SELECT u.scope, u.associated_user_id, u.accepted_at
                    FROM memory_units u JOIN memory_work w ON w.unit_id = u.id
                    WHERE w.id = :id
                """),
                        {"id": unallocated_personal_work},
                    )
                ).one()
                assert (
                    personal.scope == "USER" and personal.associated_user_id == user.id
                )
                assert personal.accepted_at is None
                assert await session.read_session.get(RDBEvent, event.id) is not None
                assert (
                    await session.read_session.get(RDBAgentMemory, saved.id) is not None
                )
                kept_source = await session.read_session.get(
                    RDBHistoricalMemorySource, subject.agent_session.id
                )
                assert kept_source is not None
                assert kept_source.summary == "Canonical prepared summary"
                assert (
                    await session.read_session.get(RDBToolkitState, snapshot.id) is None
                )
                assert (
                    await session.read_session.get(RDBToolkitState, unrelated.id)
                    is not None
                )
                tables = set(
                    await session.read_session.scalars(
                        sa.text(
                            "SELECT tablename FROM pg_tables "
                            "WHERE schemaname = 'public'"
                        )
                    )
                )
                assert not any(
                    name.startswith("historical_consolidation_") for name in tables
                )
                removed_columns = set(
                    await session.read_session.scalars(
                        sa.text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'historical_memory_sources'
                """)
                    )
                )
                assert (
                    not {
                        "evidence_hash",
                        "summary_generation",
                        "availability_generation",
                    }
                    & removed_columns
                )
                success = await session.read_session.get(
                    RDBMemoryLegacyJob, success_job
                )
                failure = await session.read_session.get(RDBMemoryLegacyJob, failed_job)
                unmatched = await session.read_session.get(
                    RDBMemoryLegacyJob, unmatched_job
                )
                assert (
                    success is not None
                    and success.recorded_outcome
                    is MemoryLegacyRecordedOutcome.COMPLETED
                )
                assert success.created_at == success.finished_at == now
                assert success.deadline_at == now + datetime.timedelta(minutes=10)
                assert success.model_requests == 2 and success.tool_calls == 3
                assert success.input_tokens == 21 and success.output_tokens == 8
                assert success.result_published_at is not None
                assert success.rendered_bytes == len(
                    "The selected current result".encode()
                )
                assert (
                    failure is not None
                    and failure.recorded_outcome is MemoryLegacyRecordedOutcome.FAILED
                )
                assert failure.failure_code == "provider_authentication"
                assert (
                    failure.result_published_at is None
                    and failure.rendered_bytes is None
                )
                assert (
                    unmatched is not None
                    and unmatched.recorded_outcome
                    is MemoryLegacyRecordedOutcome.COMPLETED
                )
                assert (
                    unmatched.result_published_at is None
                    and unmatched.rendered_bytes is None
                )
                known = await session.read_session.get(
                    RDBMemoryLegacyModelUsage, (success_job, known_dispatch)
                )
                unknown = await session.read_session.get(
                    RDBMemoryLegacyModelUsage, (success_job, unknown_dispatch)
                )
                absent = await session.read_session.get(
                    RDBMemoryLegacyModelUsage, (failed_job, absent_dispatch)
                )
                assert known is not None and known.usage_recorded
                assert (
                    known.prompt_tokens == 21
                    and known.completion_tokens == 8
                    and known.total_tokens == 29
                )
                assert (
                    known.cached_tokens == 2
                    and known.cache_creation_tokens == 3
                    and known.reasoning_tokens == 4
                )
                assert known.cost_usd == pytest.approx(0.001)
                assert known.cost_method is MemoryLegacyCostMethod.ESTIMATED
                assert known.cost_source_key == "synthetic/catalog"
                assert known.cost_collected_at == now
                assert known.cost_source_model_key == "legacy-cost-model"
                assert known.cost_estimator_version == "original-estimator"
                assert unknown is not None and unknown.usage_recorded
                assert unknown.prompt_tokens is None and unknown.total_tokens is None
                assert (
                    unknown.reserved_input_tokens == 200
                    and unknown.reserved_output_tokens is None
                )
                assert (
                    absent is not None
                    and not absent.usage_recorded
                    and absent.prompt_tokens is None
                )
                assert (
                    await session.read_session.scalar(
                        sa.text("SELECT count(*) FROM memory_executions")
                    )
                    == 0
                )
                audit_columns = set(
                    await session.read_session.scalars(
                        sa.text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name IN
                        ('memory_legacy_jobs', 'memory_legacy_model_usage')
                """)
                    )
                )
                assert (
                    not {
                        "session_id",
                        "accepted_tool_call_id",
                        "owner_token",
                        "owner_generation",
                        "revision_id",
                        "markdown",
                        "rendered_block",
                        "usage_json",
                    }
                    & audit_columns
                )
                await session.write_session.execute(
                    sa.text("DELETE FROM memory_units WHERE id = :id"), {"id": unit_id}
                )
                assert (
                    await session.read_session.scalar(
                        sa.text("SELECT count(*) FROM memory_legacy_jobs")
                    )
                    == 0
                )
                assert (
                    await session.read_session.scalar(
                        sa.text("SELECT count(*) FROM memory_legacy_model_usage")
                    )
                    == 0
                )
                assert (
                    await session.read_session.get(
                        RDBHistoricalMemorySource, subject.agent_session.id
                    )
                    is not None
                )
                assert (
                    await session.read_session.get(RDBAgentMemory, saved.id) is not None
                )
                with pytest.raises(RuntimeError, match="irreversible"):
                    await asyncio.to_thread(command.downgrade, config, "6a05f4a01f6f")
        finally:
            await engine.dispose()
