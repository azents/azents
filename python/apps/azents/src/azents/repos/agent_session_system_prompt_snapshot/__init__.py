"""AgentSession latest system prompt snapshot repository."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from azents.engine.events.types import SystemPromptAnalysisPayload
from azents.rdb.models.agent_session_system_prompt_snapshot import (
    RDBAgentSessionSystemPromptSnapshot,
)
from azents.rdb.session_capabilities import ReadSession, WriteSession


class AgentSessionSystemPromptSnapshotRepository:
    """Store the one current system prompt analysis for each AgentSession."""

    async def get(
        self,
        session: ReadSession,
        *,
        session_id: str,
    ) -> SystemPromptAnalysisPayload | None:
        """Return the current snapshot for a session."""
        rdb = await session.read_session.get(
            RDBAgentSessionSystemPromptSnapshot, session_id
        )
        if rdb is None:
            return None
        return SystemPromptAnalysisPayload.model_validate(rdb.system_prompt)

    async def replace(
        self,
        session: WriteSession,
        *,
        session_id: str,
        system_prompt: SystemPromptAnalysisPayload,
    ) -> None:
        """Atomically replace the current session snapshot."""
        prompt_json = system_prompt.model_dump(mode="json", exclude_none=True)
        insert_stmt = insert(RDBAgentSessionSystemPromptSnapshot).values(
            session_id=session_id,
            system_prompt=prompt_json,
        )
        await session.write_session.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[RDBAgentSessionSystemPromptSnapshot.session_id],
                set_={
                    "system_prompt": insert_stmt.excluded.system_prompt,
                    "updated_at": sa.func.now(),
                },
            )
        )

    async def delete(
        self,
        session: WriteSession,
        *,
        session_id: str,
    ) -> None:
        """Remove the current snapshot when a model call has no system prompt."""
        await session.write_session.execute(
            sa.delete(RDBAgentSessionSystemPromptSnapshot).where(
                RDBAgentSessionSystemPromptSnapshot.session_id == session_id
            )
        )
