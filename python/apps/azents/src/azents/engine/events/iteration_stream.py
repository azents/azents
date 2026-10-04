"""Identity-free native-stream normalization and interruption propagation."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from azents.engine.events.iteration import IterationValue


class IterationOutputStream[TNativeEvent, TIncremental, TPartial](Protocol):
    """Provider normalizer state without a required durable event identity."""

    def process_event(self, event: TNativeEvent, /) -> TIncremental:
        """Consume one native provider event and produce incremental output."""
        ...

    def interrupt(self) -> TPartial:
        """Normalize the already observed partial output after a user stop."""
        ...


@dataclass(frozen=True)
class InterruptedIterationStream[TPartial]:
    """Host-owned partial output; the host decides persistence and termination."""

    partial: TPartial
    cancellation: asyncio.CancelledError


async def consume_iteration_stream[TNativeEvent, TIncremental, TPartial](
    *,
    events_factory: Callable[[], AsyncIterator[TNativeEvent]],
    output_stream: IterationOutputStream[TNativeEvent, TIncremental, TPartial],
    on_incremental: Callable[[TIncremental], Awaitable[None]] | None,
    is_user_stop: Callable[[asyncio.CancelledError], bool],
) -> (
    IterationValue[IterationOutputStream[TNativeEvent, TIncremental, TPartial]]
    | InterruptedIterationStream[TPartial]
):
    """Consume a provider stream without changing its timeout/transport policy.

    The caller retains the concrete stream for final completion after its own
    normalization phase transition. Shutdown cancellation is never normalized
    into a successful or user-stopped result.
    """
    try:
        async for event in events_factory():
            incremental = output_stream.process_event(event)
            if on_incremental is not None:
                await on_incremental(incremental)
    except asyncio.CancelledError as error:
        if is_user_stop(error):
            return InterruptedIterationStream(
                partial=output_stream.interrupt(), cancellation=error
            )
        raise
    return IterationValue(output_stream)
