"""split tool_call+result into function_call_item rows

Best-effort data migration for Phase 4 FunctionCallItem restructuring.
- DurableToolCall (multi tool_calls) → N FunctionCallItem rows (1 per call)
- DurableToolResult → merged into FunctionCallItem.output (content/attachments)
- Server-side tool calls/results → deleted
- Orphan tool results → deleted

Revision ID: df2a19fc785c
Revises: bf99f7b4b6cc
Create Date: 2026-03-18 00:10:00.000000

"""

import json
import logging
from typing import Any, Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "df2a19fc785c"
down_revision: str | Sequence[str] | None = "bf99f7b4b6cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)


def _parse_tool_calls(raw: object) -> list[dict[str, Any]] | None:
    """Safely parse the tool_calls column. Return None when it is not an array."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError, TypeError:
            pass
    return None


def upgrade() -> None:
    """Convert legacy DurableToolCall and DurableToolResult.

    The target structure is FunctionCallItem.
    """
    conn = op.get_bind()

    # Fetch every assistant row with tool_calls
    assistant_rows = conn.execute(
        sa.text("""
            SELECT id, session_id, tool_calls, content, model,
                   raw_output, attachments
            FROM events
            WHERE role = 'assistant'
              AND tool_calls IS NOT NULL
            ORDER BY id
        """)
    ).fetchall()

    # Fetch every tool result row for matching by tool_call_id
    tool_rows = conn.execute(
        sa.text("""
            SELECT id, session_id, tool_call_id, content, attachments
            FROM events
            WHERE role = 'tool'
              AND tool_call_id IS NOT NULL
        """)
    ).fetchall()

    # Map tool results by (session_id, tool_call_id) to row
    result_map: dict[tuple[str, str], Any] = {}
    for tr in tool_rows:
        key = (tr.session_id, tr.tool_call_id)
        result_map[key] = tr

    ids_to_delete: list[str] = []
    rows_to_insert: list[dict[str, Any]] = []

    for row in assistant_rows:
        tcs = _parse_tool_calls(row.tool_calls)
        if tcs is None:
            # Non-array scalar: skip without touching it
            continue

        raw_output = row.raw_output
        # Detect server tool calls where raw_output.type != 'function_call'
        if raw_output is not None and isinstance(raw_output, dict):
            raw_type = raw_output.get("type")
            if raw_type is not None and raw_type != "function_call":
                # Server tool call: delete
                ids_to_delete.append(row.id)
                # Delete the corresponding tool result as well
                for tc in tcs:
                    tc_id = tc.get("id", "")
                    key = (row.session_id, tc_id)
                    if key in result_map:
                        ids_to_delete.append(result_map[key].id)
                        del result_map[key]
                continue

        if len(tcs) == 1:
            # Single tool call: merge only the result
            tc = tcs[0]
            tc_id = tc.get("id", "")
            key = (row.session_id, tc_id)
            tr = result_map.pop(key, None)
            if tr is not None and row.content is None:
                # Merge content and attachments
                conn.execute(
                    sa.text("""
                        UPDATE events
                        SET content = :content,
                            attachments = :attachments
                        WHERE id = :id
                    """),
                    {
                        "id": row.id,
                        "content": tr.content,
                        "attachments": (
                            json.dumps(tr.attachments) if tr.attachments else None
                        ),
                    },
                )
                ids_to_delete.append(tr.id)
        else:
            # Multi tool call: split into N rows
            ids_to_delete.append(row.id)
            for tc in tcs:
                tc_id = tc.get("id", "")
                key = (row.session_id, tc_id)
                tr = result_map.pop(key, None)

                insert = {
                    "session_id": row.session_id,
                    "role": "assistant",
                    "tool_calls": json.dumps([tc]),
                    "content": tr.content if tr else None,
                    "attachments": (
                        json.dumps(tr.attachments) if tr and tr.attachments else None
                    ),
                    "model": row.model,
                    "raw_output": (json.dumps(raw_output) if raw_output else None),
                }
                rows_to_insert.append(insert)
                if tr is not None:
                    ids_to_delete.append(tr.id)

    # Delete all remaining orphan tool results
    for tr in result_map.values():
        ids_to_delete.append(tr.id)

    # Bulk delete
    if ids_to_delete:
        # Delete in chunks to avoid IN-clause limits
        chunk_size = 500
        for i in range(0, len(ids_to_delete), chunk_size):
            chunk = ids_to_delete[i : i + chunk_size]
            conn.execute(
                sa.text("DELETE FROM events WHERE id = ANY(:ids)"),
                {"ids": chunk},
            )

    # Bulk insert
    for row_data in rows_to_insert:
        conn.execute(
            sa.text("""
                INSERT INTO events
                    (session_id, role, tool_calls, content,
                     attachments, model, raw_output)
                VALUES
                    (:session_id, :role,
                     :tool_calls::jsonb, :content,
                     :attachments::jsonb, :model,
                     :raw_output::jsonb)
            """),
            row_data,
        )

    logger.info(
        "Migration complete",
        extra={
            "deleted": len(ids_to_delete),
            "inserted": len(rows_to_insert),
        },
    )


def downgrade() -> None:
    """Downgrade is unsupported because this is a best-effort migration."""
    pass
