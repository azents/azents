"""add Agent browser implementation and application intent

Revision ID: 0701fb42b5ce
Revises: f512e037a843
Create Date: 2026-10-23 05:02:50.238485

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0701fb42b5ce"
down_revision: str | Sequence[str] | None = "f512e037a843"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    implementation = postgresql.ENUM(
        "patchright", "camoufox", name="browser_implementation", create_type=False
    )
    state = postgresql.ENUM(
        "applying",
        "ready",
        "failed",
        name="agent_browser_application_state",
        create_type=False,
    )
    implementation.create(op.get_bind(), checkfirst=True)
    state.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "agents",
        sa.Column(
            "browser_implementation",
            implementation,
            nullable=False,
            server_default="patchright",
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "browser_configuration_intent_id",
            sa.String(32),
            nullable=False,
            server_default=sa.text("replace(gen_random_uuid()::text, '-', '')"),
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "browser_application_state",
            state,
            nullable=False,
            server_default="applying",
        ),
    )
    for name, kind in (
        ("browser_observed_runtime_id", sa.String(32)),
        ("browser_observed_runner_generation", sa.BigInteger()),
        ("browser_application_reason", sa.String(128)),
        ("browser_application_claim_id", sa.String(32)),
        ("browser_application_lease_until", sa.DateTime(timezone=True)),
    ):
        op.add_column("agents", sa.Column(name, kind, nullable=True))
    op.add_column(
        "agents",
        sa.Column(
            "browser_application_next_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_agents_browser_application_due", "agents", ["browser_application_next_at"]
    )
    op.create_check_constraint(
        "ck_agents_browser_observation",
        "agents",
        "(browser_observed_runtime_id IS NULL AND "
        "browser_observed_runner_generation IS NULL) OR "
        "(browser_observed_runtime_id IS NOT NULL AND "
        "browser_observed_runner_generation IS NOT NULL AND "
        "browser_observed_runner_generation > 0)",
    )
    op.create_check_constraint(
        "ck_agents_browser_claim",
        "agents",
        "(browser_application_claim_id IS NULL) = "
        "(browser_application_lease_until IS NULL)",
    )
    op.create_check_constraint(
        "ck_agents_browser_failure",
        "agents",
        "(browser_application_state = 'failed') = "
        "(browser_application_reason IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    for name in (
        "ck_agents_browser_failure",
        "ck_agents_browser_claim",
        "ck_agents_browser_observation",
    ):
        op.drop_constraint(name, "agents", type_="check")
    op.drop_index("ix_agents_browser_application_due", table_name="agents")
    for name in (
        "browser_application_next_at",
        "browser_application_lease_until",
        "browser_application_claim_id",
        "browser_application_reason",
        "browser_observed_runner_generation",
        "browser_observed_runtime_id",
        "browser_application_state",
        "browser_configuration_intent_id",
        "browser_implementation",
    ):
        op.drop_column("agents", name)
    postgresql.ENUM(name="agent_browser_application_state").drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="browser_implementation").drop(op.get_bind(), checkfirst=True)
