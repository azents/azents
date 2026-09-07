"""Durable Runtime Control connection-generation authority models."""

import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import RuntimeConnectionAuthorityKind
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime

runtime_connection_authority_kind_enum = ENUM(
    RuntimeConnectionAuthorityKind,
    name="runtime_connection_authority_kind",
    create_type=False,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class RDBRuntimeConnectionGenerationCutover(RDBModel):
    """One immutable allocator cutover marker established by migration."""

    __tablename__ = "runtime_connection_generation_cutovers"

    CK_POSITIVE_VERSION = sa.CheckConstraint(
        "allocator_version > 0",
        name="ck_runtime_connection_generation_cutovers_positive_version",
    )

    allocator_version: Mapped[int] = mapped_column(sa.SmallInteger, primary_key=True)
    cutover_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )

    __table_args__ = (CK_POSITIVE_VERSION,)


class RDBRuntimeConnectionGeneration(RDBModel):
    """Durable allocated and accepted connection-generation high-water."""

    __tablename__ = "runtime_connection_generations"

    CK_NON_NEGATIVE = sa.CheckConstraint(
        "high_water_generation >= 0 AND accepted_generation >= 0",
        name="ck_runtime_connection_generations_non_negative",
    )
    CK_ACCEPTED_WITHIN_HIGH_WATER = sa.CheckConstraint(
        "accepted_generation <= high_water_generation",
        name="ck_runtime_connection_generations_accepted_within_high_water",
    )
    CK_SAFE_INTEGER_MAX = sa.CheckConstraint(
        "high_water_generation <= 9007199254740991",
        name="ck_runtime_connection_generations_safe_integer_max",
    )

    connection_kind: Mapped[RuntimeConnectionAuthorityKind] = mapped_column(
        runtime_connection_authority_kind_enum,
        primary_key=True,
    )
    subject_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    high_water_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    accepted_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (
        CK_NON_NEGATIVE,
        CK_ACCEPTED_WITHIN_HIGH_WATER,
        CK_SAFE_INTEGER_MAX,
    )
