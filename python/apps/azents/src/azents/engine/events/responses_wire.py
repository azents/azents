"""Compatibility-preserving typed projections of native Responses wire values."""

from dataclasses import dataclass
from typing import Self

from azents.core.type_guards import is_string_object_dict


def response_object(value: object) -> dict[str, object]:
    """Keep provider extensions opaque while requiring string-keyed objects."""
    return value if is_string_object_dict(value) else {}


def response_integer(value: object) -> int | None:
    """Retain the native contract: no string coercion or boolean counters."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parts_text(value: object) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for raw in value:
        text = response_object(raw).get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


@dataclass(frozen=True)
class ResponseOutputItem:
    """Consumed output fields plus opaque replay/provider-decoder evidence."""

    raw: dict[str, object]
    type: str
    has_type: bool
    output_index: int | None
    call_id: str
    name: str
    arguments: str
    custom_call_id: str | None
    custom_name: str | None
    custom_input: str | None
    text: str
    reasoning_text: str | None
    reasoning_summary: str | None

    @classmethod
    def decode(cls, value: object) -> Self:
        """Preserve legacy function-call coercion and strict custom-call input.

        Unknown item kinds and fields remain opaque native artifacts. Missing and
        null fields use the existing empty projections, not a stricter protocol.
        """
        raw = response_object(value)
        kind = raw.get("type")
        call_id = raw.get("call_id") or raw.get("id")
        name = raw.get("name")
        custom_input = raw.get("input")
        return cls(
            raw=raw,
            type=str(kind or ""),
            has_type=isinstance(kind, str) and bool(kind),
            output_index=response_integer(raw.get("output_index")),
            call_id=str(call_id or ""),
            name=str(name or ""),
            arguments=str(raw.get("arguments") or ""),
            custom_call_id=call_id if isinstance(call_id, str) and call_id else None,
            custom_name=name if isinstance(name, str) and name else None,
            custom_input=custom_input if isinstance(custom_input, str) else None,
            text=_parts_text(raw.get("content")),
            reasoning_text=_parts_text(raw.get("content")) or None,
            reasoning_summary=_parts_text(raw.get("summary")) or None,
        )


@dataclass(frozen=True)
class CompletedResponse:
    """Completion/continuation decisions decoded separately from opaque billing."""

    raw: dict[str, object]
    output: tuple[object, ...]
    end_turn: bool | None
    usage: dict[str, object]
    service_tier: str | None
    hidden_params: object

    @classmethod
    def decode(cls, value: object) -> Self:
        raw = response_object(value)
        output = raw.get("output")
        end_turn = raw.get("end_turn")
        tier = raw.get("service_tier")
        return cls(
            raw=raw,
            output=tuple(output) if isinstance(output, list) else (),
            end_turn=end_turn if isinstance(end_turn, bool) else None,
            usage=response_object(raw.get("usage")),
            service_tier=tier if isinstance(tier, str) else None,
            hidden_params=raw.get("_hidden_params"),
        )


@dataclass(frozen=True)
class ResponseStreamFrame:
    """Native stream fields used for incremental semantic decisions."""

    raw: dict[str, object]
    output_item: ResponseOutputItem
    response: CompletedResponse
    delta: str
    output_index: int | None
    summary_index: int | None
    item_id: str | None

    @classmethod
    def decode(cls, raw: dict[str, object]) -> Self:
        item_id = raw.get("item_id")
        return cls(
            raw=raw,
            output_item=ResponseOutputItem.decode(raw.get("item")),
            response=CompletedResponse.decode(raw.get("response")),
            delta=str(raw.get("delta", "")),
            output_index=response_integer(raw.get("output_index")),
            summary_index=response_integer(raw.get("summary_index")),
            item_id=item_id if isinstance(item_id, str) else None,
        )
