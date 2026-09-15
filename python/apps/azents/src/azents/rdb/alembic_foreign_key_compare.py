"""Alembic comparison normalization for historical foreign-key timing."""

from typing import Any

import sqlalchemy as sa
from alembic.autogenerate.api import AutogenContext
from alembic.runtime.plugins import Plugin
from alembic.util import DispatchPriority, PriorityDispatchResult
from sqlalchemy.engine.interfaces import ReflectedForeignKeyConstraint

_PLUGIN_NAME = "azents.autogenerate.foreign_key_options"


def _normalize_action(action: str | None) -> str | None:
    if action is None or action.lower() == "no action":
        return None
    return action.lower()


def _normalize_schema(schema: str | None) -> str | None:
    if schema in (None, "public"):
        return None
    return schema


def _foreign_key_identity(
    constraint: sa.ForeignKeyConstraint,
) -> tuple[Any, ...]:
    elements = tuple(constraint.elements)
    return (
        tuple(element.parent.name for element in elements),
        tuple(
            (
                _normalize_schema(element.column.table.schema),
                element.column.table.name,
                element.column.name,
            )
            for element in elements
        ),
        _normalize_action(constraint.onupdate),
        _normalize_action(constraint.ondelete),
        constraint.match,
    )


def _reflected_foreign_key_identity(
    foreign_key: ReflectedForeignKeyConstraint,
) -> tuple[Any, ...]:
    options = foreign_key.get("options", {})
    referred_schema = _normalize_schema(foreign_key.get("referred_schema"))
    referred_table = foreign_key["referred_table"]
    return (
        tuple(foreign_key["constrained_columns"]),
        tuple(
            (referred_schema, referred_table, column)
            for column in foreign_key["referred_columns"]
        ),
        _normalize_action(options.get("onupdate")),
        _normalize_action(options.get("ondelete")),
        options.get("match"),
    )


def _reflected_foreign_keys(
    autogen_context: AutogenContext,
    schema: str | None,
    table_name: str,
) -> list[ReflectedForeignKeyConstraint]:
    inspector = autogen_context.inspector
    alembic_cache = inspector.info_cache.get("alembic_foreign_keys")
    if isinstance(alembic_cache, dict):
        cached = alembic_cache.get((schema, table_name))
        if isinstance(cached, list):
            return cached
    return inspector.get_foreign_keys(table_name, schema=schema)


def _normalize_reflected_foreign_key_timing(
    autogen_context: AutogenContext,
    modify_table_ops: object,
    schema: str | None,
    table_name: str,
    reflected_table: sa.Table,
    metadata_table: sa.Table,
) -> PriorityDispatchResult:
    """Ignore only historical FK timing absent from model declarations."""
    del modify_table_ops
    if reflected_table is None or metadata_table is None:
        return PriorityDispatchResult.CONTINUE

    metadata_constraints = {
        _foreign_key_identity(constraint): constraint
        for constraint in metadata_table.constraints
        if isinstance(constraint, sa.ForeignKeyConstraint)
    }
    for reflected_foreign_key in _reflected_foreign_keys(
        autogen_context,
        schema,
        table_name,
    ):
        metadata_constraint = metadata_constraints.get(
            _reflected_foreign_key_identity(reflected_foreign_key)
        )
        if metadata_constraint is None:
            continue
        options = reflected_foreign_key.setdefault("options", {})
        options["deferrable"] = metadata_constraint.deferrable
        options["initially"] = metadata_constraint.initially

    return PriorityDispatchResult.CONTINUE


def _setup(plugin: Plugin) -> None:
    plugin.add_autogenerate_comparator(
        _normalize_reflected_foreign_key_timing,
        "table",
        "foreignkeys",
        priority=DispatchPriority.FIRST,
    )


_setup(Plugin(_PLUGIN_NAME))
