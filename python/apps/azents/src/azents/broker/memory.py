"""Application-owned, single-process Session broker."""

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from azents.broker.types import (
    BrokerMessage,
    SessionActivity,
    SessionMailboxActivity,
    SessionWakeUp,
    WorkerSignal,
)
from azents.core.enums import AgentRunPhase
from azents.engine.run.emit import PublishedEvent

_SESSION_TTL = 30 * 60
_HEARTBEAT_TTL = 120
_ACTIVITY_TTL = 30
_MESSAGE_TTL = 24 * 60 * 60
_BARRIER_TTL = 60 * 60


@dataclass
class _Owner:
    worker_id: str
    lease_until: float
    heartbeat_until: float


@dataclass
class _Activity:
    generation: int
    payload: SessionActivity | None
    expires_at: float


@dataclass
class _Messages:
    values: deque[BrokerMessage]
    expires_at: float


@dataclass(frozen=True)
class _Barrier:
    token: str
    expires_at: float


class InMemoryBrokerState:
    """Share ephemeral queues and fences within one application lifetime."""

    def __init__(self, *, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.changed = asyncio.Condition()
        self.messages: dict[str, _Messages] = {}
        self.owners: dict[str, _Owner] = {}
        self.activities: dict[str, _Activity] = {}
        self.barriers: dict[str, _Barrier] = {}
        self.incoming: deque[WorkerSignal] = deque()
        self.direct: dict[str, deque[WorkerSignal]] = {}
        self.closed = False

    def ensure_open(self) -> None:
        """Reject closed state and reclaim expired ephemeral records."""
        if self.closed:
            raise RuntimeError("Memory Session broker is closed")
        now = self.clock()
        for session_id in tuple(self.messages):
            if self.messages[session_id].expires_at <= now:
                del self.messages[session_id]
        for session_id in tuple(self.owners):
            if self.owners[session_id].lease_until <= now:
                del self.owners[session_id]
        for session_id in tuple(self.activities):
            if self.activities[session_id].expires_at <= now:
                del self.activities[session_id]
        for session_id in tuple(self.barriers):
            if self.barriers[session_id].expires_at <= now:
                del self.barriers[session_id]
        self.incoming = deque(
            signal
            for signal in self.incoming
            if self._live_signal(signal, now, worker_id=None)
        )
        for worker_id in tuple(self.direct):
            signals = deque(
                signal
                for signal in self.direct[worker_id]
                if self._live_signal(signal, now, worker_id=worker_id)
            )
            if signals:
                self.direct[worker_id] = signals
            else:
                del self.direct[worker_id]

    def _live_signal(
        self, signal: WorkerSignal, now: float, *, worker_id: str | None
    ) -> bool:
        if isinstance(signal, SessionMailboxActivity):
            owner = self.owners.get(signal.session_id)
            return (
                owner is not None
                and owner.worker_id == worker_id
                and owner.heartbeat_until > now
            )
        return signal.session_id in self.messages

    def owner(self, session_id: str, now: float) -> _Owner | None:
        """Read a sticky owner without reviving an expired lease."""
        owner = self.owners.get(session_id)
        if owner is not None and owner.lease_until <= now:
            del self.owners[session_id]
            return None
        return owner

    def barrier(self, session_id: str, now: float) -> _Barrier | None:
        """Read the active cutover barrier without extending its lifetime."""
        barrier = self.barriers.get(session_id)
        if barrier is not None and barrier.expires_at <= now:
            del self.barriers[session_id]
            return None
        return barrier

    def activity(self, session_id: str, now: float) -> _Activity | None:
        """Retain the generation tombstone only within its existing TTL."""
        activity = self.activities.get(session_id)
        if activity is not None and activity.expires_at <= now:
            del self.activities[session_id]
            return None
        return activity

    async def aclose(self) -> None:
        """Release state and unblock every receiver during root teardown."""
        async with self.changed:
            self.closed = True
            self.messages.clear()
            self.owners.clear()
            self.activities.clear()
            self.barriers.clear()
            self.incoming.clear()
            self.direct.clear()
            self.changed.notify_all()


class InMemoryBroker:
    """Implement SessionBroker over a shared, explicit process-local state."""

    def __init__(
        self,
        state: InMemoryBrokerState,
        *,
        worker_id: str | None,
    ) -> None:
        self.state = state
        self.worker_id = worker_id

    async def send_message(self, message: BrokerMessage) -> None:
        """Queue a routing signal and wake its live owner or the global receiver."""
        async with self.state.changed:
            self.state.ensure_open()
            now = self.state.clock()
            messages = self.state.messages.get(message.session_id)
            if messages is None or messages.expires_at <= now:
                messages = _Messages(deque(), now + _MESSAGE_TTL)
                self.state.messages[message.session_id] = messages
            messages.values.append(message)
            messages.expires_at = now + _MESSAGE_TTL
            owner = self.state.owner(message.session_id, now)
            target = (
                self.state.direct.setdefault(owner.worker_id, deque())
                if owner is not None and owner.heartbeat_until > now
                else self.state.incoming
            )
            target.append(SessionWakeUp(session_id=message.session_id))
            self.state.changed.notify_all()

    async def notify_mailbox_activity(self, session_id: str) -> None:
        """Notify only an existing live owner; never start an idle Session."""
        if self.worker_id is None:
            raise RuntimeError("Mailbox notification requires a Worker broker")
        async with self.state.changed:
            self.state.ensure_open()
            owner = self.state.owner(session_id, self.state.clock())
            if owner is None or owner.heartbeat_until <= self.state.clock():
                return
            self.state.direct.setdefault(owner.worker_id, deque()).append(
                SessionMailboxActivity(session_id=session_id)
            )
            self.state.changed.notify_all()

    async def receive_messages(self) -> list[WorkerSignal]:
        """Wait atomically for an admitted Session and drain its ordered signals."""
        worker_id = self.worker_id
        if worker_id is None:
            raise RuntimeError("Receiving signals requires a Worker broker")
        async with self.state.changed:
            while True:
                self.state.ensure_open()
                now = self.state.clock()
                for queue in (
                    self.state.direct.setdefault(worker_id, deque()),
                    self.state.incoming,
                ):
                    result = self._drain_ready(queue, worker_id, now)
                    if result:
                        return result
                remaining = [
                    barrier.expires_at - now
                    for barrier in self.state.barriers.values()
                    if barrier.expires_at > now
                ]
                if remaining:
                    try:
                        async with asyncio.timeout(min(remaining)):
                            await self.state.changed.wait()
                    except TimeoutError:
                        continue
                else:
                    await self.state.changed.wait()

    def _drain_ready(
        self,
        queue: deque[WorkerSignal],
        worker_id: str,
        now: float,
    ) -> list[WorkerSignal]:
        for _ in range(len(queue)):
            signal = queue.popleft()
            session_id = signal.session_id
            owner = self.state.owner(session_id, now)
            if isinstance(signal, SessionMailboxActivity):
                if (
                    owner is not None
                    and owner.worker_id == worker_id
                    and owner.heartbeat_until > now
                ):
                    return [signal]
                continue
            if self.state.barrier(session_id, now) is not None:
                queue.append(signal)
                continue
            messages = self.state.messages.get(session_id)
            if messages is None:
                continue
            if messages.expires_at <= now:
                del self.state.messages[session_id]
                continue
            if (
                owner is not None
                and owner.worker_id != worker_id
                and owner.heartbeat_until > now
            ):
                self.state.direct.setdefault(owner.worker_id, deque()).append(signal)
                self.state.changed.notify_all()
                continue
            self.state.owners[session_id] = _Owner(
                worker_id, now + _SESSION_TTL, now + _HEARTBEAT_TTL
            )
            del self.state.messages[session_id]
            return list(messages.values)
        return []

    async def publish_event(self, session_id: str, event: PublishedEvent) -> None:
        """Retain the existing adapter-free TTL-only publication behavior."""
        _ = event
        await self.renew_session_ttl(session_id)

    async def renew_session_ttl(self, session_id: str) -> None:
        """Refresh the current owner's lease/heartbeat and activity lifetime."""
        if self.worker_id is None:
            return
        async with self.state.changed:
            self.state.ensure_open()
            now = self.state.clock()
            owner = self.state.owner(session_id, now)
            if owner is not None and owner.worker_id == self.worker_id:
                owner.lease_until = now + _SESSION_TTL
                owner.heartbeat_until = now + _HEARTBEAT_TTL
            activity = self.state.activity(session_id, now)
            if activity is not None:
                activity.expires_at = now + _ACTIVITY_TTL

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """Refresh only the exact sticky owner's failure-detection heartbeat."""
        if self.worker_id is None:
            return
        async with self.state.changed:
            self.state.ensure_open()
            now = self.state.clock()
            owner = self.state.owner(session_id, now)
            if owner is not None and owner.worker_id == self.worker_id:
                owner.heartbeat_until = now + _HEARTBEAT_TTL

    async def release_session_lock(self, session_id: str) -> None:
        """Release exact Worker ownership, or explicit interface-side cleanup."""
        async with self.state.changed:
            self.state.ensure_open()
            owner = self.state.owner(session_id, self.state.clock())
            if owner is not None and (
                self.worker_id is None or owner.worker_id == self.worker_id
            ):
                del self.state.owners[session_id]
                self.state.changed.notify_all()

    async def set_session_activity(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
        phase: AgentRunPhase | None = None,
    ) -> bool:
        """Accept the newest durable execution generation, retaining its fence."""
        async with self.state.changed:
            self.state.ensure_open()
            now = self.state.clock()
            activity = self.state.activity(session_id, now)
            if activity is not None and activity.generation > owner_generation:
                return False
            self.state.activities[session_id] = _Activity(
                owner_generation, SessionActivity(run_id, phase), now + _ACTIVITY_TTL
            )
            return True

    async def clear_session_activity(
        self, session_id: str, *, owner_generation: int
    ) -> bool:
        """Clear only the exact generation's payload and retain its tombstone."""
        async with self.state.changed:
            self.state.ensure_open()
            now = self.state.clock()
            activity = self.state.activity(session_id, now)
            if activity is None or activity.generation != owner_generation:
                return False
            activity.payload = None
            activity.expires_at = now + _ACTIVITY_TTL
            return True

    async def get_session_activity(self, session_id: str) -> SessionActivity | None:
        """Return unexpired activity without reviving its generation fence."""
        async with self.state.changed:
            self.state.ensure_open()
            activity = self.state.activity(session_id, self.state.clock())
            return None if activity is None else activity.payload

    async def purge_session_state(self, session_id: str) -> None:
        """Purge routing/ownership/activity while retaining independent barriers."""
        async with self.state.changed:
            self.state.ensure_open()
            self.state.messages.pop(session_id, None)
            self.state.owners.pop(session_id, None)
            self.state.activities.pop(session_id, None)
            self.state.changed.notify_all()

    async def acquire_cutover_replay_barrier(self, session_ids: tuple[str, ...]) -> str:
        """Acquire one exact batch token without leaving partial barriers."""
        async with self.state.changed:
            self.state.ensure_open()
            now = self.state.clock()
            if len(set(session_ids)) != len(session_ids) or any(
                self.state.barrier(session_id, now) is not None
                for session_id in session_ids
            ):
                raise RuntimeError("Team Session cutover replay is already active")
            token = uuid4().hex
            for session_id in session_ids:
                self.state.barriers[session_id] = _Barrier(token, now + _BARRIER_TTL)
            self.state.changed.notify_all()
            return token

    async def release_cutover_replay_barrier(
        self, session_ids: tuple[str, ...], token: str
    ) -> None:
        """Release only barriers that still belong to this replay token."""
        async with self.state.changed:
            self.state.ensure_open()
            now = self.state.clock()
            for session_id in session_ids:
                barrier = self.state.barrier(session_id, now)
                if barrier is not None and barrier.token == token:
                    del self.state.barriers[session_id]
            self.state.changed.notify_all()

    async def renew_cutover_replay_barrier(
        self, session_ids: tuple[str, ...], token: str
    ) -> bool:
        """Renew existing exact-token barriers without adopting a replacement."""
        async with self.state.changed:
            self.state.ensure_open()
            now = self.state.clock()
            for session_id in session_ids:
                barrier = self.state.barrier(session_id, now)
                if barrier is None or barrier.token != token:
                    return False
                self.state.barriers[session_id] = _Barrier(token, now + _BARRIER_TTL)
            self.state.changed.notify_all()
            return True
