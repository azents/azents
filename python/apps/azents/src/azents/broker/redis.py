"""Redis-based session broker.

Relays messages between interfaces and the engine by combining Redis Streams
for notifications with per-session LISTs for message bodies.

Sticky session: manages worker ownership with per-session Redis locks so the
same worker handles messages for the same session.
"""

import json
import logging
import time
from typing import Any, NamedTuple, cast

from pydantic import TypeAdapter
from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from azents.core.enums import AgentRunPhase

from .types import (
    BrokerMessage,
    PublishedEvent,
    SessionActivity,
    SessionWakeUp,
)

logger = logging.getLogger(__name__)

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

_session_wake_up_adapter = TypeAdapter[SessionWakeUp](SessionWakeUp)


def encode_session_wake_up(message: SessionWakeUp) -> bytes:
    """Serialize SessionWakeUp to JSON bytes."""
    return _session_wake_up_adapter.dump_json(message)


def decode_session_wake_up(raw: bytes) -> SessionWakeUp:
    """Deserialize JSON bytes to SessionWakeUp."""
    _validate_routing_only_payload(raw, expected_type="session_wake_up")
    return _session_wake_up_adapter.validate_json(raw, strict=True)


_broker_message_adapter = TypeAdapter[BrokerMessage](BrokerMessage)
_session_activity_adapter = TypeAdapter[SessionActivity](SessionActivity)


def encode_broker_message(message: BrokerMessage) -> bytes:
    """Serialize BrokerMessage to JSON bytes."""
    return _broker_message_adapter.dump_json(message)


def decode_broker_message(raw: bytes) -> BrokerMessage:
    """Deserialize JSON bytes to BrokerMessage."""
    parsed = _validate_routing_only_payload(raw)
    message_type = parsed["type"]
    if message_type not in {"session_wake_up", "session_stop_signal"}:
        raise ValueError("Unknown broker message type")
    return _broker_message_adapter.validate_json(raw, strict=True)


def _validate_routing_only_payload(
    raw: bytes,
    *,
    expected_type: str | None = None,
) -> dict[str, object]:
    """Reject every broker payload that carries more than routing identity."""
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Broker message is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Broker message must be a JSON object")
    if set(parsed) != {"session_id", "type"}:
        raise ValueError("Broker message must contain only session_id and type")
    if not isinstance(parsed.get("session_id"), str):
        raise ValueError("Broker message session_id must be a string")
    message_type = parsed.get("type")
    if not isinstance(message_type, str):
        raise ValueError("Broker message type must be a string")
    if expected_type is not None and message_type != expected_type:
        raise ValueError("Unexpected broker message type")
    return parsed


class _WakeUp(NamedTuple):
    stream_name: bytes | str
    entry_id: bytes | str
    session_id: str


class _Ownership(NamedTuple):
    status: str
    owner: str


