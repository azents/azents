"""Completed read-only installed PostgreSQL lifecycle schema diagnostics."""

import dataclasses
from collections import defaultdict
from collections.abc import Mapping
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.session_lifecycle_schema import (
    PostgreSQLForeignKey,
    PostgreSQLForeignKeyDeleteAction,
    PostgreSQLReferentialTrigger,
)
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession

_DELETE_ACTION_BY_CATALOG_CODE: Mapping[str, PostgreSQLForeignKeyDeleteAction] = {
    "a": PostgreSQLForeignKeyDeleteAction.NO_ACTION,
    "r": PostgreSQLForeignKeyDeleteAction.RESTRICT,
    "c": PostgreSQLForeignKeyDeleteAction.CASCADE,
    "n": PostgreSQLForeignKeyDeleteAction.SET_NULL,
    "d": PostgreSQLForeignKeyDeleteAction.SET_DEFAULT,
}


@dataclasses.dataclass
class PostgreSQLSessionLifecycleGraphRepository:
    """Read installed foreign keys and referential-action triggers from PostgreSQL."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def read_foreign_keys(self) -> tuple[PostgreSQLForeignKey, ...]:
        """Return a detached installed graph after closing its read-only scope."""
        async with self.session_manager() as session:
            return await self._read_foreign_keys(session)

    async def _read_foreign_keys(
        self,
        session: ReadSession,
    ) -> tuple[PostgreSQLForeignKey, ...]:
        """Read application foreign keys and their installed PostgreSQL triggers."""
        constraint_rows = (
            await session.read_session.execute(
                sa.text(
                    """
                    SELECT
                        constraint_catalog.conname AS constraint_name,
                        source_namespace.nspname || '.' || source_relation.relname
                            AS source_table,
                        target_namespace.nspname || '.' || target_relation.relname
                            AS target_table,
                        constraint_catalog.confdeltype AS delete_action
                    FROM pg_constraint AS constraint_catalog
                    JOIN pg_class AS source_relation
                        ON source_relation.oid = constraint_catalog.conrelid
                    JOIN pg_namespace AS source_namespace
                        ON source_namespace.oid = source_relation.relnamespace
                    JOIN pg_class AS target_relation
                        ON target_relation.oid = constraint_catalog.confrelid
                    JOIN pg_namespace AS target_namespace
                        ON target_namespace.oid = target_relation.relnamespace
                    WHERE constraint_catalog.contype = 'f'
                      AND source_namespace.nspname = 'public'
                      AND target_namespace.nspname = 'public'
                    ORDER BY
                        source_namespace.nspname,
                        source_relation.relname,
                        constraint_catalog.conname
                    """
                )
            )
        ).mappings()
        trigger_rows = (
            await session.read_session.execute(
                sa.text(
                    """
                    SELECT
                        constraint_catalog.conname AS constraint_name,
                        trigger_namespace.nspname || '.' || trigger_relation.relname
                            AS table_name,
                        trigger_catalog.tgname AS trigger_name,
                        pg_get_triggerdef(trigger_catalog.oid) AS trigger_definition
                    FROM pg_constraint AS constraint_catalog
                    JOIN pg_trigger AS trigger_catalog
                        ON trigger_catalog.tgconstraint = constraint_catalog.oid
                    JOIN pg_class AS trigger_relation
                        ON trigger_relation.oid = trigger_catalog.tgrelid
                    JOIN pg_namespace AS trigger_namespace
                        ON trigger_namespace.oid = trigger_relation.relnamespace
                    WHERE constraint_catalog.contype = 'f'
                      AND trigger_namespace.nspname = 'public'
                    ORDER BY
                        constraint_catalog.conname,
                        trigger_namespace.nspname,
                        trigger_relation.relname,
                        trigger_catalog.tgname
                    """
                )
            )
        ).mappings()

        triggers_by_constraint: dict[str, list[PostgreSQLReferentialTrigger]] = (
            defaultdict(list)
        )
        for row in trigger_rows:
            triggers_by_constraint[row["constraint_name"]].append(
                PostgreSQLReferentialTrigger(
                    name=row["trigger_name"],
                    table_name=row["table_name"],
                    definition=row["trigger_definition"],
                )
            )

        foreign_keys: list[PostgreSQLForeignKey] = []
        for row in constraint_rows:
            delete_action_code = row["delete_action"]
            try:
                delete_action = _DELETE_ACTION_BY_CATALOG_CODE[delete_action_code]
            except KeyError as error:
                raise RuntimeError(
                    "PostgreSQL returned an unknown FK delete action: "
                    f"{delete_action_code}"
                ) from error
            foreign_keys.append(
                PostgreSQLForeignKey(
                    constraint_name=row["constraint_name"],
                    source_table=row["source_table"],
                    target_table=row["target_table"],
                    delete_action=delete_action,
                    triggers=tuple(
                        triggers_by_constraint.get(row["constraint_name"], ())
                    ),
                )
            )
        return tuple(foreign_keys)
