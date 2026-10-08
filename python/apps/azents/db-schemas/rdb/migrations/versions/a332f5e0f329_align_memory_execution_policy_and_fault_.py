"""Align Historical Memory execution policy and operational fault observability."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a332f5e0f329"
down_revision: str | Sequence[str] | None = "4ededb171886"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE system_setting_section ADD VALUE 'historical_memory_execution'"
    )
    op.drop_constraint(
        "ck_historical_consolidation_model_dispatches_budget",
        "historical_consolidation_model_dispatches",
        type_="check",
    )
    op.alter_column(
        "historical_consolidation_model_dispatches",
        "reserved_output_tokens",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_historical_consolidation_model_dispatches_budget",
        "historical_consolidation_model_dispatches",
        "request_number >= 1 AND reserved_input_tokens >= 0 AND "
        "(reserved_output_tokens IS NULL OR reserved_output_tokens >= 1)",
    )
    op.drop_constraint(
        "ck_historical_consolidation_drafts_limits",
        "historical_consolidation_drafts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_historical_consolidation_drafts_limits",
        "historical_consolidation_drafts",
        "file_count >= 0 AND byte_count >= 0",
    )
    op.drop_constraint(
        "ck_historical_consolidation_draft_files_size",
        "historical_consolidation_draft_files",
        type_="check",
    )
    op.execute(
        "UPDATE historical_consolidation_attempts SET failure_code = NULL "
        "WHERE failure_code IS NOT NULL AND failure_code NOT IN ("
        "'model_provider_authentication', 'model_provider_permission', "
        "'model_provider_quota_or_billing', 'model_provider_model_unavailable')"
    )


def downgrade() -> None:
    raise RuntimeError(
        "irreversible: previous draft/token restrictions cannot be restored "
        "without discarding valid execution data and system policy."
    )
