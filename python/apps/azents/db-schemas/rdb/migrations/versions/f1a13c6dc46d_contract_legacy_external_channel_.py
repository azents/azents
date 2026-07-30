"""Contract legacy External Channel processing state."""

from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a13c6dc46d"
down_revision: str | Sequence[str] | None = "acd4e70d9c19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_ELIGIBILITY_ENUM = postgresql.ENUM(
    "unclassified",
    "tracked",
    "ignored",
    "processed",
    name="external_channel_event_eligibility_state",
    create_type=False,
)
_EVENT_STATUS_ENUM = postgresql.ENUM(
    "accepted",
    "ignored_unlinked",
    "processing",
    "processed",
    "failed",
    name="external_channel_event_status",
    create_type=False,
)
_HYDRATION_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "running",
    "complete",
    "bounded",
    "incomplete",
    name="external_channel_hydration_status",
    create_type=False,
)
_ACTIVATION_STATUS_ENUM = postgresql.ENUM(
    "waiting_hydration",
    "active",
    "wake_pending",
    name="external_channel_binding_activation_status",
    create_type=False,
)


def _scalar_count(bind: sa.Connection, query: str) -> int:
    """Return one aggregate count without exposing row content."""
    return int(bind.execute(sa.text(query)).scalar_one())


def _thread_scope(
    provider_resource_key: str,
    labels: Mapping[str, Any] | None,
) -> tuple[str, str] | None:
    """Return the canonical thread scope used by the qualified preflight."""
    parts = provider_resource_key.split(":")
    if provider_resource_key.startswith("slack:") and len(parts) == 4:
        return parts[2], parts[3]
    if provider_resource_key.startswith("discord:") and len(parts) == 3:
        values = labels or {}
        target = next(
            (
                value
                for name in (
                    "delivery_channel_id",
                    "thread_channel_id",
                    "thread_id",
                )
                if isinstance((value := values.get(name)), str) and value
            ),
            None,
        )
        if target is not None:
            return target, target
    return None


def _active_binding_counts(bind: sa.Connection) -> Mapping[str, int]:
    """Revalidate aggregate ownership for every active binding."""
    counts = {
        "active_bindings_without_delivery_target": 0,
        "active_bindings_without_session": 0,
        "active_bindings_without_route": 0,
        "active_bindings_without_latest_batch": 0,
        "active_bindings_without_thread_position": 0,
        "active_bindings_with_ambiguous_thread_position": 0,
    }
    rows = bind.execute(
        sa.text(
            """
            SELECT
                binding.id,
                resource.connection_id,
                resource.provider_resource_key,
                resource.labels,
                session.id IS NOT NULL AS has_session,
                route.id IS NOT NULL AS has_route,
                EXISTS (
                    SELECT 1
                    FROM external_channel_invocation_batches AS batch
                    WHERE batch.binding_id = binding.id
                ) AS has_batch
            FROM external_channel_bindings AS binding
            JOIN external_channel_resources AS resource
              ON resource.id = binding.resource_id
            LEFT JOIN agent_sessions AS session
              ON session.id = binding.agent_session_id
            LEFT JOIN external_channel_agent_routes AS route
              ON route.id = binding.route_id
            WHERE binding.status = 'active'
            ORDER BY binding.id
            """
        )
    ).mappings()
    for row in rows:
        if not row["has_session"]:
            counts["active_bindings_without_session"] += 1
        if not row["has_route"]:
            counts["active_bindings_without_route"] += 1
        if not row["has_batch"]:
            counts["active_bindings_without_latest_batch"] += 1

        provider_resource_key = str(row["provider_resource_key"])
        labels = row["labels"] if isinstance(row["labels"], Mapping) else None
        scope = _thread_scope(provider_resource_key, labels)
        if scope is None:
            if provider_resource_key.startswith("discord:"):
                counts["active_bindings_without_delivery_target"] += 1
            counts["active_bindings_with_ambiguous_thread_position"] += 1
            continue

        positions = bind.execute(
            sa.text(
                """
                SELECT read_through_position
                FROM external_channel_conversation_positions
                WHERE connection_id = :connection_id
                  AND scope_kind = 'thread'
                  AND provider_channel_id = :provider_channel_id
                  AND provider_thread_key = :provider_thread_key
                """
            ),
            {
                "connection_id": row["connection_id"],
                "provider_channel_id": scope[0],
                "provider_thread_key": scope[1],
            },
        ).all()
        if len(positions) > 1:
            counts["active_bindings_with_ambiguous_thread_position"] += 1
        elif not positions or positions[0][0] is None:
            counts["active_bindings_without_thread_position"] += 1
    return counts


