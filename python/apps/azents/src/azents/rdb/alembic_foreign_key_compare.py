"""Alembic comparison normalization for historical foreign-key timing."""

from typing import NamedTuple

import sqlalchemy as sa
from alembic.autogenerate.api import AutogenContext
from alembic.runtime.plugins import Plugin
from alembic.util import DispatchPriority, PriorityDispatchResult
from sqlalchemy.engine.interfaces import ReflectedForeignKeyConstraint

_PLUGIN_NAME = "azents.autogenerate.foreign_key_options"


class _ForeignKeyIdentity(NamedTuple):
    constrained_columns: tuple[str, ...]
    referred_columns: tuple[tuple[str | None, str, str], ...]
    onupdate: str | None
    ondelete: str | None
    match: str | None


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
) -> _ForeignKeyIdentity:
    elements = tuple(constraint.elements)
    return _ForeignKeyIdentity(
        constrained_columns=tuple(element.parent.name for element in elements),
        referred_columns=tuple(
            (
                _normalize_schema(element.column.table.schema),
                element.column.table.name,
                element.column.name,
            )
            for element in elements
        ),
        onupdate=_normalize_action(constraint.onupdate),
        ondelete=_normalize_action(constraint.ondelete),
        match=constraint.match,
    )


def _reflected_foreign_key_identity(
    foreign_key: ReflectedForeignKeyConstraint,
) -> _ForeignKeyIdentity:
    options = foreign_key.get("options", {})
    referred_schema = _normalize_schema(foreign_key.get("referred_schema"))
    referred_table = foreign_key["referred_table"]
    return _ForeignKeyIdentity(
        constrained_columns=tuple(foreign_key["constrained_columns"]),
        referred_columns=tuple(
            (referred_schema, referred_table, column)
            for column in foreign_key["referred_columns"]
        ),
        onupdate=_normalize_action(options.get("onupdate")),
        ondelete=_normalize_action(options.get("ondelete")),
        match=options.get("match"),
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
