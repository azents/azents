"""Replace legacy External Channel inbound storage with mailbox authority."""

import datetime
import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import RowMapping

revision: str = "7f4c2a9d1b6e"
down_revision: str | Sequence[str] | None = "699b38c35430"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN_ADMISSION_STATUSES = (
    "pending_selection",
    "selected",
    "awaiting_access",
)
_RETIRED_ENUMS = (
    "external_channel_conversation_admission_origin",
    "external_channel_conversation_admission_status",
    "external_channel_invocation_wake_dispatch_status",
    "external_channel_message_lifecycle",
    "external_channel_message_revision_kind",
    "external_channel_resource_provisioning_operation",
    "external_channel_resource_provisioning_status",
)

_ADMISSION_ORIGIN = postgresql.ENUM(
    "single_route",
    "channel_default",
    "shortcut",
    "mention_selector",
    name="external_channel_conversation_admission_origin",
    create_type=False,
)
_ADMISSION_STATUS = postgresql.ENUM(
    "pending_selection",
    "selected",
    "awaiting_access",
    "bound",
    "expired",
    "rejected",
    name="external_channel_conversation_admission_status",
    create_type=False,
)
_WAKE_STATUS = postgresql.ENUM(
    "pending",
    "claimed",
    "dispatched",
    name="external_channel_invocation_wake_dispatch_status",
    create_type=False,
)
_MESSAGE_LIFECYCLE = postgresql.ENUM(
    "current",
    "edited",
    "deleted",
    name="external_channel_message_lifecycle",
    create_type=False,
)
_REVISION_KIND = postgresql.ENUM(
    "original",
    "edit",
    "delete",
    name="external_channel_message_revision_kind",
    create_type=False,
)
_PROVISIONING_OPERATION = postgresql.ENUM(
    "thread_create",
    name="external_channel_resource_provisioning_operation",
    create_type=False,
)
_PROVISIONING_STATUS = postgresql.ENUM(
    "pending",
    "attempting",
    "delivered",
    "failed",
    "unknown",
    name="external_channel_resource_provisioning_status",
    create_type=False,
)


def _scalar_count(bind: sa.Connection, query: str) -> int:
    return int(bind.execute(sa.text(query)).scalar_one())


def _selector_provider_key(connection_id: str, provider_message_key: str) -> str:
    digest = hashlib.sha256(
        f"{connection_id}\0{provider_message_key}".encode()
    ).hexdigest()
    return f"agent-selector:{digest}"


def _valid_provider_message_key(
    provider: object,
    provider_tenant_id: object,
    provider_message_key: object,
) -> bool:
    if (
        not isinstance(provider, str)
        or not isinstance(provider_tenant_id, str)
        or not provider_tenant_id
        or not isinstance(provider_message_key, str)
    ):
        return False
    prefix = f"{provider}:{provider_tenant_id}:"
    if not provider_message_key.startswith(prefix):
        return False
    remainder = provider_message_key.removeprefix(prefix)
    if provider == "slack":
        channel_id, separator, message_id = remainder.partition(":")
        return bool(channel_id and separator and message_id)
    if provider == "discord":
        return bool(remainder and ":" not in remainder)
    return False


def _open_admission_rows(bind: sa.Connection) -> list[RowMapping]:
    return list(
        bind.execute(
            sa.text(
                """
                SELECT
                    admission.id,
                    admission.connection_id,
                    admission.resource_id,
                    admission.initiating_principal_id,
                    admission.conversation_position_id,
                    admission.range_start_position,
                    admission.trigger_position,
                    admission.selected_route_id,
                    admission.status::text AS status,
                    admission.expires_at,
                    admission.created_at,
                    admission.updated_at,
                    connection.provider::text AS provider,
                    connection.provider_tenant_id,
                    connection.transport::text AS transport,
                    message.provider_message_key
                FROM external_channel_conversation_admissions AS admission
                JOIN external_channel_connections AS connection
                  ON connection.id = admission.connection_id
                JOIN external_channel_messages AS message
                  ON message.id = admission.source_message_id
                 AND message.resource_id = admission.resource_id
                WHERE admission.status IN (
                    'pending_selection',
                    'selected',
                    'awaiting_access'
                )
                ORDER BY admission.id
                """
            )
        ).mappings()
    )