def _contraction_counts(bind: sa.Connection) -> Mapping[str, int]:
    """Return aggregate-only cutover and ownership preconditions."""
    counts = {
        "events_undrained": _scalar_count(
            bind,
            """
            SELECT count(*)
            FROM external_channel_events
            WHERE status IN ('accepted', 'processing', 'failed')
            """,
        ),
        "bindings_unactivated": _scalar_count(
            bind,
            """
            SELECT count(*)
            FROM external_channel_bindings
            WHERE status = 'active'
              AND activation_status IN ('waiting_hydration', 'wake_pending')
            """,
        ),
        "hydrations_incomplete": _scalar_count(
            bind,
            """
            SELECT count(*)
            FROM external_channel_resources
            WHERE hydration_status IN ('pending', 'running', 'incomplete')
            """,
        ),
        "pending_contexts": _scalar_count(
            bind,
            "SELECT count(*) FROM external_channel_pending_contexts",
        ),
        "conversation_admissions_open": _scalar_count(
            bind,
            """
            SELECT count(*)
            FROM external_channel_conversation_admissions
            WHERE status IN ('pending_selection', 'selected', 'awaiting_access')
            """,
        ),
        "access_requests_pending": _scalar_count(
            bind,
            """
            SELECT count(*)
            FROM external_channel_access_requests
            WHERE status = 'pending'
            """,
        ),
        "resource_provisioning_inflight": _scalar_count(
            bind,
            """
            SELECT count(*)
            FROM external_channel_resource_provisionings
            WHERE status IN ('pending', 'attempting')
            """,
        ),
    }
    return {**counts, **_active_binding_counts(bind)}


def _assert_contraction_ready(bind: sa.Connection) -> None:
    """Abort before destructive DDL when any cutover prerequisite is nonzero."""
    blocked = {
        category: count
        for category, count in _contraction_counts(bind).items()
        if count
    }
    if blocked:
        summary = "; ".join(
            f"{category}={count}" for category, count in blocked.items()
        )
        raise RuntimeError(summary)


def _create_retired_enums(bind: sa.Connection) -> None:
    """Restore enum types required by a structural downgrade."""
    for enum_type in (
        _EVENT_ELIGIBILITY_ENUM,
        _EVENT_STATUS_ENUM,
        _HYDRATION_STATUS_ENUM,
        _ACTIVATION_STATUS_ENUM,
    ):
        enum_type.create(bind, checkfirst=True)


def upgrade() -> None:
    """Remove legacy processing state after a repeated content-free preflight."""
    bind = op.get_bind()
    _assert_contraction_ready(bind)

    op.create_check_constraint(
        "ck_external_channel_conversation_admissions_open_boundary",
        "external_channel_conversation_admissions",
        "status NOT IN ('pending_selection', 'selected', 'awaiting_access') OR "
        "(conversation_position_id IS NOT NULL AND trigger_position IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_external_channel_access_requests_pending_boundary",
        "external_channel_access_requests",
        "status <> 'pending' OR "
        "(connection_id IS NOT NULL AND conversation_position_id IS NOT NULL "
        "AND trigger_position IS NOT NULL)",
    )

    op.drop_table("external_channel_pending_contexts")
    op.drop_index(
        "ix_external_channel_message_revisions_source_event_id",
        table_name="external_channel_message_revisions",
    )
    op.drop_constraint(
        "external_channel_message_revisions_source_event_id_fkey",
        "external_channel_message_revisions",
        type_="foreignkey",
    )
    op.drop_column("external_channel_message_revisions", "source_event_id")
    op.drop_table("external_channel_events")

    for column in (
        "hydration_completed_at",
        "hydration_started_at",
        "hydration_error_summary",
        "hydration_error_kind",
        "reconciliation_boundary_event_id",
        "reconciliation_boundary_received_at",
        "hydration_high_watermark_position",
        "hydration_cursor",
        "hydration_status",
    ):
        op.drop_column("external_channel_resources", column)

    op.drop_constraint(
        "fk_external_channel_bindings_activation_trigger_message",
        "external_channel_bindings",
        type_="foreignkey",
    )
    for column in (
        "activation_wake_claimed_at",
        "activated_at",
        "activation_trigger_message_id",
        "activation_status",
        "projected_through_position",
        "truncated_message_count",
        "truncated_size",
    ):
        op.drop_column("external_channel_bindings", column)

    op.drop_column(
        "external_channel_invocation_batches",
        "truncation_message_count",
    )
    op.drop_column("external_channel_invocation_batches", "truncation_size")

    for enum_type in (
        _ACTIVATION_STATUS_ENUM,
        _HYDRATION_STATUS_ENUM,
        _EVENT_STATUS_ENUM,
        _EVENT_ELIGIBILITY_ENUM,
    ):
        enum_type.drop(bind, checkfirst=True)


