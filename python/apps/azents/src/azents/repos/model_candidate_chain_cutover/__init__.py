"""Model candidate-chain cutover repository."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.model_candidate_chain_cutover import (
    RDBModelCandidateChainCutover,
)


async def mark_model_candidate_chain_write(session: AsyncSession) -> None:
    """Fence database downgrade after the first canonical configuration write."""
    statement = insert(RDBModelCandidateChainCutover).values(
        id=1,
        schema_version=1,
        new_format_written_at=sa.func.now(),
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[RDBModelCandidateChainCutover.id],
            set_={
                "new_format_written_at": sa.func.coalesce(
                    RDBModelCandidateChainCutover.new_format_written_at,
                    sa.func.now(),
                )
            },
        )
    )
