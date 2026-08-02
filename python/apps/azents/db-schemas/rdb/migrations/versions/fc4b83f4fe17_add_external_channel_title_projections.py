"""Add External Channel automatic title projections."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fc4b83f4fe17"
down_revision: str | Sequence[str] | None = "772e7ab22a8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CANDIDATE_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "consumed",
    "relinquished",
    name="external_channel_session_title_candidate_status",
    create_type=False,
)
_OBSERVATION_STATUS_ENUM = postgresql.ENUM(
    "thread_absent",
    "thread_present",
    "unknown",
    name="external_channel_discord_thread_observation_status",
    create_type=False,
)
_PROVISIONING_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "attempting",
    "retry_wait",
    "ready",
    "unmanaged",
    "failed",
    name="external_channel_discord_thread_title_provisioning_status",
    create_type=False,
)
_PROOF_KIND_ENUM = postgresql.ENUM(
    "direct",
    "adopted",
    name="external_channel_discord_thread_title_proof_kind",
    create_type=False,
)
_TITLE_STATUS_ENUM = postgresql.ENUM(
    "waiting",
    "pending",
    "attempting",
    "retry_wait",
    "applied",
    "relinquished",
    "failed",
    name="external_channel_discord_thread_title_status",
    create_type=False,
)


def _create_enum_types() -> None:
    """Create PostgreSQL enum types owned by this revision."""
    bind = op.get_bind()
    for enum_type in (
        _CANDIDATE_STATUS_ENUM,
        _OBSERVATION_STATUS_ENUM,
        _PROVISIONING_STATUS_ENUM,
        _PROOF_KIND_ENUM,
        _TITLE_STATUS_ENUM,
    ):
        enum_type.create(bind)


def _drop_enum_types() -> None:
    """Drop PostgreSQL enum types owned by this revision."""
    bind = op.get_bind()
    for enum_type in (
        _TITLE_STATUS_ENUM,
        _PROOF_KIND_ENUM,
        _PROVISIONING_STATUS_ENUM,
        _OBSERVATION_STATUS_ENUM,
        _CANDIDATE_STATUS_ENUM,
    ):
        enum_type.drop(bind)


def _abort_unsafe_downgrade() -> None:
    """Reject downgrade after automatic-title state has been written."""
    unsafe = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT EXISTS (
                SELECT 1 FROM external_channel_session_title_candidates
            ) OR EXISTS (
                SELECT 1 FROM external_channel_discord_thread_title_projections
            )
            """
            )
        )
        .scalar_one()
    )
    if unsafe:
        raise RuntimeError(
            "Cannot downgrade after External Channel automatic title state is written."
        )


