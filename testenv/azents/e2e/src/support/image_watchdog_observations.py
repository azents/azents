"""Typed decision fields for image-generation and watchdog fixture evidence."""

from __future__ import annotations

import json

from azentspublicclient.models.chat_live_run_operation_response import (
    ChatLiveRunOperationResponse,
)
from pydantic import JsonValue, StrictInt, StrictStr, TypeAdapter, model_validator
from typing_extensions import Self

from support.observations import (
    ChatActionObservation,
    ExtensionObservation,
    FailedAttemptObservation,
    HistoryEventObservation,
)


class ContentObservation(ExtensionObservation):
    """Event content remains opaque except where a string is explicitly selected."""

    content: JsonValue = None


class AssistantContentObservation(ExtensionObservation):
    """Canonical assistant strings or opaque structured OutputContentPart lists."""

    content: StrictStr | list[dict[str, JsonValue]]


class WatchdogRetryObservation(ExtensionObservation):
    """Interpreted retry evidence under the Event wire's null omission."""

    failed_attempt_count: StrictInt
    error_kind: StrictStr
    attempts: list[FailedAttemptObservation]


class WatchdogRunObservation(ExtensionObservation):
    """Nullable run projections preserve the public null-omitting Event wire."""

    retry: WatchdogRetryObservation | None = None
    operation: ChatLiveRunOperationResponse | None = None


class WatchdogPartialObservation(ExtensionObservation):
    items: list[HistoryEventObservation]


class WatchdogLiveObservation(ExtensionObservation):
    partial_history: WatchdogPartialObservation
    run: WatchdogRunObservation | None = None
    session_run_state: StrictStr


class WatchdogActionObservation(ChatActionObservation):
    event_id: StrictStr | None = None
    run: WatchdogRunObservation | None = None

    @model_validator(mode="after")
    def validate_watchdog_variant(self) -> Self:
        if self.type == "live_event_upserted" and self.event is None:
            raise ValueError("Live event upsert requires event")
        if self.type == "live_event_removed" and self.event_id is None:
            raise ValueError("Live event removal requires event_id")
        if self.type == "live_run_updated" and self.run is None:
            raise ValueError("Live run update requires run")
        return self


class RequestFormatObservation(ExtensionObservation):
    type: StrictStr


class RequestTextObservation(ExtensionObservation):
    format: RequestFormatObservation | None = None


class RequestContentObservation(ExtensionObservation):
    type: StrictStr
    text: StrictStr | None = None


class RequestInputObservation(ExtensionObservation):
    role: StrictStr | None = None
    type: StrictStr | None = None
    content: StrictStr | list[RequestContentObservation] | None = None


class RequestToolObservation(ExtensionObservation):
    type: StrictStr
    name: StrictStr | None = None


class ImageRequestObservation(ExtensionObservation):
    """Interpret request selection fields; preserve provider extensions verbatim."""

    model: StrictStr | None = None
    input: StrictStr | list[RequestInputObservation] | None = None
    tools: list[RequestToolObservation] | None = None
    text: RequestTextObservation | None = None

    def serialized(self) -> str:
        return json.dumps(self.model_dump(mode="json", exclude_unset=True))


_IMAGE_REQUESTS = TypeAdapter(list[ImageRequestObservation])


def decode_image_requests(value: object) -> list[ImageRequestObservation]:
    return _IMAGE_REQUESTS.validate_python(value)


class ImageOutputObservation(ExtensionObservation):
    """Fields of one materialized model-file or attachment output part."""

    type: StrictStr | None = None
    model_file_id: StrictStr | None = None
    kind: StrictStr | None = None
    media_type: StrictStr | None = None
    availability: StrictStr | None = None
    size: StrictInt | None = None
    uri: StrictStr | None = None
    attachment_id: StrictStr | None = None


class ImageResultObservation(ExtensionObservation):
    call_id: StrictStr
    name: StrictStr
    status: StrictStr
    output: list[ImageOutputObservation]


class RequestNodeObservation(ExtensionObservation):
    """Validate the one decision field used by nested provider-wire counting."""

    type: StrictStr | None = None
