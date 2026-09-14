"""Inactive accepting-Control broker for replacement Runtime Web sessions."""

from __future__ import annotations

import asyncio
import dataclasses
from collections import deque
from typing import Protocol

from azents_runtime_control.runtime_web_capacity import (
    ActiveCapacityStream,
    CapacityProtocol,
    RuntimeWebCapacityCoordinator,
)
from azents_runtime_control.runtime_web_session import (
    MAX_STREAM_TOMBSTONES,
    OwnerSessionEpoch,
    StreamAuthority,
    StreamProtocol,
)


@dataclasses.dataclass(frozen=True)
class BrokerTarget:
    """Exact local or one-hop Owner target."""

    owner: OwnerSessionEpoch
    local: bool
    relay_count: int

    def __post_init__(self) -> None:
        if self.relay_count not in {0, 1} or self.local != (self.relay_count == 0):
            raise ValueError("Runtime Web relay topology is invalid")


@dataclasses.dataclass(frozen=True)
class BrokerStreamKey:
    """One peer-session-scoped logical stream identity."""

    source_session_id: str
    stream_id: int

    def __post_init__(self) -> None:
        if not self.source_session_id or self.stream_id <= 0:
            raise ValueError("Runtime Web broker stream identity is invalid")


@dataclasses.dataclass(frozen=True)
class BrokerAdmission:
    """Exact routing and Owner-capacity binding for one logical stream."""

    key: BrokerStreamKey
    target: BrokerTarget
    capacity_stream_id: int


class BrokerRouter(Protocol):
    async def resolve(self, authority: StreamAuthority) -> BrokerTarget | None: ...


class RuntimeWebSessionBroker:
    """Admit exact peer-scoped streams without replay or multi-hop relay."""

    def __init__(
        self, *, router: BrokerRouter, capacity: RuntimeWebCapacityCoordinator
    ) -> None:
        self.router = router
        self.capacity = capacity
        self.next_capacity_stream_id = 1
        self.admissions: dict[BrokerStreamKey, BrokerAdmission] = {}
        self.tombstones: deque[BrokerStreamKey] = deque(maxlen=MAX_STREAM_TOMBSTONES)
        self.tombstone_set: set[BrokerStreamKey] = set()
        self.lock = asyncio.Lock()

    async def admit(
        self,
        *,
        key: BrokerStreamKey,
        authority: StreamAuthority,
        protocol: StreamProtocol,
    ) -> BrokerAdmission | None:
        """Admit one exact authority and allocate Owner-scoped capacity identity."""
        target = await self.router.resolve(authority)
        if target is None:
            return None
        if (
            authority.runtime_id,
            authority.desired_generation,
            authority.runner_generation,
        ) != (
            target.owner.runtime_id,
            target.owner.desired_generation,
            target.owner.runner_generation,
        ):
            raise ValueError("Runtime Web authority does not match Owner epoch")
        async with self.lock:
            if key in self.admissions or key in self.tombstone_set:
                raise ValueError("Runtime Web broker stream identity is not reusable")
            capacity_stream_id = self.next_capacity_stream_id
            self.next_capacity_stream_id += 1
            pending = False
            try:
                pending = await self.capacity.begin_open(capacity_stream_id)
                if not pending:
                    self._retire(key)
                    return None
                capacity_protocol = (
                    CapacityProtocol.WEBSOCKET
                    if protocol is StreamProtocol.WEBSOCKET
                    else CapacityProtocol.HTTP
                )
                accepted = await self.capacity.accept_open(
                    ActiveCapacityStream(capacity_stream_id, capacity_protocol)
                )
                if not accepted:
                    await self.capacity.reject_open(capacity_stream_id)
                    self._retire(key)
                    return None
            except asyncio.CancelledError:
                if pending:
                    await self.capacity.reject_open(capacity_stream_id)
                self._retire(key)
                raise
            except Exception:
                if pending:
                    await self.capacity.reject_open(capacity_stream_id)
                self._retire(key)
                raise
            admission = BrokerAdmission(
                key=key,
                target=target,
                capacity_stream_id=capacity_stream_id,
            )
            self.admissions[key] = admission
            return admission

    async def release(self, key: BrokerStreamKey) -> bool:
        """Release exact active Runtime capacity and retire the source identity."""
        async with self.lock:
            admission = self.admissions.pop(key, None)
            if admission is None:
                return False
            await self.capacity.release_stream(admission.capacity_stream_id)
            self._retire(key)
            return True

    def _retire(self, key: BrokerStreamKey) -> None:
        if key in self.tombstone_set:
            return
        if len(self.tombstones) == MAX_STREAM_TOMBSTONES:
            expired = self.tombstones.popleft()
            self.tombstone_set.remove(expired)
        self.tombstones.append(key)
        self.tombstone_set.add(key)
