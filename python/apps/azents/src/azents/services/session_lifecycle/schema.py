"""Pure lifecycle ownership validation of detached installed schema graphs."""

from collections import defaultdict
from collections.abc import Iterable, Mapping

from azents.core.session_lifecycle import (
    SessionLifecycleOwnershipManifest,
    SessionLifecycleResourceClassification,
)
from azents.core.session_lifecycle_schema import (
    PostgreSQLForeignKey,
    PostgreSQLForeignKeyDeleteAction,
    PostgreSQLMutatingPath,
    SessionLifecycleSchemaValidationResult,
    SessionLifecycleSchemaViolation,
)


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
