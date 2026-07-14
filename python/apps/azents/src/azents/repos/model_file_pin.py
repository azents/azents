"""ModelFile pin repository."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunStatus, ModelFileStatus
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.model_file import RDBModelFile
from azents.rdb.models.model_file_pin import RDBModelFilePin


class ModelFilePinRepository:
    """CRUD repository for active ModelFile run pins."""

    async def pin_many(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        run_id: str,
        model_file_ids: Sequence[str],
    ) -> None:
        """Create idempotent active run pins for ModelFiles."""
        requested_ids = sorted(dict.fromkeys(model_file_ids))
        if not requested_ids:
            return
        model_files = (
            await session.scalars(
                sa.select(RDBModelFile)
                .where(RDBModelFile.id.in_(requested_ids))
                .order_by(RDBModelFile.id)
                .with_for_update()
            )
        ).all()
        eligible_ids = {
            model_file.id
            for model_file in model_files
            if model_file.session_id == session_id
            and model_file.status is ModelFileStatus.AVAILABLE
        }
        if eligible_ids != set(requested_ids):
            raise RuntimeError(
                "Cannot pin a missing, unavailable, or cross-session ModelFile"
            )
        rows = [
            {
                "model_file_id": model_file_id,
                "session_id": session_id,
                "run_id": run_id,
            }
            for model_file_id in requested_ids
        ]
        await session.execute(
            pg_insert(RDBModelFilePin)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=[
                    RDBModelFilePin.model_file_id,
                    RDBModelFilePin.run_id,
                ]
            )
        )
        await session.flush()

    async def release_run(self, session: AsyncSession, *, run_id: str) -> None:
        """Release all pins held by one run."""
        await session.execute(
            sa.delete(RDBModelFilePin).where(RDBModelFilePin.run_id == run_id)
        )
        await session.flush()

    async def release_terminal_run_pins(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> int:
        """Clear stale pins whose AgentRun is already terminal."""
        rows = (
            await session.execute(
                sa.select(RDBModelFilePin.model_file_id, RDBModelFilePin.run_id)
                .join(RDBAgentRun, RDBAgentRun.id == RDBModelFilePin.run_id)
                .where(
                    RDBAgentRun.status.in_(
                        [
                            AgentRunStatus.COMPLETED,
                            AgentRunStatus.STOPPED,
                            AgentRunStatus.FAILED,
                            AgentRunStatus.INTERRUPTED,
                            AgentRunStatus.CANCELLED,
                        ]
                    )
                )
                .limit(limit)
            )
        ).all()
        if not rows:
            return 0
        clauses = [
            sa.and_(
                RDBModelFilePin.model_file_id == model_file_id,
                RDBModelFilePin.run_id == run_id,
            )
            for model_file_id, run_id in rows
        ]
        await session.execute(sa.delete(RDBModelFilePin).where(sa.or_(*clauses)))
        await session.flush()
        return len(rows)
