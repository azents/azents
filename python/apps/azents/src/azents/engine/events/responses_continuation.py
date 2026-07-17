"""In-memory planning for Responses API continuation requests."""

import copy
import dataclasses
from collections.abc import Mapping, Sequence
from typing import Protocol


class ResponsesContinuationRequest(Protocol):
    """Logical Responses request surface needed by continuation planning."""

    def continuation_input_items(self) -> list[dict[str, object]]:
        """Return the complete logical input sequence."""
        ...

    def continuation_properties(self) -> object:
        """Return every non-input semantic request property."""
        ...

    def continuation_store_enabled(self) -> bool:
        """Return whether stored-response continuation is allowed."""
        ...


@dataclasses.dataclass(frozen=True)
class ResponsesContinuationPlan:
    """Physical Responses input derived from one full logical request."""

    input_items: list[dict[str, object]]
    previous_response_id: str | None


@dataclasses.dataclass(frozen=True)
class _ResponsesContinuationState:
    """Last successfully completed request and response boundary."""

    input_items: list[dict[str, object]]
    properties: object
    response_id: str
    output_items: list[dict[str, object]]


class ResponsesContinuationPlanner:
    """Plan safe incremental input within one model adapter lifetime."""

    def __init__(self) -> None:
        self._state: _ResponsesContinuationState | None = None
        self._disabled = False

    def plan(self, request: ResponsesContinuationRequest) -> ResponsesContinuationPlan:
        """Return incremental input only when the prior boundary matches exactly."""
        request_input = request.continuation_input_items()
        comparison_input = _sanitize_responses_input_items(request_input)
        full_plan = ResponsesContinuationPlan(
            input_items=request_input,
            previous_response_id=None,
        )
        if self._disabled or not request.continuation_store_enabled():
            return full_plan

        state = self._state
        if state is None or state.properties != request.continuation_properties():
            return full_plan

        previous_input_count = len(state.input_items)
        if comparison_input[:previous_input_count] != state.input_items:
            return full_plan

        output_end = previous_input_count + len(state.output_items)
        if comparison_input[previous_input_count:output_end] != state.output_items:
            return full_plan

        delta = request_input[output_end:]
        if not delta:
            return full_plan
        return ResponsesContinuationPlan(
            input_items=delta,
            previous_response_id=state.response_id,
        )

    def record_completion(
        self,
        request: ResponsesContinuationRequest,
        *,
        response_id: str,
        output_items: Sequence[Mapping[str, object]],
    ) -> None:
        """Commit a completed provider response as the next continuation boundary."""
        if (
            self._disabled
            or not request.continuation_store_enabled()
            or not response_id
        ):
            self._state = None
            return
        self._state = _ResponsesContinuationState(
            input_items=copy.deepcopy(
                _sanitize_responses_input_items(request.continuation_input_items())
            ),
            properties=copy.deepcopy(request.continuation_properties()),
            response_id=response_id,
            output_items=copy.deepcopy(
                [sanitize_responses_native_item(dict(item)) for item in output_items]
            ),
        )

    def reset(self) -> None:
        """Discard the prior boundary before starting a new provider call."""
        self._state = None

    def disable(self) -> None:
        """Disable continuation after the provider rejects stored response state."""
        self._disabled = True
        self._state = None


def _sanitize_responses_input_items(
    items: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Sanitize request-local blob fields only for continuation comparison."""
    return [sanitize_responses_native_item(dict(item)) for item in items]


def sanitize_responses_native_item(
    item: dict[str, object],
) -> dict[str, object]:
    """Remove raw blob fields from a Responses native item."""
    item_type = item.get("type")
    sanitized: dict[str, object] = {}
    for key, value in item.items():
        if item_type == "image_generation_call" and key == "result":
            continue
        if item_type == "reasoning" and key == "output_index":
            continue
        if _raw_blob_key(key):
            continue
        sanitized[key] = _sanitize_responses_native_value(value)
    return sanitized


def _sanitize_responses_native_value(value: object) -> object:
    """Remove raw blob fields from nested Responses native values."""
    if isinstance(value, dict):
        return sanitize_responses_native_item(value)
    if isinstance(value, list):
        return [_sanitize_responses_native_value(item) for item in value]
    return value


def _raw_blob_key(key: str) -> bool:
    """Return whether a native artifact key contains a raw blob."""
    return key in {"file_data", "base64", "data_base64", "provider_payload"}
