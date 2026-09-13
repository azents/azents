"""remove runtime web configuration versioning

Revision ID: 41c53610f55a
Revises: a779d057128b
Create Date: 2026-09-13 08:17:47.917897

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "41c53610f55a"
down_revision: str | Sequence[str] | None = "a779d057128b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        sa.text(
            """
            UPDATE runtime_web_gateway_identities AS identity
            SET revoked_at = now()
            FROM runtime_web_auth_configuration AS configuration
            WHERE configuration.id = 1
              AND identity.epoch <> configuration.active_epoch
              AND identity.revoked_at IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM runtime_web_auth_tickets AS ticket
            USING runtime_web_auth_configuration AS configuration
            WHERE configuration.id = 1
              AND ticket.epoch <> configuration.active_epoch
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM runtime_web_auth_bindings AS binding
            USING runtime_web_auth_configuration AS configuration
            WHERE configuration.id = 1
              AND binding.epoch <> configuration.active_epoch
            """
        )
    )
    op.drop_constraint(
        "ck_runtime_web_cycles_duration_configuration_revision",
        "runtime_web_cycles",
        type_="check",
    )
    op.drop_column("runtime_web_cycles", "duration_configuration_revision")
    op.drop_column("runtime_web_gateway_identities", "epoch")
    op.drop_column("runtime_web_auth_bindings", "epoch")
    op.drop_column("runtime_web_auth_tickets", "epoch")
    op.drop_constraint(
        "ck_runtime_web_auth_configuration_versions",
        "runtime_web_auth_configuration",
        type_="check",
    )
    op.drop_column("runtime_web_auth_configuration", "configuration_version")
    op.drop_column("runtime_web_auth_configuration", "active_epoch")
    op.drop_column(
        "runtime_web_auth_configuration",
        "duration_configuration_revision",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "runtime_web_auth_configuration",
        sa.Column(
            "duration_configuration_revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "runtime_web_auth_configuration",
        sa.Column(
            "active_epoch",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "runtime_web_auth_configuration",
        sa.Column(
            "configuration_version",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_runtime_web_auth_configuration_versions",
        "runtime_web_auth_configuration",
        "configuration_version >= 1 AND active_epoch >= 1 AND "
        "duration_configuration_revision >= 1",
    )
    for column in (
        "configuration_version",
        "active_epoch",
        "duration_configuration_revision",
    ):
        op.alter_column(
            "runtime_web_auth_configuration",
            column,
            server_default=None,
        )
    for table in (
        "runtime_web_auth_tickets",
        "runtime_web_auth_bindings",
        "runtime_web_gateway_identities",
    ):
        op.add_column(
            table,
            sa.Column(
                "epoch",
                sa.BigInteger(),
                nullable=False,
                server_default="1",
            ),
        )
        op.alter_column(table, "epoch", server_default=None)
    op.add_column(
        "runtime_web_cycles",
        sa.Column(
            "duration_configuration_revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_runtime_web_cycles_duration_configuration_revision",
        "runtime_web_cycles",
        "duration_configuration_revision >= 1",
    )
    op.alter_column(
        "runtime_web_cycles",
        "duration_configuration_revision",
        server_default=None,
    )
