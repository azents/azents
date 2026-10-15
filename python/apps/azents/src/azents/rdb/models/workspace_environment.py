"""Workspace environment identities and explicit Agent opt-in relations."""

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel


class RDBWorkspaceEnvironmentVariable(RDBModel):
    """An immutable variable identity; renaming creates a new identity."""

    __tablename__ = "workspace_environment_variables"
    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, default_factory=lambda: uuid7().hex, init=False
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(sa.Text, nullable=False)
    UQ_WORKSPACE_NAME = sa.UniqueConstraint(
        "workspace_id", "name", name="uq_workspace_environment_name"
    )
    __table_args__ = (UQ_WORKSPACE_NAME,)


class RDBAgentWorkspaceEnvironmentSelection(RDBModel):
    """Absence is opt-out; deletion of either identity removes consent."""

    __tablename__ = "agent_workspace_environment_selections"
    agent_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    variable_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspace_environment_variables.id", ondelete="CASCADE"),
        primary_key=True,
    )
    IX_VARIABLE = sa.Index("ix_agent_workspace_env_variable", "variable_id")
    __table_args__ = (IX_VARIABLE,)
