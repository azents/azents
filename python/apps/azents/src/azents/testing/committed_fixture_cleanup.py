"""Exact committed test-graph teardown without changing production transactions."""

import dataclasses
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


@dataclasses.dataclass(frozen=True)
class FixtureRow:
    """One exact primary key and its foreign-key identity values."""

    table_name: str
    key: tuple[object, ...]
    values: Mapping[str, object]


def _key(table: sa.Table, values: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(values[column.name] for column in table.primary_key.columns)


async def _rows(
    connection: AsyncConnection, table: sa.Table, predicate: sa.ColumnElement[bool]
) -> dict[tuple[str, tuple[object, ...]], FixtureRow]:
    result: dict[tuple[str, tuple[object, ...]], FixtureRow] = {}
    columns = {column.name: column for column in table.primary_key.columns}
    for constraint in table.foreign_key_constraints:
        for element in constraint.elements:
            columns[element.parent.name] = element.parent
    if table.name == "runtime_connection_generations":
        columns["subject_id"] = table.c.subject_id
        columns["connection_kind"] = table.c.connection_kind
    for row in (
        await connection.execute(sa.select(*columns.values()).where(predicate))
    ).mappings():
        values = dict(row)
        identity = _key(table, values)
        result[(table.name, identity)] = FixtureRow(table.name, identity, values)
    return result


async def _roots(
    connection: AsyncConnection, metadata: sa.MetaData
) -> dict[tuple[str, tuple[object, ...]], FixtureRow]:
    result = {}
    for name in ("workspaces", "users"):
        result.update(await _rows(connection, metadata.tables[name], sa.true()))
    return result


def _references(
    source: FixtureRow, target: FixtureRow, constraint: sa.ForeignKeyConstraint
) -> bool:
    if constraint.referred_table.name != target.table_name:
        return False
    return all(
        source.values.get(element.parent.name) is not None
        and source.values[element.parent.name] == target.values.get(element.column.name)
        for element in constraint.elements
    )


def _predicate(table: sa.Table, row: FixtureRow) -> sa.ColumnElement[bool]:
    return sa.and_(
        *(
            column == value
            for column, value in zip(table.primary_key.columns, row.key, strict=True)
        )
    )


def _cycle_reference(
    row: FixtureRow,
    parent: FixtureRow,
    remaining: Mapping[tuple[str, tuple[object, ...]], FixtureRow],
    metadata: sa.MetaData,
) -> bool:
    """Require an actual return path before clearing a nullable owned edge."""
    pending = [parent]
    seen = set()
    while pending:
        current = pending.pop()
        if current == row:
            return True
        key = (current.table_name, current.key)
        if key in seen:
            continue
        seen.add(key)
        pending.extend(
            target
            for constraint in metadata.tables[
                current.table_name
            ].foreign_key_constraints
            if not (
                constraint.deferrable and constraint.ondelete in (None, "NO ACTION")
            )
            for target in remaining.values()
            if _references(current, target, constraint)
        )
    return False


async def _cleanup(
    connection: AsyncConnection,
    metadata: sa.MetaData,
    baseline: dict[tuple[str, tuple[object, ...]], FixtureRow],
) -> None:
    current = await _roots(connection, metadata)
    owned = {key: row for key, row in current.items() if key not in baseline}
    while True:
        added = {}
        for table in metadata.tables.values():
            predicates = [
                sa.and_(
                    *(
                        element.parent == parent.values[element.column.name]
                        for element in constraint.elements
                    )
                )
                for constraint in table.foreign_key_constraints
                for parent in owned.values()
                if constraint.referred_table.name == parent.table_name
            ]
            # The Runner generation INSERT trigger has a polymorphic subject,
            # rather than a SQL foreign key. Register only the owned Runtime ID.
            if table.name == "runtime_connection_generations":
                predicates.extend(
                    sa.and_(
                        table.c.connection_kind == "runner",
                        table.c.subject_id == parent.values["id"],
                    )
                    for parent in owned.values()
                    if parent.table_name == "agent_runtimes"
                )
            if predicates:
                matches = await _rows(connection, table, sa.or_(*predicates))
                for key, row in matches.items():
                    assert key not in baseline, "Owned graph reaches a preexisting root"
                    if key not in owned:
                        added[key] = row
        if not added:
            break
        owned.update(added)
    assert set(owned).isdisjoint(baseline)
    remaining = dict(owned)
    while remaining:
        leaves = []
        for key, parent in remaining.items():
            blocked = any(
                child_key != key
                and not (
                    constraint.deferrable and constraint.ondelete in (None, "NO ACTION")
                )
                and _references(child, parent, constraint)
                for child_key, child in remaining.items()
                for constraint in metadata.tables[
                    child.table_name
                ].foreign_key_constraints
            )
            if not blocked:
                leaves.append(key)
        if not leaves:
            # Break only nullable references between owned rows in a real FK
            # cycle (notably Context -> root SessionAgent). Keep all other values.
            changed = False
            for key, row in list(remaining.items()):
                table = metadata.tables[row.table_name]
                nullable = {
                    element.parent.name: None
                    for constraint in table.foreign_key_constraints
                    if not (
                        constraint.deferrable
                        and constraint.ondelete in (None, "NO ACTION")
                    )
                    and all(element.parent.nullable for element in constraint.elements)
                    and any(
                        _references(row, parent, constraint)
                        and _cycle_reference(row, parent, remaining, metadata)
                        for parent in remaining.values()
                    )
                    for element in constraint.elements
                }
                if nullable:
                    await connection.execute(
                        sa.update(table).where(_predicate(table, row)).values(nullable)
                    )
                    remaining[key] = dataclasses.replace(
                        row, values={**row.values, **nullable}
                    )
                    changed = True
            assert changed, "Owned fixture graph has an unresolved non-null FK cycle"
            continue
        for key in leaves:
            row = remaining.pop(key)
            table = metadata.tables[row.table_name]
            await connection.execute(sa.delete(table).where(_predicate(table, row)))
    after = await _roots(connection, metadata)
    assert set(baseline) <= set(after), "Fixture cleanup removed a preexisting identity"
    for row in owned.values():
        table = metadata.tables[row.table_name]
        assert not await _rows(connection, table, _predicate(table, row)), (
            "Owned fixture row survived cleanup"
        )


@asynccontextmanager
async def committed_fixture_graph(
    engine: AsyncEngine, metadata: sa.MetaData
) -> AsyncIterator[None]:
    """Register exact baseline identities and clean only new root-owned rows."""
    async with engine.connect() as connection:
        baseline = await _roots(connection, metadata)
    try:
        yield
    finally:
        async with engine.begin() as connection:
            await _cleanup(connection, metadata, baseline)
