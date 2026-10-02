"""Best-effort orchestration for durable subagent terminal result repair."""

import asyncio
import dataclasses
import logging
from typing import Annotated, Literal

from fastapi import Depends

from azents.repos.subagent_terminal_result import SubagentTerminalResultRepository

logger = logging.getLogger(__name__)

DeliveryRepairSource = Literal[
    "terminal_boundary",
    "parent_wait",
    "source_session_reuse",
]


@dataclasses.dataclass(frozen=True)
class TerminalResultDeliverySummary:
    """Best-effort terminal result delivery attempt summary."""

    attempted: int
    enqueued: int
    already_finalized: int
    failed: int


@dataclasses.dataclass(frozen=True)
class SubagentTerminalResultService:
    """Sequence completed repair operations and retain best-effort reporting."""

    repository: Annotated[
        SubagentTerminalResultRepository, Depends(SubagentTerminalResultRepository)
    ]

    async def deliver_pending_for_source_session(
        self,
        source_session_id: str,
        *,
        repair_source: DeliveryRepairSource,
    ) -> TerminalResultDeliverySummary:
        """Attempt every eligible terminal Run for one source session."""
        try:
            candidate_ids = await self.repository.list_candidate_run_ids(
                source_session_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to list pending subagent terminal results",
                extra={
                    "source_session_id": source_session_id,
                    "repair_source": repair_source,
                },
            )
            return TerminalResultDeliverySummary(0, 0, 0, 1)
        enqueued = 0
        finalized = 0
        failed = 0
        for run_id in candidate_ids:
            try:
                delivered = await self.repository.deliver_one(run_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                failed += 1
                logger.exception(
                    "Failed to deliver subagent terminal result",
                    extra={
                        "run_id": run_id,
                        "source_session_id": source_session_id,
                        "repair_source": repair_source,
                    },
                )
                continue
            if delivered:
                enqueued += 1
                logger.info(
                    "Enqueued subagent terminal result",
                    extra={
                        "run_id": run_id,
                        "source_session_id": source_session_id,
                        "repair_source": repair_source,
                    },
                )
            else:
                finalized += 1
        return TerminalResultDeliverySummary(
            attempted=len(candidate_ids),
            enqueued=enqueued,
            already_finalized=finalized,
            failed=failed,
        )

    async def deliver_pending_for_parent_children(
        self,
        parent_session_id: str,
        *,
        repair_source: DeliveryRepairSource,
    ) -> TerminalResultDeliverySummary:
        """Repair eligible results from the current agent's direct children."""
        child_session_ids = await self.repository.list_direct_child_session_ids(
            parent_session_id,
        )
        summaries = [
            await self.deliver_pending_for_source_session(
                child_session_id,
                repair_source=repair_source,
            )
            for child_session_id in child_session_ids
        ]
        return TerminalResultDeliverySummary(
            attempted=sum(summary.attempted for summary in summaries),
            enqueued=sum(summary.enqueued for summary in summaries),
            already_finalized=sum(summary.already_finalized for summary in summaries),
            failed=sum(summary.failed for summary in summaries),
        )