def upgrade() -> None:
    """Add additive automatic title state without backfilling existing bindings."""
    _create_enum_types()

    op.create_table(
        "external_channel_session_title_candidates",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column("trigger_provider_message_key", sa.Text(), nullable=False),
        sa.Column(
            "status",
            _CANDIDATE_STATUS_ENUM,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("consumed_event_id", sa.String(length=32), nullable=True),
        sa.Column("relinquished_reason", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "(status = 'consumed' AND consumed_event_id IS NOT NULL) OR "
            "(status <> 'consumed' AND consumed_event_id IS NULL)",
            name="ck_ec_session_title_candidates_consumed_event",
        ),
        sa.CheckConstraint(
            "(status = 'relinquished' AND relinquished_reason IS NOT NULL) OR "
            "(status <> 'relinquished' AND relinquished_reason IS NULL)",
            name="ck_ec_session_title_candidates_relinquished_reason",
        ),
        sa.ForeignKeyConstraint(
            ["agent_session_id"],
            ["agent_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["external_channel_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["consumed_event_id"],
            ["events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_session_id",
            name="uq_ec_session_title_candidates_agent_session",
        ),
        sa.UniqueConstraint(
            "binding_id",
            "trigger_provider_message_key",
            name="uq_ec_session_title_candidates_binding_trigger",
        ),
        sa.UniqueConstraint(
            "id",
            "agent_session_id",
            "binding_id",
            "trigger_provider_message_key",
            name="uq_ec_session_title_candidates_id_session_binding_trigger",
        ),
    )

    op.create_table(
        "external_channel_discord_thread_title_projections",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=False),
        sa.Column("session_title_candidate_id", sa.String(length=32), nullable=False),
        sa.Column(
            "provisioning_protocol_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("requested_provisional_title", sa.Text(), nullable=False),
        sa.Column("admission_connection_id", sa.String(length=32), nullable=False),
        sa.Column("admission_guild_id", sa.String(length=255), nullable=False),
        sa.Column("admission_parent_channel_id", sa.String(length=255), nullable=False),
        sa.Column("admission_root_message_id", sa.String(length=255), nullable=False),
        sa.Column("admission_trigger_provider_message_key", sa.Text(), nullable=False),
        sa.Column(
            "admission_observation_status", _OBSERVATION_STATUS_ENUM, nullable=False
        ),
        sa.Column("admission_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "provisioning_status",
            _PROVISIONING_STATUS_ENUM,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("admission_root_has_thread", sa.Boolean(), nullable=True),
        sa.Column(
            "admission_observed_thread_channel_id", sa.String(length=255), nullable=True
        ),
        sa.Column("preflight_absent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thread_channel_id", sa.String(length=255), nullable=True),
        sa.Column("expected_provisional_title", sa.Text(), nullable=True),
        sa.Column("provisioning_proof_kind", _PROOF_KIND_ENUM, nullable=True),
        sa.Column(
            "provision_attempt_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "provision_next_attempt_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("provision_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provision_failure_kind", sa.String(length=120), nullable=True),
        sa.Column("provision_failure_summary", sa.String(length=255), nullable=True),
        sa.Column("provision_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("desired_title", sa.Text(), nullable=True),
        sa.Column("title_generation_event_id", sa.String(length=32), nullable=True),
        sa.Column(
            "title_status", _TITLE_STATUS_ENUM, nullable=False, server_default="waiting"
        ),
        sa.Column(
            "title_attempt_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("title_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title_failure_kind", sa.String(length=120), nullable=True),
        sa.Column("title_failure_summary", sa.String(length=255), nullable=True),
        sa.Column("title_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "(admission_observation_status = 'thread_absent' "
            "AND admission_root_has_thread = false "
            "AND admission_observed_thread_channel_id IS NULL) OR "
            "(admission_observation_status = 'thread_present' "
            "AND admission_root_has_thread = true "
            "AND admission_observed_thread_channel_id IS NOT NULL) OR "
            "admission_observation_status = 'unknown'",
            name="ck_ec_discord_title_projection_admission",
        ),
        sa.CheckConstraint(
            "(provisioning_status = 'attempting' "
            "AND provision_claimed_at IS NOT NULL) OR "
            "provisioning_status <> 'attempting'",
            name="ck_ec_discord_title_projection_provision_claim",
        ),
        sa.CheckConstraint(
            "(provisioning_status = 'ready' "
            "AND thread_channel_id IS NOT NULL "
            "AND expected_provisional_title IS NOT NULL "
            "AND provisioning_proof_kind IS NOT NULL "
            "AND provision_completed_at IS NOT NULL) OR "
            "provisioning_status <> 'ready'",
            name="ck_ec_discord_title_projection_provision_ready",
        ),
        sa.CheckConstraint(
            "(provisioning_status = 'retry_wait' "
            "AND provision_next_attempt_at IS NOT NULL) OR "
            "provisioning_status <> 'retry_wait'",
            name="ck_ec_discord_title_projection_provision_retry",
        ),
        sa.CheckConstraint(
            "(provisioning_status IN ('ready', 'unmanaged', 'failed') "
            "AND provision_completed_at IS NOT NULL) OR "
            "provisioning_status NOT IN ('ready', 'unmanaged', 'failed')",
            name="ck_ec_discord_title_projection_provision_terminal",
        ),
        sa.CheckConstraint(
            "(title_status = 'attempting' AND title_claimed_at IS NOT NULL) OR "
            "title_status <> 'attempting'",
            name="ck_ec_discord_title_projection_title_claim",
        ),
        sa.CheckConstraint(
            "(title_status = 'retry_wait' AND title_next_attempt_at IS NOT NULL) OR "
            "title_status <> 'retry_wait'",
            name="ck_ec_discord_title_projection_title_retry",
        ),
        sa.CheckConstraint(
            "("
            "title_status IN ('pending', 'attempting', 'retry_wait', 'applied') "
            "AND desired_title IS NOT NULL "
            "AND title_generation_event_id IS NOT NULL"
            ") OR ("
            "title_status NOT IN ('pending', 'attempting', 'retry_wait', 'applied') "
            "AND ("
            "(desired_title IS NULL AND title_generation_event_id IS NULL) OR "
            "(desired_title IS NOT NULL AND title_generation_event_id IS NOT NULL)"
            ")"
            ")",
            name="ck_ec_discord_title_projection_title_ready",
        ),
        sa.CheckConstraint(
            "(title_status IN ('applied', 'relinquished', 'failed') "
            "AND title_completed_at IS NOT NULL) OR "
            "title_status NOT IN ('applied', 'relinquished', 'failed')",
            name="ck_ec_discord_title_projection_title_terminal",
        ),
        sa.CheckConstraint(
            "title_status IN ('waiting', 'relinquished', 'failed') OR "
            "provisioning_status = 'ready'",
            name="ck_ec_discord_title_projection_title_provider_ready",
        ),
        sa.CheckConstraint(
            "length(btrim(requested_provisional_title)) > 0",
            name="ck_ec_discord_title_projection_requested_title",
        ),
        sa.CheckConstraint(
            "provisioning_protocol_version > 0",
            name="ck_ec_discord_title_projection_protocol_version",
        ),
        sa.ForeignKeyConstraint(
            ["agent_session_id"],
            ["agent_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["external_channel_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["external_channel_resources.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "session_title_candidate_id",
                "agent_session_id",
                "binding_id",
                "admission_trigger_provider_message_key",
            ],
            [
                "external_channel_session_title_candidates.id",
                "external_channel_session_title_candidates.agent_session_id",
                "external_channel_session_title_candidates.binding_id",
                "external_channel_session_title_candidates.trigger_provider_message_key",
            ],
            name="fk_ec_discord_title_projection_candidate_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["title_generation_event_id"],
            ["events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resource_id",
            name="uq_ec_discord_title_projections_resource",
        ),
    )
    op.create_index(
        "ix_ec_discord_title_projections_provision_due",
        "external_channel_discord_thread_title_projections",
        ["provisioning_status", "provision_next_attempt_at"],
    )
    op.create_index(
        "ix_ec_discord_title_projections_title_due",
        "external_channel_discord_thread_title_projections",
        ["title_status", "title_next_attempt_at"],
    )


def downgrade() -> None:
    """Downgrade only before automatic-title state has been written."""
    _abort_unsafe_downgrade()
    op.drop_index(
        "ix_ec_discord_title_projections_title_due",
        table_name="external_channel_discord_thread_title_projections",
    )
    op.drop_index(
        "ix_ec_discord_title_projections_provision_due",
        table_name="external_channel_discord_thread_title_projections",
    )
    op.drop_table("external_channel_discord_thread_title_projections")
    op.drop_table("external_channel_session_title_candidates")
    _drop_enum_types()
