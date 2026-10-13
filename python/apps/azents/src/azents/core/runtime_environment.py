"""Typed Agent Runtime environment editing and secret validation."""

import enum
import re
from typing import Annotated, Literal, assert_never

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
)

_ENV_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\Z")
_MAX_ENTRY_COUNT = 50
_MAX_NAME_BYTES = 64
_MAX_VALUE_BYTES = 4096
_MAX_PAYLOAD_BYTES = 100 * 1024


class StoredRuntimeEnvironmentValue(BaseModel):
    """Retain an existing secret by its exact persisted variable name."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal["stored"]
    name: str


class ReplacementRuntimeEnvironmentValue(BaseModel):
    """Explicit replacement, including a valid empty environment value."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal["replace"]
    value: SecretStr


class RuntimeEnvironmentEntryEdit(BaseModel):
    """One desired entry with an explicit retain or replacement operation."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: str
    value: Annotated[
        StoredRuntimeEnvironmentValue | ReplacementRuntimeEnvironmentValue,
        Field(discriminator="type"),
    ]


class InvalidRuntimeEnvironment(ValueError):
    """Safe validation error containing no secret value."""


class RuntimeEnvironmentAccessError(enum.StrEnum):
    """Bounded Agent settings access failures."""

    NOT_FOUND = "not_found"
    DENIED = "denied"


_values_adapter = TypeAdapter[dict[str, str]](dict[str, str])


def validate_runtime_environment(values: dict[str, str]) -> None:
    """Validate OS-safe names and UTF-8 limits without including values in errors."""
    if len(values) > _MAX_ENTRY_COUNT:
        raise InvalidRuntimeEnvironment("At most 50 environment variables are allowed.")
    size = 0
    for name, value in values.items():
        if not _ENV_NAME_RE.fullmatch(name) or len(name.encode()) > _MAX_NAME_BYTES:
            raise InvalidRuntimeEnvironment(
                "Variable names must be POSIX names of at most 64 bytes."
            )
        try:
            value_size = len(value.encode())
        except UnicodeEncodeError:
            raise InvalidRuntimeEnvironment(
                "Variable values must be valid UTF-8."
            ) from None
        if "\0" in value or value_size > _MAX_VALUE_BYTES:
            raise InvalidRuntimeEnvironment(
                "Variable values must be NUL-free and at most 4096 UTF-8 bytes."
            )
        size += len(name.encode()) + value_size
    if size > _MAX_PAYLOAD_BYTES:
        raise InvalidRuntimeEnvironment(
            "Environment variables exceed the 100 KiB total limit."
        )


def merge_runtime_environment(
    existing: dict[str, str], edits: list[RuntimeEnvironmentEntryEdit]
) -> dict[str, str]:
    """Build the desired map, deleting absent names and retaining referenced secrets."""
    if len(edits) > _MAX_ENTRY_COUNT:
        raise InvalidRuntimeEnvironment("At most 50 environment variables are allowed.")
    desired: dict[str, str] = {}
    retained: set[str] = set()
    for entry in edits:
        if entry.name in desired:
            raise InvalidRuntimeEnvironment(
                "Environment variable names must be unique."
            )
        match entry.value:
            case StoredRuntimeEnvironmentValue(name=stored_name):
                if stored_name not in existing or stored_name in retained:
                    raise InvalidRuntimeEnvironment(
                        "A retained variable is missing or referenced more than once. "
                        "Reload the settings."
                    )
                retained.add(stored_name)
                desired[entry.name] = existing[stored_name]
            case ReplacementRuntimeEnvironmentValue(value=value):
                desired[entry.name] = value.get_secret_value()
            case _:
                assert_never(entry.value)
    validate_runtime_environment(desired)
    return desired


def parse_runtime_environment(plaintext: str) -> dict[str, str]:
    """Decode the encrypted body and fail closed on invalid persisted settings."""
    try:
        values = _values_adapter.validate_json(plaintext)
    except ValidationError:
        raise InvalidRuntimeEnvironment(
            "Stored Runtime environment is invalid."
        ) from None
    validate_runtime_environment(values)
    return values
