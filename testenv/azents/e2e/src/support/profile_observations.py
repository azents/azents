"""Typed fixture observations for prepared inference-profile E2E journeys.

Generated models own public API responses. These projections own only the
provider-fixture fields interpreted by the journeys. Provider content and
extension fields remain opaque JSON; serialization is solely for journal
correlation and deliberate provider-wire assertions.
"""

from __future__ import annotations

import json

from azentspublicclient.models.chat_event_page_response import ChatEventPageResponse
from azentspublicclient.models.chat_event_response import ChatEventResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
)

from support.observations import decode_history_page


class ProfileObservation(BaseModel):
    """Forward-compatible fixture evidence without primitive coercion."""

    model_config = ConfigDict(extra="allow", frozen=True)


class ProviderReasoningObservation(ProfileObservation):
    """Wire reasoning effort, with meaningful absent/null distinction."""

    effort: StrictStr | None = None


class ProfileProviderRequestObservation(ProfileObservation):
    """Provider request identity, limits, and actual requested processing tier."""

    model: StrictStr | None = None
    service_tier: StrictStr | None = None
    max_tokens: StrictInt | None = None
    max_output_tokens: StrictInt | None = None
    reasoning: ProviderReasoningObservation | None = None
    input: JsonValue = None
    messages: JsonValue = None

    def serialized(self) -> str:
        """Serialize the retained wire envelope for transparent correlation."""
        return json.dumps(
            self.model_dump(mode="json", exclude_unset=True), ensure_ascii=False
        )


class MockProfileRequestObservation(ProfileObservation):
    """Mock provider journal entry with its operation-specific request body."""

    body: ProfileProviderRequestObservation


class ProfileBarrierObservation(ProfileObservation):
    """Authoritative provider stream barrier readiness."""

    reached: StrictBool


class CatalogSourceObservation(ProfileObservation):
    """Acknowledged fixture model-catalog source variant."""

    variant: StrictStr


_PROVIDER_REQUESTS = TypeAdapter(list[ProfileProviderRequestObservation])
_MOCK_REQUESTS = TypeAdapter(list[MockProfileRequestObservation])


def decode_profile_history(value: object) -> ChatEventPageResponse:
    """Decode shared generated history defaults and retained wire extensions."""
    return decode_history_page(value)


def profile_history_event_wire(event: ChatEventResponse) -> dict[str, object]:
    """Serialize typed history at the legacy helper/output-evidence boundary.

    JSON-mode dumping encodes timestamps; generated additional properties are
    flattened explicitly so the egress retains unknown wire envelope evidence.
    """
    wire = event.model_dump(
        mode="json", exclude_unset=True, exclude={"additional_properties"}
    )
    wire.update(event.additional_properties)
    return wire


def decode_profile_provider_journal(
    value: object,
) -> list[ProfileProviderRequestObservation]:
    """Validate interpreted provider identities once, retaining opaque bodies."""
    return _PROVIDER_REQUESTS.validate_python(value)


def decode_mock_profile_journal(value: object) -> list[MockProfileRequestObservation]:
    """Validate mock request envelopes before selecting model/output caps."""
    return _MOCK_REQUESTS.validate_python(value)
