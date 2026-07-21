"""Installed PostgreSQL lifecycle foreign-key graph reader and validator."""

import dataclasses
import enum
from collections import defaultdict
from collections.abc import Iterable, Mapping

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.session_lifecycle import (
    SessionLifecycleOwnershipManifest,
    SessionLifecycleResourceClassification,
)


class PostgreSQLForeignKeyDeleteAction(enum.StrEnum):
    """PostgreSQL foreign-key parent-delete actions."""

    NO_ACTION = "no_action"
    RESTRICT = "restrict"
    CASCADE = "cascade"
    SET_NULL = "set_null"
    SET_DEFAULT = "set_default"

    @property
    def mutates_child(self) -> bool:
        """Return whether a parent delete mutates the referencing row."""
        return self in {
            PostgreSQLForeignKeyDeleteAction.CASCADE,
            PostgreSQLForeignKeyDeleteAction.SET_NULL,
            PostgreSQLForeignKeyDeleteAction.SET_DEFAULT,
        }


_DELETE_ACTION_BY_CATALOG_CODE: Mapping[str, PostgreSQLForeignKeyDeleteAction] = {
    "a": PostgreSQLForeignKeyDeleteAction.NO_ACTION,
    "r": PostgreSQLForeignKeyDeleteAction.RESTRICT,
    "c": PostgreSQLForeignKeyDeleteAction.CASCADE,
    "n": PostgreSQLForeignKeyDeleteAction.SET_NULL,
    "d": PostgreSQLForeignKeyDeleteAction.SET_DEFAULT,
}


@dataclasses.dataclass(frozen=True)
class PostgreSQLReferentialTrigger:
    """One installed referential-action trigger belonging to a foreign key."""

    name: str
    table_name: str
    definition: str


@dataclasses.dataclass(frozen=True)
class PostgreSQLForeignKey:
    """Installed PostgreSQL foreign-key metadata."""

    constraint_name: str
    source_table: str
    target_table: str
    delete_action: PostgreSQLForeignKeyDeleteAction
    triggers: tuple[PostgreSQLReferentialTrigger, ...]


@dataclasses.dataclass(frozen=True)
class PostgreSQLMutatingPath:
    """One parent-delete mutation path through installed foreign keys."""

    foreign_keys: tuple[PostgreSQLForeignKey, ...]

    @property
    def target_table(self) -> str:
        """Return the table mutated at the end of this path."""
        return self.foreign_keys[-1].source_table

    def describe(self) -> str:
        """Return a stable table and constraint path for diagnostics."""
        first = self.foreign_keys[0]
        parts = [first.target_table]
        for foreign_key in self.foreign_keys:
            parts.append(
                f"--[{foreign_key.constraint_name}:{foreign_key.delete_action.value}]-->"
            )
            parts.append(foreign_key.source_table)
        return " ".join(parts)


@dataclasses.dataclass(frozen=True)
class SessionLifecycleSchemaViolation:
    """One unsafe installed-schema relationship reported by the validator."""

    code: str
    table_name: str
    message: str
    paths: tuple[PostgreSQLMutatingPath, ...]


@dataclasses.dataclass(frozen=True)
class SessionLifecycleSchemaValidationResult:
    """Complete lifecycle schema validation result."""

    foreign_keys: tuple[PostgreSQLForeignKey, ...]
    violations: tuple[SessionLifecycleSchemaViolation, ...]

    def require_safe(self) -> None:
        """Raise a complete diagnostic when the installed graph is unsafe."""
        if not self.violations:
            return
        details = "\n".join(
            f"- {violation.code} {violation.table_name}: {violation.message}"
            for violation in self.violations
        )
        raise RuntimeError(f"Unsafe session lifecycle PostgreSQL graph:\n{details}")


