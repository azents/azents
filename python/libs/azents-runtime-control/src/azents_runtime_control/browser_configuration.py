"""Closed browser configuration intent and current Runner evidence."""

import enum
from dataclasses import dataclass
from typing import Literal

from azents_runtime_control.browser_contract import BrowserContractError
from azents_runtime_control.runner import JsonValue

BROWSER_CONFIGURATION_CAPABILITY = "browser.configuration"


class BrowserImplementation(enum.StrEnum):
    """Packaged product browsers; never an executable or profile override."""

    PATCHRIGHT = "patchright"
    CAMOUFOX = "camoufox"


type BrowserApplicationState = Literal["unconfigured", "applying", "ready", "failed"]


@dataclass(frozen=True)
class BrowserConfigurationRequest:
    intent_id: str
    expected_intent_id: str | None
    implementation: BrowserImplementation


@dataclass(frozen=True)
class BrowserConfigurationStatus:
    intent_id: str | None
    implementation: BrowserImplementation | None
    state: BrowserApplicationState
    reason_code: str | None


def _identity(value: object, *, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise BrowserContractError("Invalid browser configuration identity")
    if not all(
        character.isascii() and (character.isalnum() or character in "-_")
        for character in value
    ):
        raise BrowserContractError("Invalid browser configuration identity")
    return value


def decode_browser_configuration(value: object) -> BrowserConfigurationRequest:
    if not isinstance(value, dict) or set(value) != {
        "intent_id",
        "expected_intent_id",
        "implementation",
    }:
        raise BrowserContractError("Invalid browser configuration fields")
    intent = _identity(value["intent_id"], nullable=False)
    assert intent is not None
    implementation = value["implementation"]
    if not isinstance(implementation, str):
        raise BrowserContractError("Invalid browser implementation")
    try:
        selected = BrowserImplementation(implementation)
    except ValueError:
        raise BrowserContractError("Unsupported browser implementation") from None
    return BrowserConfigurationRequest(
        intent, _identity(value["expected_intent_id"], nullable=True), selected
    )


def encode_browser_configuration(
    request: BrowserConfigurationRequest,
) -> dict[str, JsonValue]:
    return {
        "intent_id": request.intent_id,
        "expected_intent_id": request.expected_intent_id,
        "implementation": request.implementation.value,
    }


def encode_browser_configuration_status(
    status: BrowserConfigurationStatus,
) -> dict[str, JsonValue]:
    return {
        "intent_id": status.intent_id,
        "implementation": status.implementation,
        "state": status.state,
        "reason_code": status.reason_code,
    }


def decode_browser_configuration_status(value: object) -> BrowserConfigurationStatus:
    if not isinstance(value, dict) or set(value) != {
        "intent_id",
        "implementation",
        "state",
        "reason_code",
    }:
        raise BrowserContractError("Invalid browser configuration status fields")
    intent = _identity(value["intent_id"], nullable=True)
    implementation = value["implementation"]
    if implementation is not None and not isinstance(implementation, str):
        raise BrowserContractError("Invalid applied browser implementation")
    try:
        selected = (
            None if implementation is None else BrowserImplementation(implementation)
        )
    except ValueError:
        raise BrowserContractError(
            "Unsupported applied browser implementation"
        ) from None
    state = value["state"]
    reason = _identity(value["reason_code"], nullable=True)
    match state:
        case "unconfigured":
            if intent is not None or selected is not None or reason is not None:
                raise BrowserContractError("Inconsistent unconfigured browser evidence")
        case "applying" | "ready" | "failed":
            if (
                intent is None
                or selected is None
                or (state == "failed") != (reason is not None)
            ):
                raise BrowserContractError("Inconsistent browser application evidence")
        case _:
            raise BrowserContractError("Invalid browser application state")
    return BrowserConfigurationStatus(intent, selected, state, reason)
