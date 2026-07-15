"""Chat live streaming partial batching helper."""

import asyncio
import dataclasses
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Literal
from weakref import WeakValueDictionary

logger = logging.getLogger(__name__)

LIVE_PARTIAL_BATCH_MAX_DELAY_SECONDS = 0.075
LIVE_PARTIAL_BATCH_MAX_CHARS = 96

LivePartialKind = Literal["content", "reasoning"]
LivePartialFlushCallback = Callable[["LivePartialFlush"], Awaitable[None]]
LivePartialTransitionCallback = Callable[[], Awaitable[None]]


@dataclasses.dataclass(frozen=True)
class LivePartialFlush:
    """Live partial batch to flush."""

    session_id: str
    kind: LivePartialKind
    delta: str
    content_index: int | None = None


@dataclasses.dataclass
class _PartialBuffer:
    """Partial delta accumulated for one live projection key."""

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
            kind=self.kind,
            content_index=self.content_index,
            delta="".join(self.parts),
        )


class LivePartialBatcher:
    """Briefly batch and serialize live partial updates per Session."""

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
            OrderedDict[tuple[LivePartialKind, int | None], _PartialBuffer],
        ] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def append_content_delta(
        self,
        *,
        session_id: str,
        delta: str,
        content_index: int,
    ) -> None:
        """Add Assistant content delta to batch."""
        await self._append(
            session_id=session_id,
            kind="content",
            content_index=content_index,
            delta=delta,
        )

    async def append_reasoning_delta(
        self,
        *,
        session_id: str,
        delta: str,
    ) -> None:
        """Add Reasoning delta to batch."""
        await self._append(
            session_id=session_id,
            kind="reasoning",
            content_index=None,
            delta=delta,
        )

    async def _append(
        self,
        *,
        session_id: str,
        kind: LivePartialKind,
        content_index: int | None,
        delta: str,
    ) -> None:
        """Store Delta and flush according to threshold."""
        if not delta:
            return
        async with self._session_lock(session_id):
            key = (kind, content_index)
            session_buffers = self._buffers.setdefault(session_id, OrderedDict())
            buffer = session_buffers.get(key)
            if buffer is None:
                buffer = _PartialBuffer(kind=kind, content_index=content_index)
                session_buffers[key] = buffer
            buffer.append(delta)

            if buffer.size >= self._max_chars:
                await self._flush_session_locked(session_id)
                return
            self._ensure_timer(session_id)

    def _session_lock(self, session_id: str) -> asyncio.Lock:
        """Return the Session sequencing lock."""
        return self._locks.setdefault(session_id, asyncio.Lock())

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
        async with self._session_lock(session_id):
            await self._flush_session_locked(session_id)

    async def _flush_session_locked(self, session_id: str) -> None:
        """Flush one Session while its sequencing lock is held."""
        self._cancel_timer(session_id)
        session_buffers = self._buffers.pop(session_id, None)
        if not session_buffers:
            return
        for buffer in session_buffers.values():
            await self._flush(buffer.to_flush(session_id))

    def _cancel_timer(self, session_id: str) -> None:
        """Cancel a pending timer without cancelling its current task."""
        current = asyncio.current_task()
        timer = self._timers.pop(session_id, None)
        if timer is not None and timer is not current:
            timer.cancel()

    async def flush_session_and_transition(
        self,
        session_id: str,
        transition: LivePartialTransitionCallback,
    ) -> None:
        """Flush buffered output and serialize its durable replacement."""
        async with self._session_lock(session_id):
            try:
                await self._flush_session_locked(session_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await transition()
                raise
            await transition()

    async def discard_session(
        self,
        session_id: str,
        discard: LivePartialTransitionCallback,
    ) -> None:
        """Discard buffered output and serialize removal after prior mutations."""
        async with self._session_lock(session_id):
            self._cancel_timer(session_id)
            self._buffers.pop(session_id, None)
            await discard()

    async def close_session(self, session_id: str) -> None:
        """Flush pending batch and clean up timer at Session cleanup boundary."""
        await self.flush_session(session_id)
