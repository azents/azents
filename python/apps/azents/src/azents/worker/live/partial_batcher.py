"""Chat live streaming partial batching helper."""

import asyncio
import dataclasses
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Literal

logger = logging.getLogger(__name__)

LIVE_PARTIAL_BATCH_MAX_DELAY_SECONDS = 0.075
LIVE_PARTIAL_BATCH_MAX_CHARS = 96

LivePartialKind = Literal["content", "reasoning"]
LivePartialFlushCallback = Callable[["LivePartialFlush"], Awaitable[None]]


class LivePartialFlushCommittedCancellation(asyncio.CancelledError):
    """Signal cancellation after a partial projection may have committed."""


class LivePartialFlushAttemptedError(Exception):
    """Signal a failed projection attempt that must not be replayed."""


@dataclasses.dataclass(frozen=True)
class LivePartialFlush:
    """Live partial batch to flush."""

    session_id: str
    run_id: str
    kind: LivePartialKind
    delta: str
    content_index: int | None = None


@dataclasses.dataclass
class _PartialBuffer:
    """Partial delta accumulated for one live projection key."""

    run_id: str
    kind: LivePartialKind
    content_index: int | None
    parts: list[str] = dataclasses.field(default_factory=list)

    @property
    def size(self) -> int:
        """Return current accumulated character count."""
        return sum(len(part) for part in self.parts)

    def append(self, delta: str) -> None:
        """Add Delta to buffer."""
        self.parts.append(delta)

    def to_flush(self, session_id: str) -> LivePartialFlush:
        """Convert to flush payload."""
        return LivePartialFlush(
            session_id=session_id,
            run_id=self.run_id,
            kind=self.kind,
            content_index=self.content_index,
            delta="".join(self.parts),
        )


@dataclasses.dataclass
class _SessionFlushState:
    """Serialize flush callbacks and track waiters for safe state cleanup."""

    lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)
    users: int = 0