def _assert_cutover_ready(bind: sa.Connection) -> None:
    rows = _open_admission_rows(bind)
    selector_id_collisions = 0
    selector_key_collisions = 0
    invalid_selectors = 0
    seen_selector_keys: set[tuple[str, str]] = set()
    for row in rows:
        required = (
            row["id"],
            row["connection_id"],
            row["resource_id"],
            row["initiating_principal_id"],
            row["conversation_position_id"],
            row["trigger_position"],
            row["provider_message_key"],
            row["transport"],
        )
        if any(not isinstance(value, str) or not value for value in required):
            invalid_selectors += 1
            continue
        if not _valid_provider_message_key(
            row["provider"],
            row["provider_tenant_id"],
            row["provider_message_key"],
        ):
            invalid_selectors += 1
            continue
        if row["status"] != "pending_selection" and (
            not isinstance(row["selected_route_id"], str)
            or not row["selected_route_id"]
        ):
            invalid_selectors += 1
        if bind.execute(
            sa.text(
                "SELECT 1 FROM external_channel_interactions WHERE id = :id LIMIT 1"
            ),
            {"id": row["id"]},
        ).first():
            selector_id_collisions += 1
        provider_key = _selector_provider_key(
            str(row["connection_id"]),
            str(row["provider_message_key"]),
        )
        selector_key = (str(row["connection_id"]), provider_key)
        if selector_key in seen_selector_keys:
            selector_key_collisions += 1
        else:
            seen_selector_keys.add(selector_key)
        if bind.execute(
            sa.text(
                """
                SELECT 1
                FROM external_channel_interactions
                WHERE connection_id = :connection_id
                  AND provider_interaction_key = :provider_key
                LIMIT 1
                """
            ),
            {
                "connection_id": row["connection_id"],
                "provider_key": provider_key,
            },
        ).first():
            selector_key_collisions += 1

    counts = {
        "resource_provisioning_inflight": _scalar_count(
            bind,
            """
            SELECT count(*)
            FROM external_channel_resource_provisionings
            WHERE status IN ('pending', 'attempting')
            """,
        ),
        "invocation_wake_undispatched": _scalar_count(
            bind,
            """
            SELECT count(*)
            FROM external_channel_invocation_batches
            WHERE wake_dispatch_status IN ('pending', 'claimed')
            """,
        ),
        "access_request_trigger_key_collisions": _scalar_count(
            bind,
            """
            SELECT count(*)
            FROM (
                SELECT request.route_id, message.provider_message_key
                FROM external_channel_access_requests AS request
                JOIN external_channel_messages AS message
                  ON message.id = request.source_message_id
                GROUP BY request.route_id, message.provider_message_key
                HAVING count(*) > 1
            ) AS collisions
            """,
        ),
        "selector_rows_invalid": invalid_selectors,
        "selector_id_collisions": selector_id_collisions,
        "selector_key_collisions": selector_key_collisions,
    }
    blocked = {name: count for name, count in counts.items() if count}
    if blocked:
        raise RuntimeError(
            "; ".join(f"{name}={count}" for name, count in blocked.items())
        )


