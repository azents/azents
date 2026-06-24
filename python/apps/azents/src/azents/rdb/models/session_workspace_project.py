"""Session Workspace Project model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import SessionWorkspaceProjectRegistrationRequestStatus
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _registration_request_status_values(
    enum_cls: type[SessionWorkspaceProjectRegistrationRequestStatus],
) -> list[str]:
    """Return registration request status enum values stored in the DB."""
    return [v.value for v in enum_cls]


session_workspace_project_registration_request_status_enum = ENUM(
    SessionWorkspaceProjectRegistrationRequestStatus,
    name="session_workspace_project_registration_request_status",
    create_type=False,
    values_callable=_registration_request_status_values,
)


class RDBSessionWorkspaceProject(RDBModel):
    """Project registered from an existing AgentRuntime folder."""

    __tablename__ = "session_workspace_projects"

    UQ_RUNTIME_PATH = sa.UniqueConstraint(
        "agent_runtime_id",
        "path",
        name="uq_session_workspace_projects_runtime_path",
    )
    IX_AGENT_RUNTIME_ID = sa.Index(
        "ix_session_workspace_projects_agent_runtime_id",
        "agent_runtime_id",
    )

    agent_runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
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

    __table_args__ = (UQ_RUNTIME_PATH, IX_AGENT_RUNTIME_ID)


class RDBSessionWorkspaceProjectRegistrationRequest(RDBModel):
    """Project registration approval request created by an Agent user."""

    __tablename__ = "session_workspace_project_registration_requests"

    IX_RUNTIME_STATUS = sa.Index(
        "ix_swp_registration_requests_runtime_status",
        "agent_runtime_id",
        "status",
    )
    IX_PROJECT_ID = sa.Index(
        "ix_swp_registration_requests_project_id",
        "project_id",
    )

    agent_runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    project_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("session_workspace_projects.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    status: Mapped[SessionWorkspaceProjectRegistrationRequestStatus] = mapped_column(
        session_workspace_project_registration_request_status_enum,
        init=False,
        default=SessionWorkspaceProjectRegistrationRequestStatus.PENDING,
        nullable=False,
    )
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

    IX_PENDING_PATH = sa.Index(
        "ix_swp_registration_requests_pending_path",
        "agent_runtime_id",
        "path",
        unique=True,
        postgresql_where=(
            status == SessionWorkspaceProjectRegistrationRequestStatus.PENDING
        ),
    )

    __table_args__ = (IX_RUNTIME_STATUS, IX_PENDING_PATH, IX_PROJECT_ID)
