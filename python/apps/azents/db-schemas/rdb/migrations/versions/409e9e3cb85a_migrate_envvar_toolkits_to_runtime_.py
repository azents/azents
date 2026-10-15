"""Move allowlisted envvar Toolkit secrets and access into Runtime settings.

Run online with API/Workers drained and AZ_CREDENTIAL_ENCRYPTION_KEY configured
with the same Fernet key used by the application. Conflicting targets and nonempty
disabled Toolkits require explicit operator resolution before retrying. Errors
contain identifiers only. This cutover cannot reconstruct deleted Toolkit metadata.
"""

import json
import re
from typing import Sequence

import sqlalchemy as sa
from alembic import context, op
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, RootModel, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

revision: str = "409e9e3cb85a"
down_revision: str | Sequence[str] | None = "615047857119"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _EncryptionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AZ_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    credential_encryption_key: SecretStr


class _Entry(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    name: str


class _Config(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    entries: list[_Entry] = Field(default_factory=list)


class _Secrets(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    values: dict[str, str] = Field(default_factory=dict)


class _Values(RootModel[dict[str, str]]):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)


class _Toolkit(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    id: str
    workspace_id: str
    owner_agent_id: str | None
    config: _Config
    encrypted_credentials: str | None
    enabled: bool


def _validate(values: dict[str, str]) -> None:
    """Freeze the destination limits without exposing invalid persisted input."""
    if len(values) > 50:
        raise RuntimeError("Envvar cutover exceeds the 50-variable destination limit.")
    size = 0
    for name, value in values.items():
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name) or len(name.encode()) > 64:
            raise RuntimeError("Envvar cutover contains an invalid variable name.")
        try:
            value_size = len(value.encode())
        except UnicodeEncodeError:
            raise RuntimeError(
                "Envvar cutover contains an invalid variable value."
            ) from None
        if "\0" in value or value_size > 4096:
            raise RuntimeError("Envvar cutover contains an invalid variable value.")
        size += len(name.encode()) + value_size
    if size > 100 * 1024:
        raise RuntimeError("Envvar cutover exceeds the destination payload limit.")


def _merge(target: dict[str, str], source: dict[str, str], identity: str) -> None:
    for name, value in source.items():
        if name in target and target[name] != value:
            raise RuntimeError(f"Envvar cutover has conflicting values for {identity}.")
        target[name] = value
    _validate(target)


def _decrypt(cipher: Fernet, ciphertext: str) -> str:
    try:
        return cipher.decrypt(ciphertext.encode()).decode()
    except InvalidToken, UnicodeError, ValueError:
        raise RuntimeError(
            "Envvar cutover cannot decrypt persisted credentials."
        ) from None


def upgrade() -> None:
    """Migrate atomically, leaving every source intact on any blocker."""
    if context.is_offline_mode():
        raise RuntimeError(
            "Envvar data cutover requires an online database connection."
        )
    connection = op.get_bind()
    # Serialize source membership and target writes for the whole cutover.
    connection.execute(
        sa.text(
            "LOCK TABLE workspaces, agents, toolkit_configs, agent_toolkits, "
            "workspace_environment_variables, agent_workspace_environment_selections "
            "IN EXCLUSIVE MODE"
        )
    )
    rows = (
        connection.execute(
            sa.text(
                "SELECT id, workspace_id, owner_agent_id, config, "
                "encrypted_credentials, enabled "
                "FROM toolkit_configs WHERE toolkit_type = 'envvar' ORDER BY id"
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return
    try:
        sources = [_Toolkit.model_validate(dict(row)) for row in rows]
        settings = _EncryptionSettings()
        cipher = Fernet(settings.credential_encryption_key.get_secret_value().encode())
    except ValidationError, ValueError:
        raise RuntimeError(
            "Envvar cutover requires valid config and the application encryption key."
        ) from None

    local: dict[str, dict[str, str]] = {}
    shared: dict[str, dict[str, str]] = {}
    selections: set[tuple[str, str, str]] = set()
    for toolkit in sources:
        try:
            credentials = (
                _Secrets.model_validate_json(
                    _decrypt(cipher, toolkit.encrypted_credentials)
                ).values
                if toolkit.encrypted_credentials is not None
                else {}
            )
        except ValidationError:
            raise RuntimeError(
                f"Envvar cutover has invalid credentials for Toolkit {toolkit.id}."
            ) from None
        names = {entry.name for entry in toolkit.config.entries}
        values = {name: value for name, value in credentials.items() if name in names}
        _validate(values)
        if not toolkit.enabled and values:
            raise RuntimeError(
                f"Envvar cutover requires resolution of disabled Toolkit {toolkit.id}."
            )
        if toolkit.owner_agent_id is not None:
            owner_workspace = connection.scalar(
                sa.text("SELECT workspace_id FROM agents WHERE id = :id"),
                {"id": toolkit.owner_agent_id},
            )
            if owner_workspace != toolkit.workspace_id:
                raise RuntimeError(
                    f"Envvar cutover has invalid ownership for Toolkit {toolkit.id}."
                )
            _merge(
                local.setdefault(toolkit.owner_agent_id, {}),
                values,
                f"Agent {toolkit.owner_agent_id}",
            )
        else:
            _merge(
                shared.setdefault(toolkit.workspace_id, {}),
                values,
                f"Workspace {toolkit.workspace_id}",
            )
            attachments = connection.execute(
                sa.text(
                    "SELECT a.id, a.workspace_id FROM agent_toolkits t "
                    "JOIN agents a ON a.id = t.agent_id WHERE t.toolkit_id = :id"
                ),
                {"id": toolkit.id},
            )
            for agent_id, workspace_id in attachments:
                if workspace_id != toolkit.workspace_id:
                    raise RuntimeError(
                        "Envvar cutover has a cross-Workspace attachment "
                        f"for Toolkit {toolkit.id}."
                    )
                selections.update((agent_id, workspace_id, name) for name in values)

    for agent_id, values in local.items():
        encrypted = connection.scalar(
            sa.text("SELECT encrypted_runtime_environment FROM agents WHERE id = :id"),
            {"id": agent_id},
        )
        try:
            existing = (
                _Values.model_validate_json(_decrypt(cipher, encrypted)).root
                if encrypted is not None
                else {}
            )
        except ValidationError:
            raise RuntimeError(
                f"Envvar cutover has invalid Runtime settings for Agent {agent_id}."
            ) from None
        # Existing selected Workspace values preceded Toolkit values before cutover.
        selected = connection.execute(
            sa.text(
                "SELECT v.name, v.encrypted_value "
                "FROM workspace_environment_variables v "
                "JOIN agent_workspace_environment_selections s ON s.variable_id = v.id "
                "WHERE s.agent_id = :id"
            ),
            {"id": agent_id},
        )
        for name, ciphertext in selected:
            if (
                name in values
                and name not in existing
                and values[name] != _decrypt(cipher, ciphertext)
            ):
                raise RuntimeError(
                    "Envvar cutover would change existing Workspace precedence "
                    f"for Agent {agent_id}."
                )
        _merge(existing, values, f"Agent {agent_id}")
        if existing:
            connection.execute(
                sa.text(
                    "UPDATE agents SET encrypted_runtime_environment = :value "
                    "WHERE id = :id"
                ),
                {
                    "id": agent_id,
                    "value": cipher.encrypt(json.dumps(existing).encode()).decode(),
                },
            )

    variable_ids: dict[tuple[str, str], str] = {}
    for workspace_id, values in shared.items():
        targets = connection.execute(
            sa.text(
                "SELECT id, name, encrypted_value "
                "FROM workspace_environment_variables WHERE workspace_id = :id"
            ),
            {"id": workspace_id},
        ).all()
        existing = {
            name: _decrypt(cipher, ciphertext) for _, name, ciphertext in targets
        }
        _merge(existing, values, f"Workspace {workspace_id}")
        target_ids = {name: identity for identity, name, _ in targets}
        for name, value in values.items():
            identity = target_ids.get(name)
            if identity is None:
                from uuid import uuid4  # noqa: PLC0415

                identity = uuid4().hex
                connection.execute(
                    sa.text(
                        "INSERT INTO workspace_environment_variables "
                        "(id, workspace_id, name, encrypted_value) "
                        "VALUES (:id, :workspace, :name, :value)"
                    ),
                    {
                        "id": identity,
                        "workspace": workspace_id,
                        "name": name,
                        "value": cipher.encrypt(value.encode()).decode(),
                    },
                )
            variable_ids[workspace_id, name] = identity
    for agent_id, workspace_id, name in sorted(selections):
        connection.execute(
            sa.text(
                "INSERT INTO agent_workspace_environment_selections "
                "(agent_id, variable_id) "
                "VALUES (:agent, :variable) ON CONFLICT DO NOTHING"
            ),
            {"agent": agent_id, "variable": variable_ids[workspace_id, name]},
        )
    # FK cascades remove attachments; namespace reservations become consumed tombstones.
    connection.execute(
        sa.text("DELETE FROM toolkit_configs WHERE toolkit_type = 'envvar'")
    )


def downgrade() -> None:
    """Refuse to invent lost Toolkit identities, state, metadata or memberships."""
    raise RuntimeError(
        "Envvar Toolkit cutover is irreversible; restore a pre-cutover database backup."
    )
