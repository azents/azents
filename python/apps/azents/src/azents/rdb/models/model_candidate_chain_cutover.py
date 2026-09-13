"""Model candidate-chain coordinated cutover state."""

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBModelCandidateChainCutover(RDBModel):
    """Singleton fence that makes post-write rollback fail closed."""

    __tablename__ = "model_candidate_chain_cutovers"

    id: Mapped[int] = mapped_column(sa.SmallInteger, primary_key=True)
    schema_version: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    cutover_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
    new_format_written_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )

    CK_SINGLETON = sa.CheckConstraint(
        "id = 1",
        name="ck_model_candidate_chain_cutovers_singleton",
    )
    CK_SCHEMA_VERSION = sa.CheckConstraint(
        "schema_version = 1",
        name="ck_model_candidate_chain_cutovers_schema_version",
    )

    __table_args__ = (CK_SINGLETON, CK_SCHEMA_VERSION)
