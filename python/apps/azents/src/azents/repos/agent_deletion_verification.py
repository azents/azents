"""Database-only verification compiled from the Agent deletion ownership registry."""

import sqlalchemy as sa
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import TableClause

from azents.core.agent_deletion import (
    AgentDeletionContext,
    AgentDeletionParticipantFailure,
    AgentDeletionPolicy,
    AgentDeletionRegistry,
    AgentDeletionRelationship,
)
from azents.rdb.session_capabilities import ReadSession


class AgentDeletionVerification:
    """Verify scoped obligations without maintaining a second model ownership list."""

    def __init__(self, registry: AgentDeletionRegistry) -> None:
        self.registry = registry
        self.tables: dict[str, TableClause] = {}
        self.relations = tuple(
            relation
            for participant in registry.participants
            for relation in participant.relationships
        )

    def table(self, name: str) -> TableClause:
        """Reuse one quoted relation identity so nested predicates correlate safely."""
        if name in self.tables:
            return self.tables[name]
        columns = {
            column
            for relation in self.relations
            for column in (
                relation.source_columns if relation.source_table == name else ()
            )
        } | {
            column
            for relation in self.relations
            for column in (
                relation.target_columns if relation.target_table == name else ()
            )
        }
        table = sa.table(name, *(sa.column(column) for column in sorted(columns)))
        self.tables[name] = table
        return table

    def _reference_scope(
        self,
        relation: AgentDeletionRelationship,
        context: AgentDeletionContext,
        ancestors: frozenset[str],
    ) -> ColumnElement[bool]:
        source = self.table(relation.source_table)
        target = self.table(relation.target_table)
        target_query = sa.select(
            *(target.c[column] for column in relation.target_columns)
        ).where(self._owner_scope(relation.target_table, context, ancestors))
        if len(relation.source_columns) == 1:
            return source.c[relation.source_columns[0]].in_(target_query)
        return sa.tuple_(*(source.c[column] for column in relation.source_columns)).in_(
            target_query
        )

    def _owner_scope(
        self, name: str, context: AgentDeletionContext, ancestors: frozenset[str]
    ) -> ColumnElement[bool]:
        if name in ancestors:
            raise ValueError(f"Cyclic Agent deletion database scope: {name}")
        table = self.table(name)
        if name == "agents":
            return sa.and_(
                table.c.id == context.agent_id,
                table.c.workspace_id == context.workspace_id,
            )
        owners = [
            relation
            for relation in self.relations
            if relation.source_table == name
            and relation.policy
            in (
                AgentDeletionPolicy.DECLARED_CASCADE,
                AgentDeletionPolicy.VERIFY_RUNTIME,
            )
        ]
        if not owners:
            raise ValueError(f"Missing Agent deletion database scope: {name}")
        return sa.or_(
            *(
                self._reference_scope(relation, context, ancestors | {name})
                for relation in owners
            )
        )

    async def require_complete(
        self, session: ReadSession, *, context: AgentDeletionContext
    ) -> None:
        """Re-evaluate required absence and cross-owner cascade safety now."""
        for participant in self.registry.participants:
            for relation in participant.relationships:
                source = self.table(relation.source_table)
                scope = self._reference_scope(relation, context, frozenset())
                if relation.policy is AgentDeletionPolicy.REQUIRE_ABSENT:
                    exists = await session.read_session.scalar(
                        sa.select(sa.exists().where(scope))
                    )
                    if exists:
                        raise AgentDeletionParticipantFailure(
                            participant_key=participant.key,
                            phase=f"verify:{relation.key}",
                            error=RuntimeError(
                                f"Lifecycle root remains: {relation.key}"
                            ),
                        )
                elif (
                    relation.policy is AgentDeletionPolicy.DECLARED_CASCADE
                    and relation.target_table not in ("agents", "agent_runtimes")
                ):
                    direct_owners = [
                        candidate
                        for candidate in self.relations
                        if candidate.source_table == relation.source_table
                        and candidate.target_table == "agents"
                        and candidate.policy is AgentDeletionPolicy.DECLARED_CASCADE
                    ]
                    for owner in direct_owners:
                        agent_column = owner.source_columns[
                            owner.target_columns.index("id")
                        ]
                        foreign_owner = await session.read_session.scalar(
                            sa.select(
                                sa.exists().where(
                                    scope,
                                    source.c[agent_column].is_not(None),
                                    source.c[agent_column] != context.agent_id,
                                )
                            )
                        )
                        if foreign_owner:
                            raise AgentDeletionParticipantFailure(
                                participant_key=participant.key,
                                phase=f"verify:{relation.key}",
                                error=RuntimeError(
                                    "Cascade would mutate another Agent's resource"
                                ),
                            )