def downgrade() -> None:
    """Restore the retired schema shape without reconstructing discarded rows."""
    bind = op.get_bind()
    _create_retired_enums(bind)

    op.create_table(
        "external_channel_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column(
            "envelope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "eligibility_state",
            _EVENT_ELIGIBILITY_ENUM,
            server_default="unclassified",
            nullable=False,
        ),
        sa.Column(
            "status",
            _EVENT_STATUS_ENUM,
            server_default="accepted",
            nullable=False,
        ),
        sa.Column("transport_envelope_id", sa.String(length=255), nullable=True),
        sa.Column("provider_app_id", sa.String(length=255), nullable=True),
        sa.Column("provider_tenant_id", sa.String(length=255), nullable=True),
        sa.Column("provider_enterprise_id", sa.String(length=255), nullable=True),
        sa.Column("resource_correlation_key", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claim_owner", sa.String(length=120), nullable=True),
        sa.Column("claim_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_kind", sa.String(length=120), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("provider_occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["external_channel_connections.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "provider_event_id",
            name="uq_external_channel_events_connection_provider_event",
        ),
    )
    op.create_index(
        "ix_external_channel_events_connection_id_provider_timestamp",
        "external_channel_events",
        ["connection_id", "provider_occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_events_connection_correlation_status",
        "external_channel_events",
        ["connection_id", "resource_correlation_key", "status", "received_at"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_events_status_received_at",
        "external_channel_events",
        ["status", "received_at"],
        unique=False,
    )

    op.add_column(
        "external_channel_message_revisions",
        sa.Column("source_event_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "external_channel_message_revisions_source_event_id_fkey",
        "external_channel_message_revisions",
        "external_channel_events",
        ["source_event_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_external_channel_message_revisions_source_event_id",
        "external_channel_message_revisions",
        ["source_event_id"],
        unique=False,
    )

    op.add_column(
        "external_channel_resources",
        sa.Column(
            "hydration_status",
            _HYDRATION_STATUS_ENUM,
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column("hydration_cursor", sa.Text(), nullable=True),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column(
            "hydration_high_watermark_position",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column(
            "reconciliation_boundary_received_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column(
            "reconciliation_boundary_event_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column("hydration_error_kind", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column("hydration_error_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column("hydration_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "external_channel_resources",
        sa.Column("hydration_completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "activation_status",
            _ACTIVATION_STATUS_ENUM,
            server_default="waiting_hydration",
            nullable=False,
        ),
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "activation_trigger_message_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "activation_wake_claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "projected_through_position",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "truncated_message_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "truncated_size",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_external_channel_bindings_activation_trigger_message",
        "external_channel_bindings",
        "external_channel_messages",
        ["activation_trigger_message_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "external_channel_invocation_batches",
        sa.Column(
            "truncation_message_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "external_channel_invocation_batches",
        sa.Column(
            "truncation_size",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )

    op.create_table(
        "external_channel_pending_contexts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("route_id", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=32), nullable=False),
        sa.Column("message_revision_id", sa.String(length=32), nullable=False),
        sa.Column("provider_position", sa.String(length=255), nullable=False),
        sa.Column("normalized_size", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_revision_id"],
            ["external_channel_message_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["external_channel_resources.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["external_channel_agent_routes.id"],
            name="external_channel_pending_contexts_route_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "route_id",
            "resource_id",
            "message_revision_id",
            name="uq_external_channel_pending_route_resource_message_revision",
        ),
    )
    op.create_index(
        "ix_external_channel_pending_contexts_expires_at",
        "external_channel_pending_contexts",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_pending_ctx_route_resource_position",
        "external_channel_pending_contexts",
        ["route_id", "resource_id", "provider_position"],
        unique=False,
    )

    op.drop_constraint(
        "ck_external_channel_access_requests_pending_boundary",
        "external_channel_access_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_external_channel_conversation_admissions_open_boundary",
        "external_channel_conversation_admissions",
        type_="check",
    )
