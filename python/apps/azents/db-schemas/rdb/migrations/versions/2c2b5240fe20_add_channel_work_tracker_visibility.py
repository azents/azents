"""Add Channel Work Tracker visibility."""

import json
from collections.abc import Sequence
from datetime import datetime
from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import op

revision: str = "2c2b5240fe20"
down_revision: str | Sequence[str] | None = "ff79e1119f1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Grandfather existing Channel Work cycles as Tracker-visible."""
    _validate_channel_work_state_shape(
        row_schema_version=1,
        payload_schema_version=1,
        tracker_visibility_required=False,
    )
    op.execute(
        sa.text(
            """
            UPDATE toolkit_states
            SET
                state_json = jsonb_set(
                    jsonb_set(
                        state_json,
                        '{schema_version}',
                        '2'::jsonb,
                        false
                    ),
                    '{tracker_visibility}',
                    '"visible"'::jsonb,
                    true
                ),
                schema_version = 2,
                version = version + 1,
                updated_at = now()
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
              AND schema_version = 1
            """
        )
    )


def downgrade() -> None:
    """Restore the pre-visibility Channel Work payload shape."""
    _validate_channel_work_state_shape(
        row_schema_version=2,
        payload_schema_version=2,
        tracker_visibility_required=True,
    )
    op.execute(
        sa.text(
            """
            UPDATE toolkit_states
            SET
                state_json = jsonb_set(
                    state_json - 'tracker_visibility',
                    '{schema_version}',
                    '1'::jsonb,
                    false
                ),
                schema_version = 1,
                version = version + 1,
                updated_at = now()
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
              AND schema_version = 2
            """
        )
    )


