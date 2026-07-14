"""Redis-based session broker.

Relays messages between interfaces and the engine with complete-message Redis
Stream entries. A LIST/notification copy remains only for rolling compatibility
with workers that predate the atomic Stream protocol.

Sticky session: manages worker ownership with per-session Redis locks so the
same worker handles messages for the same session.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, NamedTuple, TypeVar

from azcommon.uuid import uuid7
from pydantic import BeforeValidator, TypeAdapter, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from azents.core.enums import AgentRunPhase

from .types import (
    BrokerMessage,
    PublishedEvent,
    SessionActivity,
    SessionOwnershipLostError,
    SessionWakeUp,
)

logger = logging.getLogger(__name__)
_RECEIVE_RECOVERY_TIMEOUT_SECONDS = 1.0
_RECEIVE_RECOVERY_ATTEMPTS = 3
_SEND_ATTEMPT_TIMEOUT_SECONDS = 10.0
_REDIS_OPERATION_TIMEOUT_SECONDS = 1.0
_T = TypeVar("_T")

# Duplicate error message when creating Redis Stream consumer groups
_BUSYGROUP_PREFIX = "BUSYGROUP"
_NOGROUP_PREFIX = "NOGROUP"
_ACQUIRE_LOCK_SCRIPT = """
local owner = redis.call("GET", KEYS[1])
if not owner then
  redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2])
  redis.call("SET", KEYS[2], ARGV[1], "EX", ARGV[3])
  return { "acquired", ARGV[1] }
end
if owner == ARGV[1] then
  redis.call("EXPIRE", KEYS[1], ARGV[2])
  redis.call("SET", KEYS[2], ARGV[1], "EX", ARGV[3])
  return { "owned", ARGV[1] }
end
local heartbeat = redis.call("GET", KEYS[2])
if heartbeat == owner then
  return { "live_owner", owner }
end
redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2])
redis.call("SET", KEYS[2], ARGV[1], "EX", ARGV[3])
return { "stolen", ARGV[1] }
"""
_ROUTE_WAKE_SCRIPT = """
local owner = redis.call("GET", KEYS[1])
if owner then
  local heartbeat = redis.call("GET", KEYS[2])
  if heartbeat == owner then
    return owner
  end
end
return false
"""
_RENEW_HEARTBEAT_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("SET", KEYS[2], ARGV[1], "EX", ARGV[2])
end
return false
"""
_RENEW_LEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  redis.call("EXPIRE", KEYS[1], ARGV[2])
  return redis.call("SET", KEYS[2], ARGV[1], "EX", ARGV[3])
end
return false
"""
_RELEASE_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  redis.call("DEL", KEYS[2])
  return redis.call("DEL", KEYS[1])
end
return 0
"""
_SET_ACTIVITY_IF_OWNER_SCRIPT = """
if redis.call("GET", KEYS[1]) ~= ARGV[1] then
  return 0
end
redis.call("SET", KEYS[2], ARGV[2], "EX", ARGV[3])
redis.call("SET", KEYS[3], ARGV[1], "EX", ARGV[3])
return 1
"""
_CLEAR_ACTIVITY_IF_OWNER_SCRIPT = """
if redis.call("GET", KEYS[1]) ~= ARGV[1] then
  return -1
end
redis.call("SET", KEYS[3], ARGV[1], "EX", ARGV[2])
return redis.call("DEL", KEYS[2])
"""
_CLEAR_ACTIVITY_FOR_RUN_SCRIPT = """
local value = redis.call("GET", KEYS[1])
if not value then
  return 0
end
local activity = cjson.decode(value)
if activity["run_id"] ~= ARGV[1] then
  return 0
end
return redis.call("DEL", KEYS[1])
"""
_CLEAR_ACTIVITY_FOR_RUN_IF_OWNER_SCRIPT = """
if redis.call("GET", KEYS[1]) ~= ARGV[1] then
  return -1
end
redis.call("SET", KEYS[3], ARGV[1], "EX", ARGV[3])
local value = redis.call("GET", KEYS[2])
if not value then
  return 0
end
local activity = cjson.decode(value)
if activity["run_id"] ~= ARGV[2] then
  return 0
end
return redis.call("DEL", KEYS[2])
"""
_DELETE_IF_VALUE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end
return 0
"""
_CLEAR_LEGACY_ACTIVITY_IF_OWNER_SCRIPT = """
local value = redis.call("GET", KEYS[1])
if not value then
  return 0
end
local ok, activity = pcall(cjson.decode, value)
if not ok or activity["_azents_owner"] ~= ARGV[1] then
  return 0
end
return redis.call("DEL", KEYS[1])
"""
_CLEAR_LEGACY_ACTIVITY_FOR_RUN_IF_OWNER_SCRIPT = """
local value = redis.call("GET", KEYS[1])
if not value then
  return 0
end
local ok, activity = pcall(cjson.decode, value)
if not ok or activity["_azents_owner"] ~= ARGV[1] then
  return 0
end
if activity["run_id"] ~= ARGV[2] then
  return 0
end
return redis.call("DEL", KEYS[1])
"""
_APPEND_WITH_TTL_SCRIPT = """
for index = 2, #ARGV do
  redis.call("RPUSH", KEYS[1], ARGV[index])