class LivePartialBatcher:
    """Briefly batch text/reasoning live partial updates per Session."""

    def __init__(
        self,
        flush: LivePartialFlushCallback,
        *,
        max_delay_seconds: float = LIVE_PARTIAL_BATCH_MAX_DELAY_SECONDS,
        max_chars: int = LIVE_PARTIAL_BATCH_MAX_CHARS,
    ) -> None:
        self._flush = flush
        self._max_delay_seconds = max_delay_seconds
        self._max_chars = max_chars
        self._buffers: dict[
            str,
            OrderedDict[tuple[str, LivePartialKind, int | None], _PartialBuffer],
        ] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._flush_states: dict[str, _SessionFlushState] = {}

    async def append_content_delta(
        self,
        *,
        session_id: str,
        run_id: str,
        delta: str,
        content_index: int,
    ) -> None:
        """Add Assistant content delta to batch."""
        should_flush = await self.buffer_content_delta(
            session_id=session_id,
            run_id=run_id,
            delta=delta,
            content_index=content_index,
        )
        if should_flush:
            await self.flush_session(session_id)

    async def buffer_content_delta(
        self,
        *,
        session_id: str,
        run_id: str,
        delta: str,
        content_index: int,
    ) -> bool:
        """Buffer content and report whether the size threshold was reached."""
        return await self._append(
            session_id=session_id,
            run_id=run_id,
            kind="content",
            content_index=content_index,
            delta=delta,
        )

    async def append_reasoning_delta(
        self,
        *,
        session_id: str,
        run_id: str,
        delta: str,
    ) -> None:
        """Add Reasoning delta to batch."""
        should_flush = await self.buffer_reasoning_delta(
            session_id=session_id,
            run_id=run_id,
            delta=delta,
        )
        if should_flush:
            await self.flush_session(session_id)

    async def buffer_reasoning_delta(
        self,
        *,
        session_id: str,
        run_id: str,
        delta: str,
    ) -> bool:
        """Buffer reasoning and report whether the size threshold was reached."""
        return await self._append(
            session_id=session_id,
            run_id=run_id,
            kind="reasoning",
            content_index=None,
            delta=delta,
        )

    async def _append(
        self,
        *,
        session_id: str,
        run_id: str,
        kind: LivePartialKind,
        content_index: int | None,
        delta: str,
    ) -> bool:
        """Store Delta and flush according to threshold."""
        if not delta:
            return False
        key = (run_id, kind, content_index)
        session_buffers = self._buffers.setdefault(session_id, OrderedDict())
        buffer = session_buffers.get(key)
        if buffer is None:
            buffer = _PartialBuffer(
                run_id=run_id,
                kind=kind,
                content_index=content_index,
            )
            session_buffers[key] = buffer
        buffer.append(delta)

        self._ensure_timer(session_id)
        return buffer.size >= self._max_chars

    def _ensure_timer(self, session_id: str) -> None:
        """Schedule Session flush timer when absent."""
        timer = self._timers.get(session_id)
        if timer is not None and not timer.done():
            return
        self._timers[session_id] = asyncio.create_task(self._run_timer(session_id))

    async def _run_timer(self, session_id: str) -> None:
        """Flush session buffer after delay."""
        try:
            await asyncio.sleep(self._max_delay_seconds)
            await self.flush_session(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to flush live partial batch on timer",
                extra={"session_id": session_id},
            )

    async def flush_session(self, session_id: str) -> None:
        """Flush all partial batches accumulated in Session."""
        state = self._flush_states.setdefault(session_id, _SessionFlushState())
        state.users += 1
        acquired = False
        try:
            await state.lock.acquire()
            acquired = True
            current = asyncio.current_task()
            timer = self._timers.pop(session_id, None)
            if timer is not None and timer is not current:
                timer.cancel()
            session_buffers = self._buffers.pop(session_id, None)
            if not session_buffers:
                return
            pending_buffers = list(session_buffers.values())
            for index, buffer in enumerate(pending_buffers):
                try:
                    await self._flush(buffer.to_flush(session_id))
                except LivePartialFlushCommittedCancellation:
                    self._restore_unflushed_buffers(
                        session_id,
                        pending_buffers[index + 1 :],
                    )
                    raise
                except LivePartialFlushAttemptedError:
                    # Redis may have applied the write before its response was lost.
                    # Never replay this batch; durable history is authoritative and a
                    # dropped live partial is safer than duplicated text. Preserve only
                    # batches whose projection was not attempted yet.
                    self._restore_unflushed_buffers(
                        session_id,
                        pending_buffers[index + 1 :],
                    )
                    raise
                except asyncio.CancelledError:
                    self._restore_unflushed_buffers(
                        session_id,
                        pending_buffers[index:],
                    )
                    raise
                except Exception:
                    self._restore_unflushed_buffers(
                        session_id,
                        pending_buffers[index:],
                    )
                    raise
        finally:
            if acquired:
                state.lock.release()
            state.users -= 1
            if (
                state.users == 0
                and not self._buffers.get(session_id)
                and session_id not in self._timers
                and self._flush_states.get(session_id) is state
            ):
                self._flush_states.pop(session_id, None)

    def _restore_unflushed_buffers(
        self,
        session_id: str,
        unflushed_buffers: list[_PartialBuffer],
    ) -> None:
        """Restore failed and pending batches ahead of concurrently appended deltas."""
        concurrent_buffers = self._buffers.pop(session_id, OrderedDict())
        restored_buffers: OrderedDict[
            tuple[str, LivePartialKind, int | None], _PartialBuffer
        ] = OrderedDict()
        for buffer in unflushed_buffers:
            key = (buffer.run_id, buffer.kind, buffer.content_index)
            concurrent = concurrent_buffers.pop(key, None)
            if concurrent is not None:
                buffer.parts.extend(concurrent.parts)
            restored_buffers[key] = buffer
        restored_buffers.update(concurrent_buffers)
        if restored_buffers:
            self._buffers[session_id] = restored_buffers
            self._ensure_timer(session_id)

    async def close_session(self, session_id: str) -> None:
        """Flush pending batch and clean up timer at Session cleanup boundary."""
        await self.flush_session(session_id)

    async def discard_session(self, session_id: str) -> None:
        """Discard every pending partial at a new Run ownership boundary."""
        # Do not wait for the flush lock here. Run-boundary callers hold the
        # projector lock, while an in-flight flush callback waits for that same
        # lock. Popping queued buffers is event-loop atomic; an already-popped
        # old-Run batch is rejected by the projector's run fence after the
        # boundary advances.
        timer = self._timers.pop(session_id, None)
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        self._buffers.pop(session_id, None)
        state = self._flush_states.get(session_id)
        if state is not None and state.users == 0:
            self._flush_states.pop(session_id, None)
