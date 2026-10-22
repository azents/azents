"""Make existing Google operation selections explicit without changing grants.

Run with API/Workers drained. Pending setups require AZ_CREDENTIAL_ENCRYPTION_KEY
from the same deployment. All transformations are transactional; diagnostics
contain row identifiers only. Current credential ciphertext is never decoded or
changed. The frozen catalog covers every formerly exposed service operation,
independently of requested scopes and current grant evidence.
"""

import json
from typing import Literal, Sequence

import sqlalchemy as sa
from alembic import context, op
from cryptography.fernet import Fernet, InvalidToken
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f512e037a843"
down_revision: str | Sequence[str] | None = "d1142f351e96"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

Service = Literal["calendar", "drive", "gmail"]
_GROUPS = {
    "calendar": (
        "calendar_read",
        "calendar_availability",
        "calendar_events",
        "calendar_status",
        "calendar_create",
    ),
    "drive": ("drive_read", "drive_files", "drive_sharing", "drive_ownership"),
    "gmail": (
        "gmail_read",
        "gmail_labels",
        "gmail_drafts",
        "gmail_send",
        "gmail_organize",
        "gmail_filters",
    ),
}


class _EncryptionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AZ_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    credential_encryption_key: SecretStr


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    services: list[Service]
    oauth_request_scopes: list[str]
    timeout: float = Field(gt=0, le=300, allow_inf_nan=False)


class _Final(_Config):
    name: str | None
    slug: str | None
    description: str | None
    prompt: str | None
    enabled: bool
    always_expose_tools: bool


class _Target(_Config):
    toolkit_id: str
    connection_id: str | None
    client_id: str | None
    subject: str | None
    granted_scopes: list[str] | None
    status: Literal["connected", "reconnect_required"] | None


class _Setup(_Config):
    client_id: str
    effective_generation: str
    redirect_uri: str
    state_nonce: str
    oidc_nonce: str
    code_verifier: str
    target: _Target | None


_FINAL = TypeAdapter(_Final | _Config)


def _selection(config: _Config) -> dict[str, object]:
    return {
        **config.model_dump(mode="json"),
        "tool_groups": sorted(
            {group for service in config.services for group in _GROUPS[service]}
        ),
    }


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "Google tool group migration requires an online transaction."
        )
    connection = op.get_bind()
    # Drained writers and table locks keep setup target snapshots consistent.
    connection.execute(
        sa.text(
            "LOCK TABLE toolkit_configs, google_oauth_attempts "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    toolkits = sa.table(
        "toolkit_configs",
        sa.column("id", sa.String()),
        sa.column("toolkit_type", sa.String()),
        sa.column("config", JSONB()),
    )
    attempts = sa.table(
        "google_oauth_attempts",
        sa.column("id", sa.String()),
        sa.column("encrypted_setup", sa.Text()),
        sa.column("final_settings", JSONB()),
    )
    for row in connection.execute(
        sa.select(toolkits.c.id, toolkits.c.config).where(
            toolkits.c.toolkit_type == "google"
        )
    ).mappings():
        try:
            config = _Config.model_validate(row["config"])
        except ValidationError:
            raise ValueError(
                f"Invalid Google configuration: toolkit={row['id']}"
            ) from None
        connection.execute(
            toolkits.update()
            .where(toolkits.c.id == row["id"])
            .values(config=_selection(config))
        )
    cipher: Fernet | None = None
    for row in connection.execute(sa.select(attempts)).mappings():
        if row["final_settings"] is not None:
            try:
                final = _FINAL.validate_python(row["final_settings"])
            except ValidationError:
                raise ValueError(
                    f"Invalid Google publication: attempt={row['id']}"
                ) from None
            connection.execute(
                attempts.update()
                .where(attempts.c.id == row["id"])
                .values(final_settings=_selection(final))
            )
        if row["encrypted_setup"] is not None:
            if cipher is None:
                try:
                    cipher = Fernet(
                        _EncryptionSettings().credential_encryption_key.get_secret_value()
                    )
                except ValidationError, ValueError:
                    raise ValueError(
                        "Google setup migration requires the deployment encryption key."
                    ) from None
            try:
                setup = _Setup.model_validate_json(
                    cipher.decrypt(row["encrypted_setup"].encode())
                )
            except InvalidToken, ValidationError, UnicodeError, ValueError:
                raise ValueError(f"Invalid Google setup: attempt={row['id']}") from None
            updated = _selection(setup)
            if setup.target is not None:
                updated["target"] = _selection(setup.target)
            encrypted = cipher.encrypt(json.dumps(updated).encode()).decode()
            connection.execute(
                attempts.update()
                .where(attempts.c.id == row["id"])
                .values(encrypted_setup=encrypted)
            )


def downgrade() -> None:
    raise RuntimeError(
        "Google selection migration is irreversible; restore the checkpoint. "
        "Removing selections "
        "could expand Google access."
    )