end
redis.call("EXPIRE", KEYS[1], ARGV[1])
return #ARGV - 1
"""

_session_wake_up_adapter = TypeAdapter[SessionWakeUp](SessionWakeUp)


def encode_session_wake_up(message: SessionWakeUp) -> bytes:
    """Serialize SessionWakeUp to JSON bytes."""
    return _session_wake_up_adapter.dump_json(message)


def decode_session_wake_up(raw: bytes) -> SessionWakeUp:
    """Deserialize JSON bytes to SessionWakeUp."""
    return _session_wake_up_adapter.validate_json(raw)


def _backfill_legacy_stop_request_id(value: Any) -> Any:  # noqa: ANN401
    """Accept stop signals emitted before durable request correlation shipped."""
    if (
        isinstance(value, dict)
        and value.get("type") == "session_stop_signal"
        and "stop_request_id" not in value
    ):
        return {**value, "stop_request_id": None}
    return value


_broker_message_adapter = TypeAdapter[
    Annotated[BrokerMessage, BeforeValidator(_backfill_legacy_stop_request_id)]
](Annotated[BrokerMessage, BeforeValidator(_backfill_legacy_stop_request_id)])
_session_activity_adapter = TypeAdapter[SessionActivity](SessionActivity)
_legacy_activity_adapter = TypeAdapter[dict[str, str | None]](dict[str, str | None])


def encode_broker_message(message: BrokerMessage) -> bytes:
    """Serialize BrokerMessage to JSON bytes."""
    return _broker_message_adapter.dump_json(message)


def _encode_legacy_broker_message(message: BrokerMessage) -> bytes:
    """Add a unique ignored field so legacy compensation is identity-safe."""
    payload = _broker_message_adapter.dump_python(message, mode="json")
    assert isinstance(payload, dict)
    payload["_azents_broker_delivery_id"] = uuid7().hex
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def decode_broker_message(raw: bytes) -> BrokerMessage:
    """Deserialize JSON bytes to BrokerMessage."""
    return _broker_message_adapter.validate_json(raw)


async def _run_with_redis_deadline(
    operation: Callable[[], Awaitable[_T]],
) -> _T:
    """Run one Redis operation with a process-local hard deadline.

    The shared Redis client intentionally has no socket I/O timeout because the
    broker also uses blocking commands. Every finite broker operation therefore
    needs its own deadline at the semantic operation boundary. This helper never
    retries because a timed-out mutation may already have committed in Redis.
    """
    async with asyncio.timeout(_REDIS_OPERATION_TIMEOUT_SECONDS):
        return await operation()


class _WakeUp(NamedTuple):
    stream_name: bytes | str
    entry_id: bytes | str
    session_id: str


class _AtomicWakeUp(NamedTuple):
    stream_name: bytes | str
    entry_id: bytes | str
    message: BrokerMessage
    legacy_encoded: bytes | None


class _Ownership(NamedTuple):
    status: str
    owner: str


class RedisBroker:
    """Redis-based session broker.

    - Atomic messages: Redis Stream ``azents:incoming:v2`` with complete envelopes
    - Rolling compatibility: legacy global/direct Streams and per-session LISTs
    - Session ownership: Redis String ``azents:session:{session_id}:lock`` with TTL 30m
    - owner heartbeat: Redis String
      ``azents:session:{session_id}:owner-heartbeat`` with TTL 120s
    """

    _STREAM_KEY = "azents:incoming"
    _GROUP_NAME = "engine-workers"
    _ATOMIC_STREAM_KEY = "azents:incoming:v2"
    _ATOMIC_GROUP_NAME = "engine-workers-v2"
    _SESSION_PREFIX = "azents:session:"
    _RECEIVE_BLOCK_MS = 100
    _WAKE_RECLAIM_IDLE_MS = 1_000
    _SESSION_TTL = 30 * 60  # seconds
    _OWNER_HEARTBEAT_TTL = 120  # seconds
    _ACTIVITY_TTL = 30  # seconds; TTL expiry cleans up after crashes
    _MESSAGE_TTL = 24 * 60 * 60  # seconds
    _INCOMING_RETENTION = 6 * 60 * 60  # seconds

    def __init__(self, redis: Redis, *, worker_id: str | None = None) -> None:
        self._redis = redis
        self._worker_id = worker_id
        self._detached_sends: set[asyncio.Task[None]] = set()
        self._detached_receive_recoveries: set[asyncio.Task[None]] = set()
        self._handed_off_atomic_wake: _AtomicWakeUp | None = None
        self._poll_atomic_first = True

    async def setup(self) -> None:
        """Create the consumer group once.

        Ignore it when already present. MKSTREAM also creates the stream if missing.
        """
        await self._ensure_stream_group(self._STREAM_KEY, self._GROUP_NAME)
        worker_id = self._worker_id
        if worker_id is not None:
            await self._ensure_stream_group(
                _worker_stream_key(worker_id),
                self._GROUP_NAME,
            )
            await self._ensure_stream_group(
                self._ATOMIC_STREAM_KEY,
                self._ATOMIC_GROUP_NAME,
            )
            await _run_with_redis_deadline(
                lambda: self._redis.set(
                    _worker_atomic_capability_key(worker_id),
                    "1",
                    ex=self._OWNER_HEARTBEAT_TTL,
                )
            )

    async def _ensure_stream_group(self, stream_key: str, group_name: str) -> None:
        """Create the Stream consumer group if it does not exist."""
        try:
            await _run_with_redis_deadline(
                lambda: self._redis.xgroup_create(
                    stream_key,
                    group_name,
                    id="0",
                    mkstream=True,
                )
            )
        except ResponseError as exc:
            if not str(exc).startswith(_BUSYGROUP_PREFIX):
                raise

    # ----- Interface side -----

    async def send_message(self, message: BrokerMessage) -> None:
        """Publish an atomic v2 envelope plus rolling-deploy compatibility copy.

        :param message: Broker message to send
        """
        send_task = asyncio.create_task(self._send_message_bounded(message))
        try:
            await asyncio.shield(send_task)
        except asyncio.CancelledError:
            # The durable producer may already have committed before its request
            # is cancelled. Let the short Redis enqueue finish so cancellation
            # cannot leave a message body without a wake notification.
            self._track_detached_send(send_task, session_id=message.session_id)
            raise

    async def _send_message_bounded(self, message: BrokerMessage) -> None:
        """Hard-bound a send that may outlive its cancelled caller."""
        async with asyncio.timeout(_SEND_ATTEMPT_TIMEOUT_SECONDS):
            await self._send_message(message)

    async def _send_message(self, message: BrokerMessage) -> None:
        """Publish one complete authority plus a rolling-deploy compatibility copy.

        The v2 Stream entry is both the message body and the notification. This
        deliberately avoids the legacy LIST -> EXPIRE -> XADD partial-commit
        window. A lost XADD response is therefore ambiguous only between the
        whole entry existing and no entry existing; it can never leave an
        undiscoverable v2 body behind. The mutation is not retried.

        The legacy path runs independently so a new API image remains compatible
        when Workers have not rolled forward yet or are fully rolled back. Either
        complete path is sufficient. Whole-envelope duplicates are expected and
        safe because broker messages only wake durable/idempotent Postgres state.
        """
        encoded = encode_broker_message(message)
        legacy_encoded = _encode_legacy_broker_message(message)
        atomic_task = asyncio.create_task(
            self._publish_atomic_message(message, encoded, legacy_encoded)
        )
        legacy_task = asyncio.create_task(
            self._publish_legacy_compatibility_message(message, legacy_encoded)
        )
        tasks = (atomic_task, legacy_task)
        try:
            atomic_result, legacy_result = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            for task in tasks:
                if task.done():
                    try:
                        task.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.exception(
                            "Broker delivery path failed during send cancellation",
                            extra={"session_id": message.session_id},
                        )
                else:
                    self._track_detached_send(
                        task,
                        session_id=message.session_id,
                    )
            raise
        if atomic_result is None or legacy_result is None:
            failed_path: str | None = None
            failed_result: object | None = None
            if atomic_result is not None:
                failed_path = "atomic"
                failed_result = atomic_result
            elif legacy_result is not None:
                failed_path = "legacy"
                failed_result = legacy_result
            if failed_path is not None and isinstance(failed_result, BaseException):
                logger.warning(
                    "Redundant broker delivery path failed",
                    extra={
                        "delivery_path": failed_path,
                        "session_id": message.session_id,
                    },
                    exc_info=failed_result,
                )
            return
        if isinstance(atomic_result, asyncio.CancelledError):
            raise atomic_result
        if isinstance(legacy_result, asyncio.CancelledError):
            raise legacy_result
        if isinstance(atomic_result, BaseException):
            raise atomic_result
        assert isinstance(legacy_result, BaseException)
        raise legacy_result

    async def _publish_atomic_message(
        self,
        message: BrokerMessage,
        encoded: bytes,
        legacy_encoded: bytes,
    ) -> None:
        """Publish the complete-message v2 authority in one Redis mutation."""
        await _run_with_redis_deadline(
            lambda: self._redis.xadd(
                self._ATOMIC_STREAM_KEY,
                {
                    "session_id": message.session_id,
                    "message": encoded,
                    "legacy_message": legacy_encoded,
                },
                minid=_stream_min_id(self._INCOMING_RETENTION),
                approximate=False,
            )
        )

    async def _publish_legacy_compatibility_message(
        self,
        message: BrokerMessage,
        encoded: bytes,
    ) -> None:
        """Publish a rolling-deploy copy for old LIST-based Workers."""
        msg_key = f"{self._SESSION_PREFIX}{message.session_id}:messages"
        appended = False
        try:
            await _run_with_redis_deadline(lambda: self._redis.rpush(msg_key, encoded))
            appended = True
            await _run_with_redis_deadline(
                lambda: self._redis.expire(msg_key, self._MESSAGE_TTL)
            )
            await self._publish_wake_up(message.session_id)
        except asyncio.CancelledError:
            await self._recover_failed_legacy_delivery(
                msg_key,
                encoded,
                session_id=message.session_id,
                appended=appended,
            )
            raise
        except TimeoutError, RedisError, OSError:
            await self._recover_failed_legacy_delivery(
                msg_key,
                encoded,
                session_id=message.session_id,
                appended=appended,
            )
            raise

    async def _recover_failed_legacy_delivery(
        self,
        msg_key: str,
        encoded: bytes,
        *,
        session_id: str,
        appended: bool,
    ) -> None:
        """Retain bounded wake repair and exact cleanup across cancellation."""

        async def recover() -> None:
            repaired = await self._publish_legacy_repair_wake_best_effort(session_id)
            if appended and not repaired:
                await self._remove_known_legacy_append(
                    msg_key,
                    encoded,
                    session_id=session_id,
                )

        recovery_task = asyncio.create_task(recover())
        try:
            await asyncio.shield(recovery_task)
        except asyncio.CancelledError:
            self._track_detached_send(recovery_task, session_id=session_id)
            raise

    async def _publish_legacy_repair_wake_best_effort(
        self,
        session_id: str,
    ) -> bool:
        """Try one duplicate-safe wake after an ambiguous legacy mutation."""
        try:
            await self._publish_wake_up(session_id)
        except asyncio.CancelledError:
            raise
        except TimeoutError, RedisError, OSError:
            logger.exception(
                "Failed to publish legacy broker repair wake",
                extra={"session_id": session_id},
            )
            return False
        return True

    async def _remove_known_legacy_append(
        self,
        msg_key: str,
        encoded: bytes,
        *,
        session_id: str,
    ) -> None:
        """Remove this delivery's unique legacy copy after a known append."""
        try:
            await _run_with_redis_deadline(
                lambda: self._redis.lrem(msg_key, -1, encoded)
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError, RedisError, OSError:
            logger.critical(
                "Failed to remove incomplete legacy broker delivery",
                extra={"session_id": session_id},
                exc_info=True,
            )

    def _track_detached_send(
        self,
        task: asyncio.Task[None],
        *,
        session_id: str,
    ) -> None:
        """Retain and observe a Redis enqueue after caller cancellation."""
        self._detached_sends.add(task)

        def on_done(done: asyncio.Task[None]) -> None:
            self._detached_sends.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                logger.error(
                    "Detached broker send was cancelled",
                    extra={"session_id": session_id},
                )
            except Exception:
                logger.exception(
                    "Detached broker send failed",
                    extra={"session_id": session_id},
                )

        task.add_done_callback(on_done)

    async def _publish_wake_up(self, session_id: str) -> None:
        """Publish one legacy wake for a rolling-deploy bridge."""
        owner = await _run_with_redis_deadline(
            lambda: self._redis.eval(
                _ROUTE_WAKE_SCRIPT,
                2,
                _session_lock_key(self._SESSION_PREFIX, session_id),
                _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id),
            )
        )
        stream_key = (
            _worker_stream_key(owner.decode() if isinstance(owner, bytes) else owner)
            if owner
            else self._STREAM_KEY
        )
        await _run_with_redis_deadline(
            lambda: self._redis.xadd(
                stream_key,
                {"session_id": session_id},
                minid=_stream_min_id(self._INCOMING_RETENTION),
                approximate=False,
            )
        )

    # ----- Engine side -----

    async def receive_messages(self) -> list[BrokerMessage]:
        """Receive, verify sticky ownership, and hand off complete messages.

        v2 complete-message entries and legacy LIST notifications are polled in
        alternating order. A v2 entry for another current Worker is assigned to
        that consumer's PEL; old owners receive a LIST/direct-Stream bridge.

        :return: Received broker messages, at least one
        """
        worker_id = self._worker_id
        assert worker_id is not None, "worker_id is required"
        await self._ack_handed_off_atomic_wake()
        poll_atomic = self._poll_atomic_first
        self._poll_atomic_first = not self._poll_atomic_first
        while True:
            if poll_atomic:
                atomic_wake = await self._try_read_atomic_wake_up()
                poll_atomic = False
                if atomic_wake is not None:
                    atomic_messages = await self._route_atomic_wake_up(atomic_wake)
                    if atomic_messages is not None:
                        return atomic_messages
                    continue

            wake_up: _WakeUp | None = None
            msg_key: str | None = None
            popped_raw: list[bytes] = []
            release_lock_on_recovery = False
            try:
                wake_up = await self._read_wake_up()
                poll_atomic = True
                if wake_up is None:
                    continue
                session_id = wake_up.session_id
                ownership = await self._acquire_or_find_owner(session_id)
                release_lock_on_recovery = ownership.status in {
                    "acquired",
                    "stolen",
                }
                if ownership.status == "live_owner":
                    await _run_with_redis_deadline(
                        lambda owner=ownership.owner, wake_session_id=session_id: (
                            self._redis.xadd(
                                _worker_stream_key(owner),
                                {"session_id": wake_session_id},
                                minid=_stream_min_id(self._INCOMING_RETENTION),
                                approximate=False,
                            )
                        )
                    )
                    await self._ack_wake_up(wake_up)
                    continue

                # Drain per-session LIST until the queue is empty
                msg_key = f"{self._SESSION_PREFIX}{session_id}:messages"
                while True:
                    raw = await _run_with_redis_deadline(
                        lambda message_key=msg_key: self._redis.lpop(message_key)
                    )
                    if raw is None:
                        break
                    popped_raw.append(raw)

                if not popped_raw:
                    # Duplicate notification; message was already consumed
                    if release_lock_on_recovery:
                        await self.release_session_lock(session_id)
                        release_lock_on_recovery = False
                    await self._ack_wake_up(wake_up)
                    continue

                messages: list[BrokerMessage] = []
                valid_raw: list[bytes] = []
                invalid_raw: list[bytes] = []
                for index, raw in enumerate(popped_raw):
                    try:
                        messages.append(decode_broker_message(raw))
                        valid_raw.append(raw)
                    except ValidationError:
                        invalid_raw.append(raw)
                        logger.exception(
                            "Quarantining invalid broker envelope",
                            extra={
                                "session_id": session_id,
                                "batch_index": index,
                            },
                        )
                if invalid_raw:
                    # Poison envelopes are no longer eligible for receive recovery.
                    # Quarantine is observability only; replaying one after a
                    # quarantine metadata failure would create an infinite loop.
                    popped_raw = valid_raw
                    await self._quarantine_invalid_messages(session_id, invalid_raw)
                if not messages:
                    if release_lock_on_recovery:
                        await self.release_session_lock(session_id)
                        release_lock_on_recovery = False
                    await self._ack_wake_up(wake_up)
                    continue
                await self._ack_wake_up(wake_up)
                return messages
            except asyncio.CancelledError:
                if wake_up is not None:
                    await self._recover_interrupted_receive(
                        wake_up,
                        msg_key=msg_key,
                        popped_raw=popped_raw,
                        release_session_lock=release_lock_on_recovery,
                    )
                raise
            except TimeoutError, RedisError, OSError:
                if wake_up is not None:
                    await self._recover_interrupted_receive(
                        wake_up,
                        msg_key=msg_key,
                        popped_raw=popped_raw,
                        release_session_lock=release_lock_on_recovery,
                    )
                raise

    async def _route_atomic_wake_up(
        self,
        wake_up: _AtomicWakeUp,
    ) -> list[BrokerMessage] | None:
        """Route one complete v2 Stream entry without destructive body reads."""
        release_lock_on_failure = False
        try:
            ownership = await self._acquire_or_find_owner(wake_up.message.session_id)
            release_lock_on_failure = ownership.status in {"acquired", "stolen"}
            if ownership.status == "live_owner":
                if await self._owner_supports_atomic_broker(ownership.owner):
                    await self._claim_atomic_wake_for_owner(
                        wake_up,
                        owner=ownership.owner,
                    )
                else:
                    await self._bridge_atomic_wake_to_legacy_owner(wake_up)
                return None

            # ACK is intentionally deferred until the next receive call. By then
            # AgentWorker has handed the message to its in-memory SessionRunner.
            # A crash before that boundary leaves the v2 entry pending for
            # XAUTOCLAIM instead of losing an initial input after XACK.
            await self._remove_atomic_legacy_copy_best_effort(wake_up)
            self._handed_off_atomic_wake = wake_up
            return [wake_up.message]
        except asyncio.CancelledError:
            if release_lock_on_failure:
                await self._release_atomic_receive_lock(wake_up.message.session_id)
            raise
        except TimeoutError, RedisError, OSError:
            if release_lock_on_failure:
                await self._release_atomic_receive_lock(wake_up.message.session_id)
            raise

    async def _remove_atomic_legacy_copy_best_effort(
        self,
        wake_up: _AtomicWakeUp,
    ) -> None:
        """Drain this v2 entry's exact dual-write copy on a new Worker."""
        encoded = wake_up.legacy_encoded
        if encoded is None:
            return
        await self._run_best_effort_projection(
            lambda: self._redis.lrem(
                f"{self._SESSION_PREFIX}{wake_up.message.session_id}:messages",
                -1,
                encoded,
            ),
            operation="remove atomic broker legacy compatibility copy",
            session_id=wake_up.message.session_id,
        )

    async def _owner_supports_atomic_broker(self, owner: str) -> bool:
        """Return whether a live owner consumes the v2 pending-entry protocol."""
        supported = await _run_with_redis_deadline(
            lambda: self._redis.get(_worker_atomic_capability_key(owner))
        )
        return supported is not None

    async def _claim_atomic_wake_for_owner(
        self,
        wake_up: _AtomicWakeUp,
        *,
        owner: str,
    ) -> None:
        """Assign a v2 PEL entry to its live sticky owner on the same Stream."""
        await _run_with_redis_deadline(
            lambda: self._redis.xclaim(  # pyright: ignore[reportAttributeAccessIssue]  # redis-py exposes XCLAIM at runtime but omits it from this generic Redis stub.
                self._ATOMIC_STREAM_KEY,
                self._ATOMIC_GROUP_NAME,
                owner,
                min_idle_time=0,
                message_ids=[wake_up.entry_id],
            )
        )

    async def _bridge_atomic_wake_to_legacy_owner(
        self,
        wake_up: _AtomicWakeUp,
    ) -> None:
        """Deliver a v2 entry to an old owner before releasing its authority.

        The v2 PEL entry remains the repair authority until LIST append, TTL,
        legacy wake publication, and v2 ACK all return successfully. A response
        loss can therefore cause a whole-envelope duplicate on redelivery, which
        is safe for these durable/idempotent hints, but cannot cause message loss.
        """
        message = wake_up.message
        msg_key = f"{self._SESSION_PREFIX}{message.session_id}:messages"
        encoded = encode_broker_message(message)
        await _run_with_redis_deadline(lambda: self._redis.rpush(msg_key, encoded))
        await _run_with_redis_deadline(
            lambda: self._redis.expire(msg_key, self._MESSAGE_TTL)
        )
        await self._publish_wake_up(message.session_id)
        await _run_with_redis_deadline(
            lambda: self._redis.xack(
                wake_up.stream_name,
                self._ATOMIC_GROUP_NAME,
                wake_up.entry_id,
            )
        )

    async def _ack_handed_off_atomic_wake(self) -> None:
        """ACK one already-handed-off entry once, tolerating redelivery."""
        wake_up = self._handed_off_atomic_wake
        if wake_up is None:
            return
        # Clear before the ambiguous mutation. Retrying XACK locally would not
        # distinguish a committed response loss. If it did not commit, the PEL
        # entry remains authoritative and may be redelivered as a safe duplicate.
        self._handed_off_atomic_wake = None
        try:
            await _run_with_redis_deadline(
                lambda: self._redis.xack(
                    wake_up.stream_name,
                    self._ATOMIC_GROUP_NAME,
                    wake_up.entry_id,
                )
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError, RedisError, OSError:
            logger.exception(
                "Failed to acknowledge handed-off atomic broker message",
                extra={"session_id": wake_up.message.session_id},
            )

    async def _release_atomic_receive_lock(self, session_id: str) -> None:
        """Release a newly acquired lease while leaving the v2 entry pending."""

        async def release() -> None:
            async with asyncio.timeout(_RECEIVE_RECOVERY_TIMEOUT_SECONDS):
                await self.release_session_lock(session_id)

        release_task = asyncio.create_task(release())
        try:
            await asyncio.shield(release_task)
        except asyncio.CancelledError:
            self._track_detached_receive_recovery(
                release_task,
                session_id=session_id,
            )
            raise
        except TimeoutError, RedisError, OSError:
            logger.exception(
                "Failed to release Session lease after atomic receive interruption",
                extra={"session_id": session_id},
            )

    async def _quarantine_invalid_messages(
        self,
        session_id: str,
        invalid_raw: list[bytes],
    ) -> None:
        """Preserve poison envelopes best-effort without blocking valid work."""
        key = _session_invalid_message_key(self._SESSION_PREFIX, session_id)
        try:
            await _run_with_redis_deadline(
                lambda: self._redis.eval(
                    _APPEND_WITH_TTL_SCRIPT,
                    1,
                    key,
                    str(self._MESSAGE_TTL),
                    *invalid_raw,
                )
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError, RedisError, OSError:
            logger.exception(
                "Failed to quarantine invalid broker envelopes; dropping batch",
                extra={
                    "invalid_count": len(invalid_raw),
                    "session_id": session_id,
                },
            )

    async def _recover_interrupted_receive(
        self,
        wake_up: _WakeUp,
        *,
        msg_key: str | None,
        popped_raw: list[bytes],
        release_session_lock: bool,
    ) -> None:
        """Restore a destructively-read envelope before propagating interruption."""

        async def run_step(
            step_name: str,
            operation: Callable[[], Awaitable[object]],
        ) -> None:
            for attempt in range(1, _RECEIVE_RECOVERY_ATTEMPTS + 1):
                try:
                    await operation()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    if attempt >= _RECEIVE_RECOVERY_ATTEMPTS:
                        raise
                    logger.warning(
                        "Retrying interrupted broker receive recovery step",
                        extra={
                            "attempt": attempt,
                            "session_id": wake_up.session_id,
                            "step_name": step_name,
                        },
                        exc_info=True,
                    )
                    await asyncio.sleep(0)

        async def recover() -> None:
            if msg_key is not None and popped_raw:
                restore_key = msg_key
                await run_step(
                    "restore_messages",
                    lambda: self._redis.lpush(
                        restore_key,
                        *reversed(popped_raw),
                    ),
                )
                await run_step(
                    "restore_message_ttl",
                    lambda: self._redis.expire(restore_key, self._MESSAGE_TTL),
                )
            if release_session_lock:
                await run_step(
                    "release_session_lock",
                    lambda: self.release_session_lock(wake_up.session_id),
                )
            await run_step(
                "republish_global_wake",
                lambda: self._redis.xadd(
                    self._STREAM_KEY,
                    {"session_id": wake_up.session_id},
                    minid=_stream_min_id(self._INCOMING_RETENTION),
                    approximate=False,
                ),
            )
            await run_step(
                "ack_interrupted_wake",
                lambda: self._redis.xack(
                    wake_up.stream_name,
                    self._GROUP_NAME,
                    wake_up.entry_id,
                ),
            )

        async def recover_with_timeout() -> None:
            async with asyncio.timeout(_RECEIVE_RECOVERY_TIMEOUT_SECONDS):
                await recover()

        recovery_task = asyncio.create_task(recover_with_timeout())
        try:
            await asyncio.shield(recovery_task)
        except asyncio.CancelledError:
            # A second cancellation must not orphan the recovery after the
            # destructive Redis read. Keep a strong reference and consume its
            # eventual outcome while allowing Worker shutdown to continue.
            self._track_detached_receive_recovery(
                recovery_task,
                session_id=wake_up.session_id,
            )
            raise
        except TimeoutError:
            logger.error(
                "Timed out restoring an interrupted broker receive",
                extra={"session_id": wake_up.session_id},
            )
        except Exception:
            logger.critical(
                "Failed restoring an interrupted broker receive; queued messages may "
                "require stuck-session recovery",
                extra={"session_id": wake_up.session_id},
                exc_info=True,
            )

    def _track_detached_receive_recovery(
        self,
        task: asyncio.Task[None],
        *,
        session_id: str,
    ) -> None:
        """Retain and observe recovery that outlives repeated cancellation."""
        self._detached_receive_recoveries.add(task)

        def on_done(done: asyncio.Task[None]) -> None:
            self._detached_receive_recoveries.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                logger.critical(
                    "Detached broker receive recovery was cancelled",
                    extra={"session_id": session_id},
                )
            except Exception:
                logger.critical(
                    "Detached broker receive recovery failed",
                    extra={"session_id": session_id},
                    exc_info=True,
                )

        task.add_done_callback(on_done)

    async def _try_read_atomic_wake_up(self) -> _AtomicWakeUp | None:
        """Read assigned, abandoned, then new complete-message Stream entries."""
        for read in (
            self._try_read_assigned_atomic_wake_up,
            self._try_reclaim_atomic_wake_up,
            self._try_read_new_atomic_wake_up,
        ):
            entry = await read()
            if entry is None:
                continue
            stream_name, raw_entry = entry
            wake_up = await self._decode_atomic_wake_up(stream_name, raw_entry)
            if wake_up is not None:
                return wake_up
        return None

    async def _try_read_assigned_atomic_wake_up(
        self,
    ) -> (
        tuple[
            bytes | str,
            tuple[bytes | str, dict[bytes, bytes]],
        ]
        | None
    ):
        """Read an entry explicitly assigned to this owner via XCLAIM."""
        return await self._try_read_atomic_group_entry("0", block=None)

    async def _try_read_new_atomic_wake_up(
        self,
    ) -> (
        tuple[
            bytes | str,
            tuple[bytes | str, dict[bytes, bytes]],
        ]
        | None
    ):
        """Read a never-delivered complete-message entry."""
        return await self._try_read_atomic_group_entry(
            ">",
            block=self._RECEIVE_BLOCK_MS,
        )

    async def _try_read_atomic_group_entry(
        self,
        stream_id: str,
        *,
        block: int | None,
    ) -> (
        tuple[
            bytes | str,
            tuple[bytes | str, dict[bytes, bytes]],
        ]
        | None
    ):
        """Read one v2 entry for the current consumer."""
        worker_id = self._worker_id
        assert worker_id is not None, "worker_id is required"
        try:
            results = await _run_with_redis_deadline(
                lambda: self._redis.xreadgroup(
                    self._ATOMIC_GROUP_NAME,
                    worker_id,
                    {self._ATOMIC_STREAM_KEY: stream_id},
                    count=1,
                    block=block,
                )
            )
        except ResponseError as exc:
            if not str(exc).startswith(_NOGROUP_PREFIX):
                raise
            await self._ensure_stream_group(
                self._ATOMIC_STREAM_KEY,
                self._ATOMIC_GROUP_NAME,
            )
            return None
        if not results or not results[0] or len(results[0]) != 2:
            return None
        stream_name, entries = results[0]
        if not entries:
            return None
        return stream_name, entries[0]

    async def _try_reclaim_atomic_wake_up(
        self,
    ) -> (
        tuple[
            bytes | str,
            tuple[bytes | str, dict[bytes, bytes]],
        ]
        | None
    ):
        """Claim one v2 entry abandoned by another consumer."""
        worker_id = self._worker_id
        assert worker_id is not None, "worker_id is required"
        try:
            response = await _run_with_redis_deadline(
                lambda: self._redis.xautoclaim(
                    self._ATOMIC_STREAM_KEY,
                    self._ATOMIC_GROUP_NAME,
                    worker_id,
                    self._WAKE_RECLAIM_IDLE_MS,
                    start_id="0-0",
                    count=1,
                )
            )
        except ResponseError as exc:
            if not str(exc).startswith(_NOGROUP_PREFIX):
                raise
            await self._ensure_stream_group(
                self._ATOMIC_STREAM_KEY,
                self._ATOMIC_GROUP_NAME,
            )
            return None
        entries = response[1]
        if not entries:
            return None
        return self._ATOMIC_STREAM_KEY, entries[0]

    async def _decode_atomic_wake_up(
        self,
        stream_name: bytes | str,
        entry: tuple[bytes | str, dict[bytes, bytes] | None],
    ) -> _AtomicWakeUp | None:
        """Decode a complete v2 entry, quarantining poison before ACK."""
        entry_id, fields = entry
        if fields is None:
            # Exact trimming may remove an entry body while retaining its PEL
            # reference. There is no envelope to recover after retention expiry.
            await _run_with_redis_deadline(
                lambda: self._redis.xack(
                    stream_name,
                    self._ATOMIC_GROUP_NAME,
                    entry_id,
                )
            )
            return None
        raw = fields.get(b"message")
        legacy_encoded = fields.get(b"legacy_message")
        session_id_raw = fields.get(b"session_id")
        try:
            if raw is None or session_id_raw is None:
                raise ValueError("atomic broker entry is missing required fields")
            message = decode_broker_message(raw)
            session_id = session_id_raw.decode()
            if message.session_id != session_id:
                raise ValueError("atomic broker entry Session identity mismatch")
        except UnicodeDecodeError, ValidationError, ValueError:
            logger.exception(
                "Quarantining invalid atomic broker envelope",
                extra={"entry_id": entry_id},
            )
            if raw is not None and session_id_raw is not None:
                try:
                    await self._quarantine_invalid_messages(
                        session_id_raw.decode(),
                        [raw],
                    )
                except UnicodeDecodeError:
                    pass
            await _run_with_redis_deadline(
                lambda: self._redis.xack(
                    stream_name,
                    self._ATOMIC_GROUP_NAME,
                    entry_id,
                )
            )
            return None
        return _AtomicWakeUp(
            stream_name=stream_name,
            entry_id=entry_id,
            message=message,
            legacy_encoded=legacy_encoded,
        )

    async def _read_wake_up(self) -> _WakeUp | None:
        """Poll worker direct and global streams once in a cluster-safe way."""
        assert self._worker_id is not None, "worker_id is required"
        stream_keys = (_worker_stream_key(self._worker_id), self._STREAM_KEY)
        for stream_key in stream_keys:
            wake_up = await self._try_read_wake_up(stream_key)
            if wake_up is not None:
                return wake_up
        return None

    async def _try_read_wake_up(self, stream_key: str) -> _WakeUp | None:
        """Read one wake-up from a single Redis Stream.

        Redis Cluster requires every key in one command to share the same hash slot.
        Worker direct stream and global stream can be in different slots, so each is
        read with a separate XREADGROUP command.

        :param stream_key: Redis Stream key to read
        :return: Matching entry when a wake-up exists, otherwise None
        """
        worker_id = self._worker_id
        assert worker_id is not None, "worker_id is required"
        reclaimed = await self._try_reclaim_wake_up(stream_key)
        if reclaimed is not None:
            return reclaimed
        try:
            results = await _run_with_redis_deadline(
                lambda: self._redis.xreadgroup(
                    self._GROUP_NAME,
                    worker_id,
                    {stream_key: ">"},
                    count=1,
                    block=self._RECEIVE_BLOCK_MS,
                )
            )
        except ResponseError as exc:
            if not str(exc).startswith(_NOGROUP_PREFIX):
                raise
            logger.warning(
                "Redis stream group missing; recreating",
                extra={"stream_key": stream_key, "consumer_group": self._GROUP_NAME},
            )
            await self._ensure_stream_group(stream_key, self._GROUP_NAME)
            return None
        if not results:
            return None

        stream_name, entries = results[0]
        return self._decode_wake_up_entry(stream_name, entries[0])

    async def _try_reclaim_wake_up(self, stream_key: str) -> _WakeUp | None:
        """Claim one wake left pending by a crashed consumer."""
        worker_id = self._worker_id
        assert worker_id is not None, "worker_id is required"
        try:
            response = await _run_with_redis_deadline(
                lambda: self._redis.xautoclaim(
                    stream_key,
                    self._GROUP_NAME,
                    worker_id,
                    self._WAKE_RECLAIM_IDLE_MS,
                    start_id="0-0",
                    count=1,
                )
            )
        except ResponseError as exc:
            if not str(exc).startswith(_NOGROUP_PREFIX):
                raise
            await self._ensure_stream_group(stream_key, self._GROUP_NAME)
            return None
        entries = response[1]
        if not entries:
            return None
        return self._decode_wake_up_entry(stream_key, entries[0])

    async def _ack_wake_up(self, wake_up: _WakeUp) -> None:
        """Acknowledge a wake only after its handoff or body drain succeeds."""
        await _run_with_redis_deadline(
            lambda: self._redis.xack(
                wake_up.stream_name,
                self._GROUP_NAME,
                wake_up.entry_id,
            )
        )

    @staticmethod
    def _decode_wake_up_entry(
        stream_name: bytes | str,
        entry: tuple[bytes | str, dict[bytes, bytes]],
    ) -> _WakeUp:
        """Decode one Redis Stream wake entry."""
        entry_id, fields = entry
        session_id_raw = fields[b"session_id"]
        session_id = (
            session_id_raw.decode()
            if isinstance(session_id_raw, bytes)
            else str(session_id_raw)
        )
        return _WakeUp(
            stream_name=stream_name,
            entry_id=entry_id,
            session_id=session_id,
        )

    async def _acquire_or_find_owner(self, session_id: str) -> _Ownership:
        """Acquire session ownership or return the live owner."""
        worker_id = self._worker_id
        assert worker_id is not None, "worker_id is required"
        result = await _run_with_redis_deadline(
            lambda: self._redis.eval(
                _ACQUIRE_LOCK_SCRIPT,
                2,
                _session_lock_key(self._SESSION_PREFIX, session_id),
                _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id),
                worker_id,
                str(self._SESSION_TTL),
                str(self._OWNER_HEARTBEAT_TTL),
            )
        )
        status_raw, owner_raw = result
        status = status_raw.decode() if isinstance(status_raw, bytes) else status_raw
        owner = owner_raw.decode() if isinstance(owner_raw, bytes) else owner_raw
        return _Ownership(status=status, owner=owner)

    async def publish_event(self, session_id: str, event: PublishedEvent) -> None:
        """Publish a session event and refresh lock/activity TTL.

        Used by the fallback path without an adapter.

        :param session_id: Target session ID
        :param event: Engine event to publish
        """
        _ = event  # Without an adapter, events have no delivery path
        await self.renew_session_ttl(session_id)

    async def renew_session_ttl(self, session_id: str) -> None:
        """Validate and refresh the Session lease and projection metadata TTLs.

        :param session_id: Target session ID
        """
        worker_id = self._worker_id
        if worker_id is None:
            return
        lock_key = _session_lock_key(self._SESSION_PREFIX, session_id)
        heartbeat_key = _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id)
        renewed = await _run_with_redis_deadline(
            lambda: self._redis.eval(
                _RENEW_LEASE_SCRIPT,
                2,
                lock_key,
                heartbeat_key,
                worker_id,
                str(self._SESSION_TTL),
                str(self._OWNER_HEARTBEAT_TTL),
            )
        )
        if not renewed:
            raise SessionOwnershipLostError(session_id)
        await self._refresh_atomic_broker_capability_best_effort(session_id)
        # The compare-and-renew above is the authority boundary and must fail
        # closed. These activity keys are only ephemeral projection metadata;
        # failure to extend one of them must not invalidate an otherwise verified
        # lease or abort the durable Run.
        activity_keys = (
            _session_activity_key(self._SESSION_PREFIX, session_id),
            _session_activity_migration_key(self._SESSION_PREFIX, session_id),
            _session_legacy_activity_key(self._SESSION_PREFIX, session_id),
        )

        async def renew_activity_ttls() -> list[object]:
            results = await asyncio.gather(
                *(
                    self._redis.expire(activity_key, self._ACTIVITY_TTL)
                    for activity_key in activity_keys
                ),
                return_exceptions=True,
            )
            return list(results)

        try:
            ttl_results = await _run_with_redis_deadline(renew_activity_ttls)
        except asyncio.CancelledError:
            raise
        except TimeoutError, RedisError, OSError:
            logger.exception(
                "Failed to renew Session activity projection TTLs",
                extra={"session_id": session_id},
            )
            return
        for activity_key, result in zip(activity_keys, ttl_results, strict=True):
            if isinstance(result, BaseException):
                logger.error(
                    "Failed to renew Session activity projection TTL",
                    extra={
                        "activity_key": activity_key,
                        "session_id": session_id,
                    },
                    exc_info=result,
                )

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """Refresh only the sticky owner heartbeat.

        :param session_id: Session ID
        """
        worker_id = self._worker_id
        if worker_id is None:
            return
        renewed = await _run_with_redis_deadline(
            lambda: self._redis.eval(
                _RENEW_HEARTBEAT_SCRIPT,
                2,
                _session_lock_key(self._SESSION_PREFIX, session_id),
                _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id),
                worker_id,
                str(self._OWNER_HEARTBEAT_TTL),
            )
        )
        if not renewed:
            raise SessionOwnershipLostError(session_id)
        await self._refresh_atomic_broker_capability_best_effort(session_id)

    async def _refresh_atomic_broker_capability_best_effort(
        self,
        session_id: str,
    ) -> None:
        """Refresh rolling-deploy routing metadata for this worker."""
        worker_id = self._worker_id
        if worker_id is None:
            return
        await self._run_best_effort_projection(
            lambda: self._redis.set(
                _worker_atomic_capability_key(worker_id),
                "1",
                ex=self._OWNER_HEARTBEAT_TTL,
            ),
            operation="refresh atomic broker capability",
            session_id=session_id,
        )

    async def release_session_lock(self, session_id: str) -> None:
        """Release session lock.

        :param session_id: Session ID to release
        """
        lock_key = _session_lock_key(self._SESSION_PREFIX, session_id)
        heartbeat_key = _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id)
        worker_id = self._worker_id
        if worker_id is None:
            await _run_with_redis_deadline(
                lambda: self._redis.delete(lock_key, heartbeat_key)
            )
            return
        await _run_with_redis_deadline(
            lambda: self._redis.eval(
                _RELEASE_LOCK_SCRIPT,
                2,
                lock_key,
                heartbeat_key,
                worker_id,
            )
        )

    # ----- Activity tracking -----

    async def set_session_activity(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: AgentRunPhase | None = None,
    ) -> None:
        """Record that a session is being processed.

        :param session_id: Session ID
        :param run_id: Run ID
        :param phase: Current agent run phase
        """
        key = _session_activity_key(self._SESSION_PREFIX, session_id)
        value = _session_activity_adapter.dump_json(
            SessionActivity(
                run_id=run_id,
                phase=phase,
            )
        )
        worker_id = self._worker_id
        legacy_value = _legacy_activity_adapter.dump_json(
            {
                "run_id": run_id,
                "phase": phase.value if phase is not None else None,
                "_azents_owner": worker_id or "interface",
            }
        )
        if worker_id is None:

            async def set_interface_activity() -> None:
                migration_authority = await self._redis.get(
                    _session_lock_key(self._SESSION_PREFIX, session_id)
                )
                await self._redis.set(key, value, ex=self._ACTIVITY_TTL)
                await self._redis.set(
                    _session_activity_migration_key(self._SESSION_PREFIX, session_id),
                    migration_authority or "interface",
                    ex=self._ACTIVITY_TTL,
                )
                await self._redis.set(
                    _session_legacy_activity_key(self._SESSION_PREFIX, session_id),
                    legacy_value,
                    ex=self._ACTIVITY_TTL,
                )

            await _run_with_redis_deadline(set_interface_activity)
            return
        legacy_key = _session_legacy_activity_key(self._SESSION_PREFIX, session_id)
        await self._run_best_effort_projection(
            lambda: self._redis.set(
                legacy_key,
                legacy_value,
                ex=self._ACTIVITY_TTL,
            ),
            operation="set legacy Session activity projection",
            session_id=session_id,
        )
        try:
            updated = await _run_with_redis_deadline(
                lambda: self._redis.eval(
                    _SET_ACTIVITY_IF_OWNER_SCRIPT,
                    3,
                    _session_lock_key(self._SESSION_PREFIX, session_id),
                    key,
                    _session_activity_migration_key(self._SESSION_PREFIX, session_id),
                    worker_id,
                    value,
                    str(self._ACTIVITY_TTL),
                )
            )
        except asyncio.CancelledError:
            # The tagged compatibility projection expires quickly and readers
            # reject it after an owner handoff. Preserve caller cancellation
            # instead of delaying stop on cleanup I/O.
            raise
        except TimeoutError, RedisError, OSError:
            await self._delete_legacy_activity_value_best_effort(
                session_id,
                legacy_key=legacy_key,
                legacy_value=legacy_value,
            )
            raise
        if not updated:
            await self._delete_legacy_activity_value_best_effort(
                session_id,
                legacy_key=legacy_key,
                legacy_value=legacy_value,
            )
            raise SessionOwnershipLostError(session_id)

    async def clear_session_activity(self, session_id: str) -> None:
        """Remove session activity.

        :param session_id: Session ID
        """
        key = _session_activity_key(self._SESSION_PREFIX, session_id)
        worker_id = self._worker_id
        if worker_id is None:

            async def clear_interface_activity() -> None:
                migration_authority = await self._redis.get(
                    _session_lock_key(self._SESSION_PREFIX, session_id)
                )
                await self._redis.delete(key)
                await self._redis.delete(
                    _session_legacy_activity_key(self._SESSION_PREFIX, session_id)
                )
                await self._redis.set(
                    _session_activity_migration_key(
                        self._SESSION_PREFIX,
                        session_id,
                    ),
                    migration_authority or "interface",
                    ex=self._ACTIVITY_TTL,
                )

            await _run_with_redis_deadline(clear_interface_activity)
            return
        cleared = await _run_with_redis_deadline(
            lambda: self._redis.eval(
                _CLEAR_ACTIVITY_IF_OWNER_SCRIPT,
                3,
                _session_lock_key(self._SESSION_PREFIX, session_id),
                key,
                _session_activity_migration_key(self._SESSION_PREFIX, session_id),
                worker_id,
                str(self._ACTIVITY_TTL),
            )
        )
        if cleared == -1:
            raise SessionOwnershipLostError(session_id)
        await self._run_best_effort_projection(
            lambda: self._redis.eval(
                _CLEAR_LEGACY_ACTIVITY_IF_OWNER_SCRIPT,
                1,
                _session_legacy_activity_key(self._SESSION_PREFIX, session_id),
                worker_id,
            ),
            operation="clear legacy Session activity projection",
            session_id=session_id,
        )

    async def clear_session_activity_for_run(
        self,
        session_id: str,
        *,
        run_id: str,
    ) -> None:
        """Remove activity when the stored authority still matches one Run.

        :param session_id: Session ID
        :param run_id: Expected Run ID
        """
        key = _session_activity_key(self._SESSION_PREFIX, session_id)
        worker_id = self._worker_id
        if worker_id is None:

            async def clear_interface_run_activity() -> None:
                migration_authority = await self._redis.get(
                    _session_lock_key(self._SESSION_PREFIX, session_id)
                )
                await self._redis.eval(_CLEAR_ACTIVITY_FOR_RUN_SCRIPT, 1, key, run_id)
                await self._redis.eval(
                    _CLEAR_ACTIVITY_FOR_RUN_SCRIPT,
                    1,
                    _session_legacy_activity_key(self._SESSION_PREFIX, session_id),
                    run_id,
                )
                await self._redis.set(
                    _session_activity_migration_key(
                        self._SESSION_PREFIX,
                        session_id,
                    ),
                    migration_authority or "interface",
                    ex=self._ACTIVITY_TTL,
                )

            await _run_with_redis_deadline(clear_interface_run_activity)
            return
        cleared = await _run_with_redis_deadline(
            lambda: self._redis.eval(
                _CLEAR_ACTIVITY_FOR_RUN_IF_OWNER_SCRIPT,
                3,
                _session_lock_key(self._SESSION_PREFIX, session_id),
                key,
                _session_activity_migration_key(self._SESSION_PREFIX, session_id),
                worker_id,
                run_id,
                str(self._ACTIVITY_TTL),
            )
        )
        if cleared == -1:
            raise SessionOwnershipLostError(session_id)
        await self._run_best_effort_projection(
            lambda: self._redis.eval(
                _CLEAR_LEGACY_ACTIVITY_FOR_RUN_IF_OWNER_SCRIPT,
                1,
                _session_legacy_activity_key(self._SESSION_PREFIX, session_id),
                worker_id,
                run_id,
            ),
            operation="clear legacy Session Run activity projection",
            session_id=session_id,
        )

    async def get_session_activity(self, session_id: str) -> SessionActivity | None:
        """Get current execution state for a session.

        :param session_id: Session ID
        :return: SessionActivity when running, otherwise None
        """
        key = _session_activity_key(self._SESSION_PREFIX, session_id)

        async def read_activity() -> SessionActivity | None:
            raw = await self._redis.get(key)
            migration_authority, lock_owner = await self._redis.mget(
                _session_activity_migration_key(self._SESSION_PREFIX, session_id),
                _session_lock_key(self._SESSION_PREFIX, session_id),
            )
            if (
                lock_owner is not None
                and migration_authority is not None
                and migration_authority != lock_owner
            ):
                raw = await self._redis.get(
                    _session_legacy_activity_key(self._SESSION_PREFIX, session_id)
                )
                if raw is None:
                    return None
            if raw is None:
                if migration_authority is not None and (
                    lock_owner is None or migration_authority == lock_owner
                ):
                    return None
                raw = await self._redis.get(
                    _session_legacy_activity_key(self._SESSION_PREFIX, session_id)
                )
            if raw is None:
                return None
            legacy_authority = _legacy_activity_authority(raw)
            if (
                legacy_authority is not None
                and lock_owner is not None
                and legacy_authority != _redis_text(lock_owner)
            ):
                return None
            return _session_activity_adapter.validate_json(raw)

        return await _run_with_redis_deadline(read_activity)

    async def _delete_legacy_activity_value_best_effort(
        self,
        session_id: str,
        *,
        legacy_key: str,
        legacy_value: bytes,
    ) -> None:
        """Remove one exact compatibility projection without masking authority loss."""
        await self._run_best_effort_projection(
            lambda: self._redis.eval(
                _DELETE_IF_VALUE_SCRIPT,
                1,
                legacy_key,
                legacy_value,
            ),
            operation="remove stale legacy Session activity projection",
            session_id=session_id,
        )

    async def _run_best_effort_projection(
        self,
        operation_fn: Callable[[], Awaitable[object]],
        *,
        operation: str,
        session_id: str,
    ) -> None:
        """Hard-bound non-authoritative projection I/O and preserve cancellation."""
        try:
            await _run_with_redis_deadline(operation_fn)
        except asyncio.CancelledError:
            raise
        except TimeoutError, RedisError, OSError:
            logger.exception(
                "Failed to %s",
                operation,
                extra={"session_id": session_id},
            )


