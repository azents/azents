"""Current private working files retained with their execution Session."""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

import azents.rdb.models.agent_session as _agent_session  # noqa: F401
from azents.rdb.models.base import RDBModel


class RDBSessionExecutionFile(RDBModel):
    """One current canonical file, without revision history or observation ledgers."""

    __tablename__ = "session_execution_files"

    FK_SESSION = sa.ForeignKeyConstraint(
        ["session_id"],
        ["agent_sessions.id"],
        name="fk_session_execution_files_session",
        ondelete="CASCADE",
    )
    CK_PATH = sa.CheckConstraint(
        "length(path) > 0",
        name="ck_session_execution_files_path",
    )

    session_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    path: Mapped[str] = mapped_column(sa.String(512), primary_key=True)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    writable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)

    __table_args__ = (FK_SESSION, CK_PATH)
