"""LLMProviderIntegration model."""

import datetime
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import LLMProvider
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _llm_provider_values(enum_cls: type[LLMProvider]) -> list[str]:
    """Return LLMProvider enum values stored in the DB."""
    return [v.value for v in enum_cls]


llm_provider_enum = ENUM(
    LLMProvider,
    name="llm_provider",
    create_type=False,
    values_callable=_llm_provider_values,
)


class RDBLLMProviderIntegration(RDBModel):
    """LLMProviderIntegration table.

    workspacet LLM provider t integration settingst managet.
    onet workspacet same providert t multiple integrationt can create..
    """

    __tablename__ = "llm_provider_integrations"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[LLMProvider] = mapped_column(llm_provider_enum, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    encrypted_credentials: Mapped[str] = mapped_column(sa.Text, nullable=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    # index
    IX_WORKSPACE_ID = sa.Index(
        "ix_llm_provider_integrations_workspace_id", "workspace_id"
    )

    __table_args__ = (IX_WORKSPACE_ID,)
