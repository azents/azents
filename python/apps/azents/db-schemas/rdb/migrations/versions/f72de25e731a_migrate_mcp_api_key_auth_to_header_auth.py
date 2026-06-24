"""migrate mcp api_key auth to header auth

Generalize the MCP Toolkit api_key authentication type to header authentication.
- config JSONB: auth_type "api_key" → "header"
- encrypted_credentials:
  { "type": "api_key", "api_key": "..." } → { "type": "header", "value": "..." }

Revision ID: f72de25e731a
Revises: 682d36da7476
Create Date: 2026-03-07 10:35:41.303430

"""

import json
import os
from typing import Sequence

from alembic import op
from cryptography.fernet import Fernet
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "f72de25e731a"
down_revision: str | Sequence[str] | None = "682d36da7476"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Convert the api_key authentication type to header."""
    conn = op.get_bind()

    # 1. Change auth_type from "api_key" to "header" in config JSONB rows
    conn.execute(
        text("""
            UPDATE toolkits
            SET config = jsonb_set(config, '{auth_type}', '"header"')
            WHERE tool_slug = 'mcp'
              AND config ->> 'auth_type' = 'api_key'
        """)
    )

    # 2. Convert encrypted_credentials through Fernet decrypt,
    # JSON conversion, and re-encrypt
    encryption_key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    if encryption_key is None:
        # Skip encrypted_credentials conversion when the key is absent
        # Only config.auth_type is converted in that case
        return

    fernet = Fernet(encryption_key.encode())

    rows = conn.execute(
        text("""
            SELECT id, encrypted_credentials
            FROM toolkits
            WHERE tool_slug = 'mcp'
              AND encrypted_credentials IS NOT NULL
        """)
    ).fetchall()

    for row in rows:
        toolkit_id = row[0]
        encrypted = row[1]

        plaintext = fernet.decrypt(encrypted.encode()).decode()
        creds = json.loads(plaintext)

        if creds.get("type") != "api_key":
            continue

        # { "type": "api_key", "api_key": "..." } → { "type": "header", "value": "..." }
        new_creds = {"type": "header", "value": creds.get("api_key", "")}
        new_encrypted = fernet.encrypt(json.dumps(new_creds).encode()).decode()

        conn.execute(
            text("UPDATE toolkits SET encrypted_credentials = :creds WHERE id = :id"),
            {"creds": new_encrypted, "id": toolkit_id},
        )


def downgrade() -> None:
    """Restore the header authentication type to api_key."""
    conn = op.get_bind()

    # 1. Restore config JSONB
    conn.execute(
        text("""
            UPDATE toolkits
            SET config = jsonb_set(config, '{auth_type}', '"api_key"')
            WHERE tool_slug = 'mcp'
              AND config ->> 'auth_type' = 'header'
        """)
    )

    # 2. Restore encrypted_credentials
    encryption_key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    if encryption_key is None:
        return

    fernet = Fernet(encryption_key.encode())

    rows = conn.execute(
        text("""
            SELECT id, encrypted_credentials
            FROM toolkits
            WHERE tool_slug = 'mcp'
              AND encrypted_credentials IS NOT NULL
        """)
    ).fetchall()

    for row in rows:
        toolkit_id = row[0]
        encrypted = row[1]

        plaintext = fernet.decrypt(encrypted.encode()).decode()
        creds = json.loads(plaintext)

        if creds.get("type") != "header":
            continue

        # { "type": "header", "value": "..." } → { "type": "api_key", "api_key": "..." }
        new_creds = {"type": "api_key", "api_key": creds.get("value", "")}
        new_encrypted = fernet.encrypt(json.dumps(new_creds).encode()).decode()

        conn.execute(
            text("UPDATE toolkits SET encrypted_credentials = :creds WHERE id = :id"),
            {"creds": new_encrypted, "id": toolkit_id},
        )
