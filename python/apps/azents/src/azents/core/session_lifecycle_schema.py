"""Detached installed PostgreSQL lifecycle graph diagnostic data."""

import dataclasses
import enum


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