class RedisBroker:
    """Redis-based session broker.

    - Incoming notifications: Redis Stream ``azents:incoming`` with session_id only
    - Message bodies: per-session Redis List ``azents:session:{session_id}:messages``
    - Session ownership: Redis String ``azents:session:{session_id}:lock`` with TTL 30m
    - owner heartbeat: Redis String
      ``azents:session:{session_id}:owner-heartbeat`` with TTL 120s
    """

    _STREAM_KEY = "azents:incoming"
    _GROUP_NAME = "engine-workers"
    _SESSION_PREFIX = "azents:session:"
    _RECEIVE_BLOCK_MS = 100
    _SESSION_TTL = 30 * 60  # seconds
    _OWNER_HEARTBEAT_TTL = 120  # seconds
    _ACTIVITY_TTL = 30  # seconds; TTL expiry cleans up after crashes
    _MESSAGE_TTL = 24 * 60 * 60  # seconds
    _INCOMING_RETENTION = 6 * 60 * 60  # seconds

    def __init__(self, redis: Redis, *, worker_id: str | None = None) -> None:
        self._redis = redis
        self._worker_id = worker_id

    async def setup(self) -> None:
        """Create the consumer group once.

        Ignore it when already present. MKSTREAM also creates the stream if missing.
        """
        await self._ensure_stream_group(self._STREAM_KEY)
        if self._worker_id is not None:
            await self._ensure_stream_group(_worker_stream_key(self._worker_id))

    async def _ensure_stream_group(self, stream_key: str) -> None:
        """Create the Stream consumer group if it does not exist."""
        try:
            await self._redis.xgroup_create(
                stream_key,
                self._GROUP_NAME,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if not str(exc).startswith(_BUSYGROUP_PREFIX):
                raise

    # ----- Interface side -----

    async def send_message(self, message: BrokerMessage) -> None:
        """Store a message in the per-session LIST and publish notification.

        :param message: Broker message to send
        """
        encoded = encode_broker_message(message)
        msg_key = f"{self._SESSION_PREFIX}{message.session_id}:messages"
        await self._redis.rpush(msg_key, encoded)
        await self._redis.expire(msg_key, self._MESSAGE_TTL)
        try:
            await self._publish_wake_up(message.session_id)
        except RedisError:
            await self._redis.lrem(  # pyright: ignore[reportAttributeAccessIssue]  # redis-py stub omits LREM.
                msg_key,
                1,
                encoded,
            )
            raise

    async def _publish_wake_up(self, session_id: str) -> None:
        """Wake the owner stream when there is a live owner."""
        redis_any = cast(Any, self._redis)
        owner = await redis_any.eval(
            _ROUTE_WAKE_SCRIPT,
            2,
            _session_lock_key(self._SESSION_PREFIX, session_id),
            _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id),
        )
        stream_key = (
            _worker_stream_key(owner.decode() if isinstance(owner, bytes) else owner)
            if owner
            else self._STREAM_KEY
        )
        await self._redis.xadd(
            stream_key,
            {"session_id": session_id},
            minid=_stream_min_id(self._INCOMING_RETENTION),
            approximate=False,
        )

    # ----- Engine side -----

    async def receive_messages(self) -> list[BrokerMessage]:
        """Receive notification, verify session ownership, and drain queued messages.

        1. Receive notification with session_id from the global stream by XREADGROUP
        2. Try session lock with SET NX
        3. If owned by this worker, drain per-session LIST until the queue is empty
        4. If owned by another worker, reinsert notification and retry

        :return: Received broker messages, at least one
        """
        assert self._worker_id is not None, "worker_id is required"
        while True:
            wake_up = await self._read_wake_up()
            await self._redis.xack(
                wake_up.stream_name,
                self._GROUP_NAME,
                wake_up.entry_id,
            )

            session_id = wake_up.session_id
            ownership = await self._acquire_or_find_owner(session_id)
            if ownership.status == "live_owner":
                await self._redis.xadd(
                    _worker_stream_key(ownership.owner),
                    {"session_id": session_id},
                    minid=_stream_min_id(self._INCOMING_RETENTION),
                    approximate=False,
                )
                continue

            # Drain per-session LIST until the queue is empty
            msg_key = f"{self._SESSION_PREFIX}{session_id}:messages"
            messages: list[BrokerMessage] = []
            while True:
                raw = await self._redis.lpop(msg_key)
                if raw is None:
                    break
                messages.append(decode_broker_message(raw))

            if not messages:
                # Duplicate notification; message was already consumed
                continue

            return messages

    async def _read_wake_up(self) -> _WakeUp:
        """Read worker direct and global streams alternately in a cluster-safe way."""
        assert self._worker_id is not None, "worker_id is required"
        stream_keys = (_worker_stream_key(self._worker_id), self._STREAM_KEY)
        while True:
            for stream_key in stream_keys:
                wake_up = await self._try_read_wake_up(stream_key)
                if wake_up is not None:
                    return wake_up

    async def _try_read_wake_up(self, stream_key: str) -> _WakeUp | None:
        """Read one wake-up from a single Redis Stream.

        Redis Cluster requires every key in one command to share the same hash slot.
        Worker direct stream and global stream can be in different slots, so each is
        read with a separate XREADGROUP command.

        :param stream_key: Redis Stream key to read
        :return: Matching entry when a wake-up exists, otherwise None
        """
        assert self._worker_id is not None, "worker_id is required"
        try:
            results = await self._redis.xreadgroup(
                self._GROUP_NAME,
                self._worker_id,
                {stream_key: ">"},
                count=1,
                block=self._RECEIVE_BLOCK_MS,
            )
        except ResponseError as exc:
            if not str(exc).startswith(_NOGROUP_PREFIX):
                raise
            logger.warning(
                "Redis stream group missing; recreating",
                extra={"stream_key": stream_key, "consumer_group": self._GROUP_NAME},
            )
            await self._ensure_stream_group(stream_key)
            return None
        if not results:
            return None

        stream_name, entries = results[0]
        entry_id, fields = entries[0]
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
        assert self._worker_id is not None, "worker_id is required"
        redis_any = cast(Any, self._redis)
        result = await redis_any.eval(
            _ACQUIRE_LOCK_SCRIPT,
            2,
            _session_lock_key(self._SESSION_PREFIX, session_id),
            _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id),
            self._worker_id,
            str(self._SESSION_TTL),
            str(self._OWNER_HEARTBEAT_TTL),
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
        """Refresh owner lock, owner heartbeat, and activity TTLs.

        :param session_id: Target session ID
        """
        if self._worker_id is None:
            return
        lock_key = _session_lock_key(self._SESSION_PREFIX, session_id)
        heartbeat_key = _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id)
        redis_any = cast(Any, self._redis)
        await redis_any.eval(
            _RENEW_LEASE_SCRIPT,
            2,
            lock_key,
            heartbeat_key,
            self._worker_id,
            str(self._SESSION_TTL),
            str(self._OWNER_HEARTBEAT_TTL),
        )
        activity_key = f"{self._SESSION_PREFIX}{session_id}:activity"
        await self._redis.expire(activity_key, self._ACTIVITY_TTL)

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """Refresh only the sticky owner heartbeat.

        :param session_id: Session ID
        """
        if self._worker_id is None:
            return
        redis_any = cast(Any, self._redis)
        await redis_any.eval(
            _RENEW_HEARTBEAT_SCRIPT,
            2,
            _session_lock_key(self._SESSION_PREFIX, session_id),
            _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id),
            self._worker_id,
            str(self._OWNER_HEARTBEAT_TTL),
        )

    async def release_session_lock(self, session_id: str) -> None:
        """Release session lock.

        :param session_id: Session ID to release
        """
        lock_key = _session_lock_key(self._SESSION_PREFIX, session_id)
        heartbeat_key = _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id)
        if self._worker_id is None:
            await self._redis.delete(lock_key, heartbeat_key)
            return
        redis_any = cast(Any, self._redis)
        await redis_any.eval(
            _RELEASE_LOCK_SCRIPT,
            2,
            lock_key,
            heartbeat_key,
            self._worker_id,
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
        key = f"{self._SESSION_PREFIX}{session_id}:activity"
        value = _session_activity_adapter.dump_json(
            SessionActivity(
                run_id=run_id,
                phase=phase,
            )
        )
        await self._redis.set(key, value, ex=self._ACTIVITY_TTL)

    async def clear_session_activity(self, session_id: str) -> None:
        """Remove session activity.

        :param session_id: Session ID
        """
        key = f"{self._SESSION_PREFIX}{session_id}:activity"
        await self._redis.delete(key)

    async def get_session_activity(self, session_id: str) -> SessionActivity | None:
        """Get current execution state for a session.

        :param session_id: Session ID
        :return: SessionActivity when running, otherwise None
        """
        key = f"{self._SESSION_PREFIX}{session_id}:activity"
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return _session_activity_adapter.validate_json(raw)

    async def purge_session_state(self, session_id: str) -> None:
        """Delete all ephemeral broker state owned by one Session."""
        await self._redis.delete(f"{self._SESSION_PREFIX}{session_id}:messages")
        await self._redis.delete(
            _session_lock_key(self._SESSION_PREFIX, session_id),
            _session_owner_heartbeat_key(self._SESSION_PREFIX, session_id),
        )
        await self._redis.delete(f"{self._SESSION_PREFIX}{session_id}:activity")


def _stream_min_id(retention_seconds: int) -> str:
    """Return the minimum ID for time-based Redis Stream retention."""
    cutoff_ms = max(0, int((time.time() - retention_seconds) * 1000))
    return f"{cutoff_ms}-0"


def _session_lock_key(prefix: str, session_id: str) -> str:
    return f"{prefix}{{{session_id}}}:lock"


def _session_owner_heartbeat_key(prefix: str, session_id: str) -> str:
    return f"{prefix}{{{session_id}}}:owner-heartbeat"


def _worker_stream_key(worker_id: str) -> str:
    return f"azents:worker:{worker_id}:incoming"