def _stream_min_id(retention_seconds: int) -> str:
    """Return the minimum ID for time-based Redis Stream retention."""
    cutoff_ms = max(0, int((time.time() - retention_seconds) * 1000))
    return f"{cutoff_ms}-0"


def _legacy_activity_authority(raw: bytes | str) -> str | None:
    """Read new-writer authority while accepting unversioned legacy payloads."""
    try:
        payload = _legacy_activity_adapter.validate_json(raw)
    except ValidationError:
        return None
    authority = payload.get("_azents_owner")
    return authority if isinstance(authority, str) else None


def _redis_text(value: bytes | str) -> str:
    """Normalize a Redis scalar for authority comparison."""
    return value.decode() if isinstance(value, bytes) else value


def _session_lock_key(prefix: str, session_id: str) -> str:
    return f"{prefix}{{{session_id}}}:lock"


def _session_owner_heartbeat_key(prefix: str, session_id: str) -> str:
    return f"{prefix}{{{session_id}}}:owner-heartbeat"


def _session_activity_key(prefix: str, session_id: str) -> str:
    return f"{prefix}{{{session_id}}}:activity"


def _session_activity_migration_key(prefix: str, session_id: str) -> str:
    return f"{prefix}{{{session_id}}}:activity-migrated"


def _session_legacy_activity_key(prefix: str, session_id: str) -> str:
    return f"{prefix}{session_id}:activity"


def _session_invalid_message_key(prefix: str, session_id: str) -> str:
    return f"{prefix}{{{session_id}}}:invalid-messages"


def _worker_atomic_capability_key(worker_id: str) -> str:
    return f"azents:worker:{worker_id}:broker-v2"


def _worker_stream_key(worker_id: str) -> str:
    return f"azents:worker:{worker_id}:incoming"
