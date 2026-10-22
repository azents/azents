"""One-time stopped Google Workspace data cutover.

Current encrypted grants and historical publication identities are deliberately
untouched. Rollback after commit requires the matching operator checkpoint.
The finite contracts below are frozen here, independent of application policy.
"""

import math
from collections import defaultdict
from typing import Literal

import sqlalchemy as sa
from alembic import op
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.dialects.postgresql import JSONB

revision = "d1142f351e96"
down_revision = "2944b0e66140"
branch_labels = None
depends_on = None

Service = Literal["calendar", "drive", "gmail"]
_PREFIX = "https://www.googleapis.com/auth/"
_LEGACY = {
    "calendar_read": (
        "calendar",
        ("calendar.events.readonly", "calendar.calendarlist.readonly"),
    ),
    "calendar_availability": (
        "calendar",
        ("calendar.events.freebusy", "calendar.calendarlist.readonly"),
    ),
    "calendar_edit": ("calendar", ("calendar.events",)),
    "drive_read": ("drive", ("drive.readonly",)),
    "drive_files": ("drive", ("drive.file",)),
    "gmail_read": ("gmail", ("gmail.readonly",)),
    "gmail_drafts": ("gmail", ("gmail.compose",)),
    "gmail_modify": ("gmail", ("gmail.modify",)),
}
_REQUEST_SCOPES = frozenset(
    _PREFIX + scope
    for scope in (
        "gmail.readonly",
        "gmail.modify",
        "gmail.compose",
        "gmail.send",
        "gmail.labels",
        "gmail.metadata",
        "gmail.settings.basic",
        "calendar",
        "calendar.readonly",
        "calendar.events",
        "calendar.events.readonly",
        "calendar.events.freebusy",
        "calendar.freebusy",
        "calendar.events.owned",
        "calendar.events.owned.readonly",
        "calendar.events.public.readonly",
        "calendar.app.created",
        "calendar.calendars",
        "calendar.calendarlist",
        "calendar.calendarlist.readonly",
        "drive",
        "drive.readonly",
        "drive.file",
        "drive.metadata",
        "drive.metadata.readonly",
    )
) | {"openid", "email", "https://mail.google.com/"}
_ENDPOINTS = {
    "calendar": "https://calendarmcp.googleapis.com/mcp/v1",
    "drive": "https://drivemcp.googleapis.com/mcp/v1",
    "gmail": "https://gmailmcp.googleapis.com/mcp/v1",
}
_METADATA = {"name", "slug", "description", "prompt", "enabled", "always_expose_tools"}


class CutoverError(ValueError):
    """Nonsecret migration diagnostic without row payloads or credentials."""


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    services: list[Service]
    oauth_request_scopes: list[str]
    timeout: float = Field(strict=True, gt=0, le=300, allow_inf_nan=False)


class _Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    name: str | None = Field(max_length=255)
    slug: str | None
    description: str | None
    prompt: str | None
    enabled: bool
    always_expose_tools: bool


def _transform(payload: object, *, published: bool) -> dict[str, object]:
    """Preflight one finite config; metadata is all-or-none for publication."""
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) for key in payload
    ):
        raise CutoverError("Invalid Google configuration for cutover.")
    data = dict(payload)
    metadata: dict[str, object] = {}
    if published and _METADATA.intersection(data):
        try:
            metadata = _Metadata.model_validate(
                {key: data.pop(key) for key in _METADATA if key in data}
            ).model_dump()
        except ValidationError:
            raise CutoverError(
                "Invalid published Google metadata for cutover."
            ) from None
    timeout = data.get("timeout", None if published else 30.0)
    if (
        type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or not 0 < timeout <= 300
    ):
        raise CutoverError("Invalid Google timeout for cutover.")
    if "tasks" in data:
        if (
            set(data) - {"tasks", "timeout", "security_risk_acknowledged"}
            or type(data.get("security_risk_acknowledged")) is not bool
        ):
            raise CutoverError("Invalid legacy Google configuration for cutover.")
        tasks = data["tasks"]
        if (
            not isinstance(tasks, list)
            or not tasks
            or any(not isinstance(task, str) or task not in _LEGACY for task in tasks)
        ):
            raise CutoverError("Invalid legacy Google task selection for cutover.")
        data = {
            "services": sorted({_LEGACY[task][0] for task in tasks}),
            "oauth_request_scopes": sorted(
                {"openid", "email"}
                | {_PREFIX + scope for task in tasks for scope in _LEGACY[task][1]}
            ),
            "timeout": timeout,
        }
    try:
        config = _Config.model_validate(data)
    except ValidationError:
        raise CutoverError("Invalid Google configuration for cutover.") from None
    if any(scope not in _REQUEST_SCOPES for scope in config.oauth_request_scopes):
        raise CutoverError("Invalid Google request scopes for cutover.")
    return {
        **metadata,
        "services": sorted(set(config.services)),
        "oauth_request_scopes": sorted(
            set(config.oauth_request_scopes) | {"openid", "email"}
        ),
        "timeout": config.timeout,
    }


