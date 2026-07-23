"""add provider native channel work progress

Revision ID: 1d10cb8faa04
Revises: 0f30e3780e6b
Create Date: 2026-07-23 10:44:31.156570

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1d10cb8faa04"
down_revision: str | Sequence[str] | None = "0f30e3780e6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "external_channel_works",
        sa.Column("title", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE external_channel_works
        SET title = CASE
            WHEN jsonb_array_length(tasks) > 0
            THEN left(coalesce(tasks -> 0 ->> 'title', 'Agent is working'), 499) || '…'
            ELSE NULL
        END
        """
    )
    op.execute(
        """
        UPDATE external_channel_works AS work
        SET tasks = coalesce(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'id', task.item ->> 'id',
                        'title', task.item ->> 'title',
                        'status', task.item ->> 'status',
                        'details', NULL,
                        'output', NULL,
                        'sources', '[]'::jsonb
                    )
                    ORDER BY task.ordinality
                )
                FROM jsonb_array_elements(work.tasks)
                    WITH ORDINALITY AS task(item, ordinality)
            ),
            '[]'::jsonb
        )
        """
    )
    op.execute(
        """
        UPDATE external_channel_works
        SET desired_progress_payload = CASE
            WHEN desired_progress_payload IS NULL THEN NULL
            WHEN desired_progress_payload ->> 'state' = 'checking'
            THEN jsonb_build_object(
                'schema_version', 2,
                'state', 'checking',
                'title', NULL,
                'tasks', '[]'::jsonb
            )
            ELSE jsonb_build_object(
                'schema_version', 2,
                'state', 'working',
                'title', title,
                'tasks', tasks
            )
        END,
        schema_version = 2
        """
    )
    op.alter_column(
        "external_channel_works",
        "schema_version",
        server_default="2",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        UPDATE external_channel_works AS work
        SET tasks = coalesce(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'id', task.item ->> 'id',
                        'title', task.item ->> 'title',
                        'status', CASE
                            WHEN task.item ->> 'status' = 'failed' THEN 'pending'
                            ELSE task.item ->> 'status'
                        END
                    )
                    ORDER BY task.ordinality
                )
                FROM jsonb_array_elements(work.tasks)
                    WITH ORDINALITY AS task(item, ordinality)
            ),
            '[]'::jsonb
        )
        """
    )
    op.execute(
        """
        UPDATE external_channel_works
        SET desired_progress_payload = CASE
            WHEN desired_progress_payload IS NULL THEN NULL
            WHEN desired_progress_payload ->> 'state' = 'checking'
            THEN jsonb_build_object('state', 'checking', 'tasks', '[]'::jsonb)
            ELSE jsonb_build_object(
                'state', 'working',
                'tasks', tasks
            )
        END,
        schema_version = 1
        """
    )
    op.alter_column(
        "external_channel_works",
        "schema_version",
        server_default="1",
    )
    op.drop_column("external_channel_works", "title")
