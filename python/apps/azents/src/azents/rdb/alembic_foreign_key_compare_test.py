"""Tests for Alembic foreign-key comparison normalization."""

import sqlalchemy as sa
from sqlalchemy.engine.interfaces import ReflectedForeignKeyConstraint

from azents.rdb.alembic_foreign_key_compare import (
    _foreign_key_identity,
    _reflected_foreign_key_identity,
)


def _metadata_foreign_key(
    *,
    ondelete: str | None = "CASCADE",
) -> sa.ForeignKeyConstraint:
    metadata = sa.MetaData()
    sa.Table("parents", metadata, sa.Column("id", sa.Integer, primary_key=True))
    child = sa.Table(
        "children",
        metadata,
        sa.Column("parent_id", sa.Integer),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["parents.id"],
            ondelete=ondelete,
        ),
    )
    return next(
        constraint
        for constraint in child.constraints
        if isinstance(constraint, sa.ForeignKeyConstraint)
    )


def _reflected_foreign_key(
    *,
    constrained_columns: list[str] | None = None,
    referred_table: str = "parents",
    referred_columns: list[str] | None = None,
    ondelete: str | None = "CASCADE",
) -> ReflectedForeignKeyConstraint:
    return {
        "name": "children_parent_id_fkey",
        "constrained_columns": constrained_columns or ["parent_id"],
        "referred_schema": "public",
        "referred_table": referred_table,
        "referred_columns": referred_columns or ["id"],
        "options": {
            "ondelete": ondelete,
            "deferrable": True,
            "initially": "DEFERRED",
        },
    }


def test_foreign_key_identity_ignores_only_historical_timing() -> None:
    """Match a production FK despite reflected deferrability timing."""
    assert _foreign_key_identity(_metadata_foreign_key()) == (
        _reflected_foreign_key_identity(_reflected_foreign_key())
    )


def test_foreign_key_identity_retains_structure_and_actions() -> None:
    """Keep columns, targets, and actions authoritative for drift detection."""
    metadata_identity = _foreign_key_identity(_metadata_foreign_key())

    assert metadata_identity != _reflected_foreign_key_identity(
        _reflected_foreign_key(constrained_columns=["other_parent_id"])
    )
    assert metadata_identity != _reflected_foreign_key_identity(
        _reflected_foreign_key(referred_table="other_parents")
    )
    assert metadata_identity != _reflected_foreign_key_identity(
        _reflected_foreign_key(referred_columns=["other_id"])
    )
    assert metadata_identity != _reflected_foreign_key_identity(
        _reflected_foreign_key(ondelete="RESTRICT")
    )
