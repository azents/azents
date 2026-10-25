"""Bounded Browser-only representation for the Runner protobuf transport."""

import json
from dataclasses import dataclass

from azents_runtime_control.browser_configuration import (
    decode_browser_configuration,
    decode_browser_configuration_status,
    encode_browser_configuration,
    encode_browser_configuration_status,
)
from azents_runtime_control.browser_contract import (
    BrowserCommand,
    BrowserContractError,
    decode_browser_command,
    decode_browser_result,
    encode_browser_command,
    encode_browser_result,
)
from azents_runtime_control.runner import JsonValue

BROWSER_RUNNER_MAX_PAYLOAD_BYTES = 1 << 20


@dataclass(frozen=True)
class ConfiguredBrowserCommand:
    intent_id: str
    command: BrowserCommand


def encode_configured_browser_command(
    intent_id: str, command: BrowserCommand
) -> dict[str, JsonValue]:
    return {"intent_id": intent_id, "command": encode_browser_command(command)}


def decode_configured_browser_command(
    operation_type: str, payload: object
) -> ConfiguredBrowserCommand:
    if not isinstance(payload, dict) or set(payload) != {"intent_id", "command"}:
        raise BrowserContractError("Invalid configured Browser command fields")
    intent = payload["intent_id"]
    if not isinstance(intent, str) or not 1 <= len(intent) <= 128:
        raise BrowserContractError("Invalid Browser configuration intent")
    return ConfiguredBrowserCommand(
        intent, decode_browser_command(operation_type, payload["command"])
    )


def _canonical_command(operation_type: str, payload: object) -> dict[str, JsonValue]:
    match operation_type:
        case "browser.configure":
            return encode_browser_configuration(decode_browser_configuration(payload))
        case "browser.configuration_status":
            if payload != {}:
                raise BrowserContractError("Browser configuration status has no fields")
            return {}
        case _:
            configured = decode_configured_browser_command(operation_type, payload)
            return encode_configured_browser_command(
                configured.intent_id, configured.command
            )


def browser_command_to_wire(operation_type: str, payload: object) -> bytes:
    """Validate a closed command before emitting canonical transport bytes."""
    return _encode(_canonical_command(operation_type, payload))


def browser_command_from_wire(
    operation_type: str, payload: bytes
) -> dict[str, JsonValue]:
    """Validate incoming bytes before returning the canonical command shape."""
    return _canonical_command(operation_type, _decode(payload))


def _canonical_result(payload: object) -> dict[str, JsonValue]:
    if isinstance(payload, dict) and "browser_configuration" in payload:
        if set(payload) != {"browser_configuration"}:
            raise BrowserContractError("Unexpected Browser configuration result fields")
        return {
            "browser_configuration": encode_browser_configuration_status(
                decode_browser_configuration_status(payload["browser_configuration"])
            )
        }
    return encode_browser_result(decode_browser_result(payload))


def browser_result_to_wire(payload: object) -> bytes:
    """Validate a completed result before emitting canonical transport bytes."""
    return _encode(_canonical_result(payload))


def browser_result_from_wire(payload: bytes) -> dict[str, JsonValue]:
    """Validate incoming bytes before returning the completed result shape."""
    return _canonical_result(_decode(payload))


def _encode(payload: dict[str, JsonValue]) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        ).encode("utf-8")
    except UnicodeEncodeError as error:
        raise BrowserContractError("Malformed Browser Runner payload text") from error
    _check_size(encoded)
    return encoded


def _check_size(payload: bytes) -> None:
    if not payload or len(payload) > BROWSER_RUNNER_MAX_PAYLOAD_BYTES:
        raise BrowserContractError("Browser Runner payload size is invalid")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BrowserContractError("Duplicate Browser Runner payload field")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise BrowserContractError("Nonfinite Browser Runner payload number")


def _decode(payload: bytes) -> object:
    _check_size(payload)
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise BrowserContractError("Malformed Browser Runner payload") from error
