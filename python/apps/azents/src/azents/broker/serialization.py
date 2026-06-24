"""Event serialization/deserialization.

Converts EngineEvent and event objects to dicts or restores them from dicts.
Used for Redis Pub/Sub message delivery and WebSocket wire format.

Unified by directly calling Pydantic ``model_dump`` / ``model_validate``.
Do not add case-by-case conversion code.

Wire format:
    - Event → ``Event.model_dump(mode="json")``
    - EngineEvent → ``TypeAdapter(EngineEvent).dump_python(event, mode="json")``
      (top-level ``type`` discriminator)

Dispatch treats wire dicts with ``kind``/``payload`` keys as event, rejects
``item`` keys as legacy envelopes, and validates all others as EngineEvent.
"""

from pydantic import TypeAdapter

from azents.engine.events.engine_events import EngineEvent
from azents.engine.events.types import Event
from azents.transport.chat import chat_event_transport_dump

# Build the EngineEvent discriminated union only once.
_engine_event_adapter: TypeAdapter[EngineEvent] = TypeAdapter(EngineEvent)


def serialize_event(event: EngineEvent | Event) -> dict[str, object]:
    """Serialize EngineEvent or event to a wire dict.

    :param event: Engine event or durable event to serialize
    :return: JSON-serializable dict
    """
    if isinstance(event, Event):
        return chat_event_transport_dump(event)
    dumped = _engine_event_adapter.dump_python(event, mode="json")
    if not isinstance(dumped, dict):
        raise TypeError("Serialized engine event must be a dict")
    return {str(key): value for key, value in dumped.items()}


def deserialize_event(data: dict[str, object]) -> EngineEvent | Event:
    """Restore an event from a wire dict.

    Distinguish event, legacy, and engine payloads by presence of
    ``kind``/``payload`` or ``item`` keys.

    :param data: Serialized event dict
    :return: Restored event
    """
    if "kind" in data and "payload" in data:
        return Event.model_validate(data)
    if "item" in data:
        raise ValueError("Legacy event envelope is not supported")
    return _engine_event_adapter.validate_python(data)