class PostgreSQLSessionLifecycleGraphReader:
    """Read installed foreign keys and referential-action triggers from PostgreSQL."""

    async def read_foreign_keys(
        self,
        session: AsyncSession,
    ) -> tuple[PostgreSQLForeignKey, ...]:
        """Read application foreign keys and their installed PostgreSQL triggers."""
        constraint_rows = (
            await session.execute(
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
            await session.execute(
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


class SessionLifecycleSchemaValidator:
    """Validate installed parent-delete paths against lifecycle ownership."""

    def validate(
        self,
        *,
        foreign_keys: Iterable[PostgreSQLForeignKey],
        manifest: SessionLifecycleOwnershipManifest,
        root_table: str,
    ) -> SessionLifecycleSchemaValidationResult:
        """Return all unsafe paths reachable through mutating parent actions."""
        foreign_key_items = tuple(foreign_keys)
        paths_by_table = self._mutating_paths_by_table(
            foreign_key_items,
            root_table=root_table,
        )
        violations: list[SessionLifecycleSchemaViolation] = []

        for table_name, paths in sorted(paths_by_table.items()):
            resource = manifest.database_resource(table_name.removeprefix("public."))
            if resource is None:
                violations.append(
                    SessionLifecycleSchemaViolation(
                        code="unclassified_reachable_table",
                        table_name=table_name,
                        message=(
                            "No session lifecycle ownership manifest entry covers "
                            "this reachable table. Paths: "
                            + "; ".join(path.describe() for path in paths)
                        ),
                        paths=paths,
                    )
                )
                continue
            if (
                resource.classification
                is SessionLifecycleResourceClassification.LIFECYCLE_ROOT
            ):
                violations.append(
                    SessionLifecycleSchemaViolation(
                        code="lifecycle_root_mutated_by_parent_delete",
                        table_name=table_name,
                        message=(
                            "Lifecycle roots must be explicitly finalized by "
                            f"{resource.test_node_id}. Paths: "
                            + "; ".join(path.describe() for path in paths)
                        ),
                        paths=paths,
                    )
                )
            if len(paths) > 1:
                violations.append(
                    SessionLifecycleSchemaViolation(
                        code="multiple_mutating_paths",
                        table_name=table_name,
                        message=(
                            "A reachable table has more than one mutating parent "
                            "delete path: "
                            + "; ".join(path.describe() for path in paths)
                        ),
                        paths=paths,
                    )
                )
            if (
                resource.classification
                is SessionLifecycleResourceClassification.PURE_DATABASE_CHILD
                and (
                    len(paths) != 1
                    or paths[0].foreign_keys[-1].delete_action
                    is not PostgreSQLForeignKeyDeleteAction.CASCADE
                )
            ):
                violations.append(
                    SessionLifecycleSchemaViolation(
                        code="pure_database_child_requires_one_cascade",
                        table_name=table_name,
                        message=(
                            "Pure database children require exactly one CASCADE "
                            f"owner asserted by {resource.test_node_id}."
                        ),
                        paths=paths,
                    )
                )

        return SessionLifecycleSchemaValidationResult(
            foreign_keys=foreign_key_items,
            violations=tuple(violations),
        )

    @staticmethod
    def _mutating_paths_by_table(
        foreign_keys: tuple[PostgreSQLForeignKey, ...],
        *,
        root_table: str,
    ) -> Mapping[str, tuple[PostgreSQLMutatingPath, ...]]:
        outgoing: dict[str, list[PostgreSQLForeignKey]] = defaultdict(list)
        for foreign_key in foreign_keys:
            if foreign_key.delete_action.mutates_child:
                outgoing[foreign_key.target_table].append(foreign_key)
        for edges in outgoing.values():
            edges.sort(key=lambda edge: (edge.source_table, edge.constraint_name))

        paths_by_table: dict[str, list[PostgreSQLMutatingPath]] = defaultdict(list)

        def walk(
            table_name: str,
            path: tuple[PostgreSQLForeignKey, ...],
            visited_tables: frozenset[str],
        ) -> None:
            for foreign_key in outgoing.get(table_name, ()):
                next_table = foreign_key.source_table
                next_path = (*path, foreign_key)
                paths_by_table[next_table].append(
                    PostgreSQLMutatingPath(foreign_keys=next_path)
                )
                if next_table in visited_tables:
                    continue
                walk(
                    next_table,
                    next_path,
                    frozenset((*visited_tables, next_table)),
                )

        walk(root_table, (), frozenset((root_table,)))
        return {
            table_name: tuple(paths) for table_name, paths in paths_by_table.items()
        }
