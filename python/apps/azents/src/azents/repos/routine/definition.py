"""Database-only definition primitives for Routine owner operations."""

import unicodedata

import sqlalchemy as sa
from sqlalchemy.sql import Select

from azents.core.json_value import JSONValue
from azents.core.routine import (
    RoutineChanges,
    RoutineContent,
    RoutineDefinition,
    RoutineScope,
    RoutineUnavailable,
    update_routine_content,
)
from azents.rdb.models.routine import RDBRoutine
from azents.rdb.session_capabilities import ReadSession, WriteSession


def routine_slug_base(title: str) -> str:
    """Keep readable Unicode letters and numbers within the stored slug bound."""
    words: list[str] = []
    word: list[str] = []
    for character in unicodedata.normalize("NFKC", title).casefold():
        if character.isalnum():
            word.append(character)
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return "-".join(words)[:64].rstrip("-") or "routine"


def _source_values(content: RoutineContent) -> list[dict[str, JSONValue]]:
    """Encode the supported typed sources at the persistence boundary."""
    return [{"type": source.type} for source in content.sources]


def routine_definition(row: RDBRoutine) -> RoutineDefinition:
    """Decode persisted content into its exact typed contract."""
    return RoutineDefinition(
        id=row.id,
        scope=RoutineScope(
            workspace_id=row.workspace_id,
            agent_id=row.agent_id,
            session_id=row.session_id,
        ),
        slug=row.slug,
        content=RoutineContent.model_validate(
            {"title": row.title, "objective": row.objective, "sources": row.sources}
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class RoutineDefinitionRepository:
    """Compose definition reads and writes inside an owner transaction."""

    def query(self, scope: RoutineScope) -> Select[tuple[RDBRoutine]]:
        """Scope every query by all durable owner identities."""
        return sa.select(RDBRoutine).where(
            RDBRoutine.workspace_id == scope.workspace_id,
            RDBRoutine.agent_id == scope.agent_id,
            RDBRoutine.session_id == scope.session_id,
        )

    async def list_for_session(
        self, session: ReadSession, *, scope: RoutineScope
    ) -> list[RoutineDefinition]:
        """Read the Session's bounded inventory without locks."""
        rows = await session.read_session.scalars(
            self.query(scope).order_by(RDBRoutine.created_at, RDBRoutine.id)
        )
        return [routine_definition(row) for row in rows]

    async def get(
        self, session: ReadSession, *, scope: RoutineScope, slug: str
    ) -> RoutineDefinition | None:
        """Read only the exact Routine in the authorized Session."""
        row = await session.read_session.scalar(
            self.query(scope).where(RDBRoutine.slug == slug)
        )
        return None if row is None else routine_definition(row)

    async def lock(
        self, session: WriteSession, *, scope: RoutineScope, slug: str
    ) -> RDBRoutine:
        """Lock the actual definition for compare-and-update or deletion."""
        row = await session.write_session.scalar(
            self.query(scope).where(RDBRoutine.slug == slug).with_for_update()
        )
        if row is None:
            raise RoutineUnavailable("Routine is not available in this Session.")
        return row

    async def count(self, session: ReadSession, *, scope: RoutineScope) -> int:
        """Count definitions after the owner has serialized Session creation."""
        return (
            await session.read_session.scalar(
                sa.select(sa.func.count()).select_from(self.query(scope).subquery())
            )
            or 0
        )

    async def create(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        content: RoutineContent,
    ) -> RoutineDefinition:
        """Create a readable stable slug under the already-locked Session owner."""
        slug = routine_slug_base(content.title)
        if await self.get(session, scope=scope, slug=slug) is not None:
            raise ValueError(f"Routine slug '{slug}' already exists in this Session.")
        row = RDBRoutine(
            workspace_id=scope.workspace_id,
            agent_id=scope.agent_id,
            session_id=scope.session_id,
            slug=slug,
            title=content.title,
            objective=content.objective,
            sources=_source_values(content),
        )
        session.write_session.add(row)
        await session.write_session.flush()
        return routine_definition(row)

    async def update(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        slug: str,
        expected: RoutineContent,
        changes: RoutineChanges,
    ) -> RoutineDefinition:
        """Compare complete old content and preserve every unrelated field."""
        row = await self.lock(session, scope=scope, slug=slug)
        content = update_routine_content(
            current=routine_definition(row).content,
            expected=expected,
            changes=changes,
        )
        row.title = content.title
        row.objective = content.objective
        row.sources = _source_values(content)
        await session.write_session.flush()
        await session.write_session.refresh(row)
        return routine_definition(row)

    async def delete(
        self, session: WriteSession, *, scope: RoutineScope, slug: str
    ) -> RoutineDefinition:
        """Remove the definition and its records, not admitted Toolkit State."""
        row = await self.lock(session, scope=scope, slug=slug)
        removed = routine_definition(row)
        await session.write_session.delete(row)
        await session.write_session.flush()
        return removed