def _migrate_access_request_identity(bind: sa.Connection) -> None:
    op.add_column(
        "external_channel_access_requests",
        sa.Column("trigger_provider_message_key", sa.Text(), nullable=True),
    )
    bind.execute(
        sa.text(
            """
            UPDATE external_channel_access_requests AS request
            SET trigger_provider_message_key = message.provider_message_key
            FROM external_channel_messages AS message
            WHERE message.id = request.source_message_id
            """
        )
    )
    missing = _scalar_count(
        bind,
        """
        SELECT count(*)
        FROM external_channel_access_requests
        WHERE trigger_provider_message_key IS NULL
        """,
    )
    if missing:
        raise RuntimeError(f"access_request_trigger_key_missing={missing}")
    op.alter_column(
        "external_channel_access_requests",
        "trigger_provider_message_key",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.drop_constraint(
        "uq_external_channel_access_requests_route_source_message",
        "external_channel_access_requests",
        type_="unique",
    )
    op.drop_constraint(
        "external_channel_access_requests_source_message_id_fkey",
        "external_channel_access_requests",
        type_="foreignkey",
    )
    op.drop_column("external_channel_access_requests", "source_message_id")
    op.create_unique_constraint(
        "uq_external_channel_access_requests_route_trigger_message",
        "external_channel_access_requests",
        ["route_id", "trigger_provider_message_key"],
    )


def _migrate_open_selectors(bind: sa.Connection) -> None:
    now = datetime.datetime.now(datetime.UTC)
    for row in _open_admission_rows(bind):
        state = {
            "connection_id": row["connection_id"],
            "resource_id": row["resource_id"],
            "principal_id": row["initiating_principal_id"],
            "conversation_position_id": row["conversation_position_id"],
            "trigger_provider_message_key": row["provider_message_key"],
            "range_start_position": row["range_start_position"],
            "trigger_position": row["trigger_position"],
            "selected_route_id": row["selected_route_id"],
        }
        expires_at = row["expires_at"]
        status = (
            "expired"
            if isinstance(expires_at, datetime.datetime) and expires_at <= now
            else "accepted"
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO external_channel_interactions (
                    id,
                    connection_id,
                    transport,
                    provider_interaction_key,
                    interaction_type,
                    projection,
                    status,
                    expires_at,
                    callback_id,
                    action_id,
                    principal_id,
                    resource_correlation_key,
                    error_kind,
                    error_summary,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :connection_id,
                    CAST(:transport AS external_channel_transport),
                    :provider_interaction_key,
                    'management_action',
                    CAST(:projection AS jsonb),
                    CAST(:status AS external_channel_interaction_status),
                    :expires_at,
                    NULL,
                    'agent_selector',
                    :principal_id,
                    NULL,
                    NULL,
                    NULL,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": row["id"],
                "connection_id": row["connection_id"],
                "transport": row["transport"],
                "provider_interaction_key": _selector_provider_key(
                    str(row["connection_id"]),
                    str(row["provider_message_key"]),
                ),
                "projection": json.dumps(
                    {"agent_selector": state},
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "status": status,
                "expires_at": expires_at,
                "principal_id": row["initiating_principal_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )


def _drop_retired_storage() -> None:
    op.drop_table("external_channel_resource_provisionings")
    op.drop_table("external_channel_conversation_admissions")
    op.drop_table("external_channel_invocation_batch_items")
    op.drop_table("external_channel_invocation_batches")
    op.drop_constraint(
        "fk_external_channel_messages_current_revision",
        "external_channel_messages",
        type_="foreignkey",
    )
    op.drop_table("external_channel_message_revisions")
    op.drop_table("external_channel_messages")
    for name in _RETIRED_ENUMS:
        op.execute(sa.text(f"DROP TYPE {name}"))


def upgrade() -> None:
    """Preserve replay boundaries, then remove legacy inbound persistence."""
    bind = op.get_bind()
    _assert_cutover_ready(bind)
    _migrate_access_request_identity(bind)
    _migrate_open_selectors(bind)
    _drop_retired_storage()


def _create_retired_enums(bind: sa.Connection) -> None:
    for enum_type in (
        _ADMISSION_ORIGIN,
        _ADMISSION_STATUS,
        _WAKE_STATUS,
        _MESSAGE_LIFECYCLE,
        _REVISION_KIND,
        _PROVISIONING_OPERATION,
        _PROVISIONING_STATUS,
    ):
        enum_type.create(bind)


def _restore_message_tables() -> None:
    op.create_table(
        "external_channel_messages",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(32), nullable=False),
        sa.Column("provider_message_key", sa.Text(), nullable=False),
        sa.Column("provider_position", sa.String(255), nullable=False),
        sa.Column(
            "lifecycle",
            _MESSAGE_LIFECYCLE,
            server_default="current",
            nullable=False,
        ),
        sa.Column(
            "author_type",
            postgresql.ENUM(
                name="external_channel_principal_author_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("principal_id", sa.String(32), nullable=True),
        sa.Column("current_revision_id", sa.String(32), nullable=True),
        sa.Column("original_url", sa.Text(), nullable=True),
        sa.Column("pending_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["external_channel_resources.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["external_channel_principals.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resource_id",
            "provider_message_key",
            name="uq_external_channel_messages_resource_provider_message",
        ),
        sa.UniqueConstraint(
            "resource_id",
            "id",
            name="uq_external_channel_messages_resource_id_id",
        ),
    )
    op.create_index(
        "ix_external_channel_messages_principal_id",
        "external_channel_messages",
        ["principal_id"],
    )
    op.create_index(
        "ix_external_channel_messages_resource_id_provider_position",
        "external_channel_messages",
        ["resource_id", "provider_position"],
    )
    op.create_table(
        "external_channel_message_revisions",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("message_id", sa.String(32), nullable=False),
        sa.Column("revision_key", sa.String(255), nullable=False),
        sa.Column("revision_kind", _REVISION_KIND, nullable=False),
        sa.Column("normalized_body", sa.Text(), nullable=True),
        sa.Column("attachment_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("reference_mappings", postgresql.JSONB(), nullable=True),
        sa.Column("provider_occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["external_channel_messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "revision_key",
            name="uq_external_channel_message_revisions_message_revision_key",
        ),
        sa.UniqueConstraint(
            "message_id",
            "id",
            name="uq_external_channel_message_revisions_message_id_id",
        ),
    )
    op.create_foreign_key(
        "fk_external_channel_messages_current_revision",
        "external_channel_messages",
        "external_channel_message_revisions",
        ["id", "current_revision_id"],
        ["message_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )


def _restore_admission_tables() -> None:
    op.create_table(
        "external_channel_conversation_admissions",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("connection_id", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(32), nullable=False),
        sa.Column("source_message_id", sa.String(32), nullable=False),
        sa.Column("initiating_principal_id", sa.String(32), nullable=True),
        sa.Column("origin", _ADMISSION_ORIGIN, nullable=False),
        sa.Column("status", _ADMISSION_STATUS, nullable=False),
        sa.Column("selected_route_id", sa.String(32), nullable=True),
        sa.Column("interaction_id", sa.String(32), nullable=True),
        sa.Column("conversation_position_id", sa.String(32), nullable=True),
        sa.Column("range_start_position", sa.Text(), nullable=True),
        sa.Column("trigger_position", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["external_channel_connections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "resource_id"],
            [
                "external_channel_resources.connection_id",
                "external_channel_resources.id",
            ],
            name="fk_external_channel_conv_admissions_connection_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id", "source_message_id"],
            [
                "external_channel_messages.resource_id",
                "external_channel_messages.id",
            ],
            name="fk_external_channel_conv_admissions_resource_source_message",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["initiating_principal_id"],
            ["external_channel_principals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "selected_route_id"],
            [
                "external_channel_agent_routes.connection_id",
                "external_channel_agent_routes.id",
            ],
            name="fk_external_channel_conv_admissions_connection_selected_route",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "interaction_id"],
            [
                "external_channel_interactions.connection_id",
                "external_channel_interactions.id",
            ],
            name="fk_external_channel_conv_admissions_connection_interaction",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "conversation_position_id"],
            [
                "external_channel_conversation_positions.connection_id",
                "external_channel_conversation_positions.id",
            ],
            name="fk_external_channel_conv_admissions_connection_position",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(status NOT IN ('pending_selection', 'selected', 'awaiting_access')) "
            "OR (conversation_position_id IS NOT NULL "
            "AND trigger_position IS NOT NULL)",
            name="ck_external_channel_conversation_admissions_open_boundary",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_conversation_admissions_connection_status",
        "external_channel_conversation_admissions",
        ["connection_id", "status"],
    )
    op.create_index(
        "ix_external_channel_conversation_admissions_expires_at",
        "external_channel_conversation_admissions",
        ["expires_at"],
    )
    op.create_index(
        "uq_external_channel_conversation_admissions_open_resource",
        "external_channel_conversation_admissions",
        ["resource_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending_selection', 'selected', 'awaiting_access')"
        ),
    )
    op.create_table(
        "external_channel_resource_provisionings",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(32), nullable=False),
        sa.Column("conversation_admission_id", sa.String(32), nullable=False),
        sa.Column("operation", _PROVISIONING_OPERATION, nullable=False),
        sa.Column("target_provider_resource_key", sa.String(255), nullable=False),
        sa.Column(
            "status",
            _PROVISIONING_STATUS,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("confirmed_provider_resource_key", sa.String(255), nullable=True),
        sa.Column("error_kind", sa.String(120), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["external_channel_resources.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_admission_id"],
            ["external_channel_conversation_admissions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resource_id",
            "conversation_admission_id",
            "operation",
            name="uq_ec_resource_provisionings_admission_operation",
        ),
    )
    op.create_index(
        "ix_external_channel_resource_provisionings_status_created_at",
        "external_channel_resource_provisionings",
        ["status", "created_at"],
    )


def _restore_invocation_tables() -> None:
    op.create_table(
        "external_channel_invocation_batches",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("binding_id", sa.String(32), nullable=False),
        sa.Column("trigger_message_id", sa.String(32), nullable=False),
        sa.Column("first_provider_position", sa.String(255), nullable=False),
        sa.Column("last_provider_position", sa.String(255), nullable=False),
        sa.Column("mailbox_item_id", sa.String(32), nullable=True),
        sa.Column("conversation_position_id", sa.String(32), nullable=True),
        sa.Column("connection_id", sa.String(32), nullable=True),
        sa.Column("range_start_position", sa.Text(), nullable=True),
        sa.Column("trigger_position", sa.Text(), nullable=True),
        sa.Column(
            "context_omitted",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "wake_dispatch_status",
            _WAKE_STATUS,
            server_default="dispatched",
            nullable=False,
        ),
        sa.Column(
            "wake_dispatch_claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["external_channel_bindings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_message_id"],
            ["external_channel_messages.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mailbox_item_id"],
            ["mailbox_items.id"],
            name="fk_external_channel_invocation_batches_mailbox_item_id_mailbox_",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "conversation_position_id"],
            [
                "external_channel_conversation_positions.connection_id",
                "external_channel_conversation_positions.id",
            ],
            name="fk_external_channel_invocation_batches_conversation_position",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id",
            "trigger_message_id",
            name="uq_external_channel_invocation_batches_binding_trigger_message",
        ),
    )
    op.create_index(
        "ix_external_channel_invocation_batches_binding_id_created_at",
        "external_channel_invocation_batches",
        ["binding_id", "created_at"],
    )
    op.create_table(
        "external_channel_invocation_batch_items",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("batch_id", sa.String(32), nullable=False),
        sa.Column("message_revision_id", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("provider_position", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["external_channel_invocation_batches.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_revision_id"],
            ["external_channel_message_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "message_revision_id",
            name="uq_external_channel_invocation_batch_items_batch_revision",
        ),
        sa.UniqueConstraint(
            "batch_id",
            "sequence",
            name="uq_external_channel_invocation_batch_items_batch_sequence",
        ),
    )
    op.create_index(
        "ix_external_channel_invocation_batch_items_message_revision_id",
        "external_channel_invocation_batch_items",
        ["message_revision_id"],
    )


def downgrade() -> None:
    """Restore only the empty legacy shape; retained data cannot be reconstructed."""
    bind = op.get_bind()
    access_request_count = _scalar_count(
        bind,
        "SELECT count(*) FROM external_channel_access_requests",
    )
    if access_request_count:
        raise RuntimeError(
            f"external_channel_access_requests_prevent_downgrade={access_request_count}"
        )
    _create_retired_enums(bind)
    _restore_message_tables()
    _restore_admission_tables()
    _restore_invocation_tables()
    op.drop_constraint(
        "uq_external_channel_access_requests_route_trigger_message",
        "external_channel_access_requests",
        type_="unique",
    )
    op.add_column(
        "external_channel_access_requests",
        sa.Column("source_message_id", sa.String(32), nullable=True),
    )
    op.drop_column(
        "external_channel_access_requests",
        "trigger_provider_message_key",
    )
    op.alter_column(
        "external_channel_access_requests",
        "source_message_id",
        existing_type=sa.String(32),
        nullable=False,
    )
    op.create_foreign_key(
        "external_channel_access_requests_source_message_id_fkey",
        "external_channel_access_requests",
        "external_channel_messages",
        ["source_message_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_external_channel_access_requests_route_source_message",
        "external_channel_access_requests",
        ["route_id", "source_message_id"],
    )