def _validate_channel_work_state_shape(
    *,
    row_schema_version: int,
    payload_schema_version: int,
    tracker_visibility_required: bool,
) -> None:
    """Fail before mutation unless every targeted row decodes after transition."""
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT id, state_name, state_json
            FROM toolkit_states
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
              AND schema_version = :row_schema_version
            FOR UPDATE
            """
            ),
            {"row_schema_version": row_schema_version},
        )
        .mappings()
    )
    for row in rows:
        try:
            _validate_work_state_payload(
                row["state_json"],
                state_name=str(row["state_name"]),
                schema_version=payload_schema_version,
                tracker_visibility_required=tracker_visibility_required,
            )
        except ValueError as error:
            raise RuntimeError(
                "Channel Work Toolkit State schema payload is malformed"
            ) from error


def _validate_work_state_payload(
    value: object,
    *,
    state_name: str,
    schema_version: int,
    tracker_visibility_required: bool,
) -> None:
    """Validate one frozen Channel Work payload without app-model imports."""
    state = _object(value, "Channel Work state")
    required_keys = {
        "schema_version",
        "binding_id",
        "work_cycle_id",
        "status",
        "title",
        "tasks",
        "state_revision",
        "desired_progress_revision",
        "desired_progress",
        "finished_at",
        "projection_parts",
    }
    if tracker_visibility_required:
        required_keys.add("tracker_visibility")
    _exact_keys(state, required_keys, "Channel Work state")
    if _integer(state["schema_version"], "schema_version") != schema_version:
        raise ValueError("Channel Work state schema version is inconsistent.")
    binding_id = _string(state["binding_id"], "binding_id", minimum=1)
    if not state_name.startswith("channel_work:"):
        raise ValueError("Channel Work state name is invalid.")
    if binding_id != state_name.removeprefix("channel_work:"):
        raise ValueError("Channel Work binding identity is inconsistent.")
    _string(state["work_cycle_id"], "work_cycle_id", minimum=1)
    status = _closed_string(state["status"], {"active", "finished"}, "status")
    _nullable_string(state["title"], "title")
    _integer(state["state_revision"], "state_revision", minimum=1)
    _integer(
        state["desired_progress_revision"],
        "desired_progress_revision",
        minimum=0,
    )
    for task in _array(state["tasks"], "tasks"):
        _validate_task(task, "tasks[]")
    _validate_finished_at(state["finished_at"], status)
    desired_progress = state["desired_progress"]
    if desired_progress is not None:
        _validate_desired_progress(desired_progress)
    _validate_projection_parts(state["projection_parts"])
    if tracker_visibility_required:
        _closed_string(
            state["tracker_visibility"],
            {"hidden", "visible"},
            "tracker_visibility",
        )


def _validate_task(value: object, context: str) -> dict[str, object]:
    """Validate and normalize one frozen provider-neutral task."""
    task = _object(value, context)
    _exact_keys(
        task,
        {"id", "title", "status", "details", "output", "sources"},
        context,
    )
    task_id = _string(task["id"], f"{context}.id", minimum=1, maximum=80, trim=True)
    title = _string(
        task["title"],
        f"{context}.title",
        minimum=1,
        maximum=500,
        trim=True,
    )
    status = _closed_string(
        task["status"],
        {"pending", "in_progress", "completed", "failed"},
        f"{context}.status",
        trim=True,
    )
    details = _nullable_string(
        task["details"],
        f"{context}.details",
        minimum=1,
        maximum=3_000,
        trim=True,
    )
    output = _nullable_string(
        task["output"],
        f"{context}.output",
        minimum=1,
        maximum=3_000,
        trim=True,
    )
    sources = [
        _validate_source(source, f"{context}.sources[]")
        for source in _array(task["sources"], f"{context}.sources", maximum=20)
    ]
    return {
        "id": task_id,
        "title": title,
        "status": status,
        "details": details,
        "output": output,
        "sources": sources,
    }


def _validate_source(value: object, context: str) -> dict[str, object]:
    """Validate and normalize one frozen HTTP(S) source."""
    source = _object(value, context)
    _exact_keys(source, {"url", "label"}, context)
    url = _string(source["url"], f"{context}.url", minimum=1, maximum=2_048, trim=True)
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{context}.url is invalid.")
    return {
        "url": url,
        "label": _string(
            source["label"],
            f"{context}.label",
            minimum=1,
            maximum=500,
            trim=True,
        ),
    }


def _validate_desired_progress(value: object) -> None:
    """Validate the complete normalized desired-progress snapshot."""
    progress = _object(value, "desired_progress")
    _exact_keys(
        progress,
        {"schema_version", "state", "title", "tasks"},
        "desired_progress",
    )
    if _integer(progress["schema_version"], "desired_progress.schema_version") != 2:
        raise ValueError("desired_progress schema version is invalid.")
    state = _closed_string(
        progress["state"],
        {"checking", "working"},
        "desired_progress.state",
        trim=True,
    )
    title = _nullable_string(
        progress["title"],
        "desired_progress.title",
        minimum=1,
        maximum=500,
        trim=True,
    )
    tasks = [
        _validate_task(task, "desired_progress.tasks[]")
        for task in _array(
            progress["tasks"],
            "desired_progress.tasks",
            maximum=49,
        )
    ]
    if state == "checking" and (title is not None or tasks):
        raise ValueError("Checking progress is inconsistent.")
    if state == "working" and (title is None or not tasks):
        raise ValueError("Working progress is inconsistent.")
    task_ids = [str(task["id"]) for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Desired progress task IDs are not unique.")
    normalized = {
        "schema_version": 2,
        "state": state,
        "title": title,
        "tasks": tasks,
    }
    if (
        len(
            json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        )
        > 64 * 1024
    ):
        raise ValueError("Desired progress exceeds the supported size.")


def _validate_projection_parts(value: object) -> None:
    """Validate deterministic ordered provider projection observations."""
    projection_parts = _array(value, "projection_parts")
    previous_ordinal = -1
    for part_value in projection_parts:
        part = _object(part_value, "projection_parts[]")
        _exact_keys(
            part,
            {
                "part_ordinal",
                "desired_progress_revision",
                "status",
                "provider_message_key",
            },
            "projection_parts[]",
        )
        ordinal = _integer(
            part["part_ordinal"],
            "projection_parts[].part_ordinal",
            minimum=0,
        )
        if ordinal <= previous_ordinal:
            raise ValueError("Projection parts are not strictly ordered.")
        previous_ordinal = ordinal
        _integer(
            part["desired_progress_revision"],
            "projection_parts[].desired_progress_revision",
            minimum=0,
        )
        _closed_string(
            part["status"],
            {"present", "failed", "unknown", "deleted"},
            "projection_parts[].status",
        )
        _nullable_string(
            part["provider_message_key"],
            "projection_parts[].provider_message_key",
        )


def _validate_finished_at(value: object, status: str) -> None:
    """Require an aware ISO timestamp exactly for finished Work."""
    if status == "active":
        if value is not None:
            raise ValueError("Active Work has a finished timestamp.")
        return
    timestamp = _string(value, "finished_at", minimum=1)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("finished_at is not ISO formatted.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("finished_at is not timezone aware.")


def _object(value: object, context: str) -> dict[str, object]:
    """Return one JSON object or reject another JSON type."""
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object.")
    return value


def _array(
    value: object,
    context: str,
    *,
    maximum: int | None = None,
) -> list[object]:
    """Return one JSON array with an optional cardinality limit."""
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array.")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{context} exceeds its maximum length.")
    return value


def _exact_keys(
    value: dict[str, object],
    expected: set[str],
    context: str,
) -> None:
    """Require one JSON object to contain exactly its model fields."""
    if set(value) != expected:
        raise ValueError(f"{context} fields are inconsistent.")


def _integer(value: object, context: str, *, minimum: int | None = None) -> int:
    """Require one non-boolean JSON integer with an optional minimum."""
    if type(value) is not int:
        raise ValueError(f"{context} must be an integer.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{context} is below its minimum.")
    return value


def _string(
    value: object,
    context: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    trim: bool = False,
) -> str:
    """Require one JSON string and apply model-equivalent trimming when requested."""
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string.")
    normalized = value.strip() if trim else value
    if minimum is not None and len(normalized) < minimum:
        raise ValueError(f"{context} is below its minimum length.")
    if maximum is not None and len(normalized) > maximum:
        raise ValueError(f"{context} exceeds its maximum length.")
    return normalized


def _nullable_string(
    value: object,
    context: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    trim: bool = False,
) -> str | None:
    """Require a JSON string or null with model-equivalent string validation."""
    if value is None:
        return None
    return _string(
        value,
        context,
        minimum=minimum,
        maximum=maximum,
        trim=trim,
    )


def _closed_string(
    value: object,
    allowed: set[str],
    context: str,
    *,
    trim: bool = False,
) -> str:
    """Require one member of a closed string set."""
    normalized = _string(value, context, trim=trim)
    if normalized not in allowed:
        raise ValueError(f"{context} is unsupported.")
    return normalized