class _Tool(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    raw_name: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    description: str
    input_schema: dict[str, object]
    server_url: str
    use_streamable_http: bool = False


class _Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    schema_version: Literal[1]
    loaded_at: str | None = None
    server_url: str | None = None
    tool_hash: str | None = None
    tools: list[_Tool] = Field(default_factory=list)


class _WorkingSet(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    schema_version: Literal[1]
    tool_names: list[str]


def _owner(row: sa.RowMapping, *, attempt: bool) -> None:
    kind = row["owner_kind"]
    agent = row["agent_id" if attempt else "owner_agent_id"]
    user = row["owner_user_id"]
    valid = bool(row["workspace_id"]) and (
        (kind == "workspace" and agent is None and user is None)
        or (kind == "agent" and bool(agent) and user is None)
        or (
            kind == "user"
            and agent is None
            and bool(user)
            and (not attempt or user == row["user_id"])
        )
    )
    if not valid:
        raise CutoverError("Invalid Google ownership for cutover.")


def upgrade() -> None:
    """Validate every targeted row before applying a DB-only atomic cutover."""
    connection = op.get_bind()
    # Operators must drain old processes first. These locks protect the finite
    # preflight/write interval, not old captured handlers after the transaction.
    connection.execute(
        sa.text(
            "LOCK TABLE toolkit_configs, google_oauth_attempts, toolkit_states, "
            "agent_toolkit_namespace_reservations IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    for invalid in (
        "SELECT 1 FROM google_oauth_connections c "
        "JOIN toolkit_configs t ON t.id=c.toolkit_id "
        "WHERE t.toolkit_type!='google' LIMIT 1",
        "SELECT 1 FROM toolkit_configs t JOIN agents a ON a.id=t.owner_agent_id "
        "WHERE t.toolkit_type='google' AND t.workspace_id!=a.workspace_id LIMIT 1",
        "SELECT 1 FROM google_oauth_attempts g JOIN agents a ON a.id=g.agent_id "
        "WHERE g.workspace_id!=a.workspace_id LIMIT 1",
        "SELECT 1 FROM agent_toolkit_namespace_reservations r "
        "JOIN toolkit_configs t ON t.id=r.toolkit_id "
        "JOIN agents a ON a.id=r.agent_id "
        "WHERE t.toolkit_type='google' AND "
        "(t.workspace_id!=a.workspace_id OR "
        "(t.owner_kind='agent' AND t.owner_agent_id!=r.agent_id)) LIMIT 1",
        "SELECT 1 FROM toolkit_states s "
        "JOIN agent_sessions c ON c.id=s.session_id "
        "JOIN agents a ON a.id=s.agent_id "
        "LEFT JOIN toolkit_configs t ON t.id=split_part(s.state_name,':',2) "
        "WHERE s.toolkit_namespace='mcp' AND s.state_name LIKE 'google:%' "
        "AND (s.agent_id IS DISTINCT FROM c.agent_id "
        "OR t.workspace_id!=a.workspace_id "
        "OR (t.owner_kind='agent' AND t.owner_agent_id!=s.agent_id)) LIMIT 1",
    ):
        if connection.scalar(sa.text(invalid)) is not None:
            raise CutoverError("Ambiguous Google ownership relationship for cutover.")
    configs = (
        connection.execute(
            sa.text("SELECT * FROM toolkit_configs WHERE toolkit_type='google'")
        )
        .mappings()
        .all()
    )
    config_updates: list[dict[str, object]] = []
    for row in configs:
        _owner(row, attempt=False)
        config_updates.append(
            {"id": row["id"], "payload": _transform(row["config"], published=False)}
        )
    attempts = (
        connection.execute(sa.text("SELECT * FROM google_oauth_attempts"))
        .mappings()
        .all()
    )
    published_updates: list[dict[str, object]] = []
    for row in attempts:
        _owner(row, attempt=True)
        if row["status"] != "published":
            # Retired encrypted setup/candidate and incomplete final state are
            # scrubbed without decoding them, including previously terminal rows.
            continue
        if not all(
            isinstance(row[key], str) and row[key].strip()
            for key in ("published_toolkit_id", "published_connection_id")
        ):
            raise CutoverError("Incomplete published Google outcome identity.")
        published_updates.append(
            {
                "id": row["id"],
                "payload": _transform(row["final_settings"], published=True),
            }
        )

    states = (
        connection.execute(
            sa.text(
                "SELECT s.*, c.agent_id AS session_agent_id FROM toolkit_states s "
                "JOIN agent_sessions c ON c.id=s.session_id WHERE "
                "(s.toolkit_namespace='mcp' AND s.state_name LIKE 'google:%') OR "
                "(s.toolkit_namespace='tool_search' AND s.state_name='working_set')"
            )
        )
        .mappings()
        .all()
    )
    reservations = (
        connection.execute(
            sa.text(
                "SELECT agent_id, toolkit_id, namespace "
                "FROM agent_toolkit_namespace_reservations "
                "WHERE toolkit_id IS NOT NULL"
            )
        )
        .mappings()
        .all()
    )
    namespaces: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in reservations:
        namespaces[(row["agent_id"], row["toolkit_id"])].add(row["namespace"])
    google_ids = {row["id"] for row in configs}
    google_prefixes: dict[str, set[str]] = defaultdict(set)
    for row in reservations:
        if row["toolkit_id"] in google_ids:
            google_prefixes[row["agent_id"]].update(
                f"{row['namespace']}__{service}_" for service in _ENDPOINTS
            )
    other_ids = set(
        connection.execute(
            sa.text("SELECT id FROM toolkit_configs WHERE toolkit_type!='google'")
        ).scalars()
    )
    removals: dict[tuple[str, str], set[str]] = defaultdict(set)
    uncertain_suffixes: dict[tuple[str, str], set[str]] = defaultdict(set)
    snapshot_ids: list[str] = []
    for row in states:
        if row["toolkit_namespace"] != "mcp":
            continue
        identity = row["state_name"].split(":")
        if (
            len(identity) != 3
            or not identity[1]
            or identity[2] not in _ENDPOINTS
            or identity[1] in other_ids
            or row["schema_version"] != 1
        ):
            raise CutoverError("Ambiguous Google snapshot ownership for cutover.")
        toolkit_id, service = identity[1:]
        try:
            snapshot = _Snapshot.model_validate(row["state_json"])
        except ValidationError:
            raise CutoverError("Invalid Google snapshot for cutover.") from None
        if snapshot.server_url not in (None, _ENDPOINTS[service]) or any(
            tool.server_url != _ENDPOINTS[service] or tool.raw_name != tool.model_name
            for tool in snapshot.tools
        ):
            raise CutoverError("Ambiguous Google snapshot ownership for cutover.")
        key = (row["agent_id"], row["session_id"])
        allocated = namespaces.get((row["agent_id"], toolkit_id), set())
        for tool in snapshot.tools:
            suffix = f"{service}_{tool.raw_name}"
            if toolkit_id not in google_ids or not allocated:
                uncertain_suffixes[key].add("__" + suffix)
            removals[key].update(f"{namespace}__{suffix}" for namespace in allocated)
        snapshot_ids.append(row["id"])
    working_updates: list[dict[str, object]] = []
    for row in states:
        key = (row["agent_id"], row["session_id"])
        prefixes = tuple(google_prefixes[row["agent_id"]])
        if (
            row["toolkit_namespace"] != "tool_search"
            or key not in removals
            and key not in uncertain_suffixes
            and not prefixes
        ):
            continue
        if row["agent_id"] != row["session_agent_id"]:
            raise CutoverError("Ambiguous Google ownership relationship for cutover.")
        try:
            working = _WorkingSet.model_validate(row["state_json"])
        except ValidationError:
            raise CutoverError(
                "Invalid Google-associated working set for cutover."
            ) from None
        if row["schema_version"] != 1 or any(
            name.endswith(suffix)
            for name in working.tool_names
            for suffix in uncertain_suffixes[key]
            if not name.startswith(prefixes)
        ):
            raise CutoverError("Ambiguous Google deferred tool ownership for cutover.")
        kept = [
            name
            for name in working.tool_names
            if name not in removals[key] and not name.startswith(prefixes)
        ]
        if kept != working.tool_names:
            working_updates.append(
                {"id": row["id"], "payload": {"schema_version": 1, "tool_names": kept}}
            )

    # All preflight is complete. No current grant, Toolkit identity/metadata,
    # historical outcome ID, event or message is updated below.
    for table, column, updates in (
        ("toolkit_configs", "config", config_updates),
        ("google_oauth_attempts", "final_settings", published_updates),
        ("toolkit_states", "state_json", working_updates),
    ):
        statement = sa.text(
            f"UPDATE {table} SET {column}=:payload WHERE id=:id"
        ).bindparams(sa.bindparam("payload", type_=JSONB))
        for update in updates:
            connection.execute(statement, update)
    connection.execute(
        sa.text(
            "UPDATE google_oauth_attempts SET status='cancelled', "
            "encrypted_setup=NULL, encrypted_candidate=NULL, final_settings=NULL "
            "WHERE status!='published'"
        )
    )
    # Published rows retain only their historical result, never staged credentials.
    connection.execute(
        sa.text(
            "UPDATE google_oauth_attempts SET encrypted_setup=NULL, "
            "encrypted_candidate=NULL WHERE status='published'"
        )
    )
    for state_id in snapshot_ids:
        connection.execute(
            sa.text("DELETE FROM toolkit_states WHERE id=:id"), {"id": state_id}
        )


def downgrade() -> None:
    """Retired attempts and schemas require a matching operator checkpoint."""
    raise RuntimeError(
        "Google direct cutover is irreversible; restore the matching checkpoint."
    )
