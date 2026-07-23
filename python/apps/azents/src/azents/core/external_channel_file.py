"""Provider-neutral External Channel file metadata and locator contracts."""

import copy
import enum
from dataclasses import dataclass
from urllib.parse import quote, unquote

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.enums import ExternalChannelProvider

MAX_EXTERNAL_CHANNEL_FILES = 20
MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH = 255
DEFAULT_EXTERNAL_CHANNEL_INBOUND_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_ACTION_BYTES = 100 * 1024 * 1024
MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES = 100 * 1024 * 1024
MAX_EXTERNAL_CHANNEL_CONFIGURED_ACTION_BYTES = (
    MAX_EXTERNAL_CHANNEL_FILES * MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES
)
EXTERNAL_CHANNEL_FILE_STREAM_CHUNK_BYTES = 1024 * 1024
EXTERNAL_CHANNEL_FILE_LOCATOR_PREFIX = "external-file:v1"


class ExternalChannelFileUnsupportedReason(enum.StrEnum):
    """Stable reason one observed provider file cannot be transferred."""

    MISSING_FILE_ID = "missing_file_id"
    INVALID_SIZE = "invalid_size"
    EXTERNAL_FILE = "external_file"
    SLACK_CONNECT_FILE = "slack_connect_file"
    SPARSE_FILE = "sparse_file"
    UNSUPPORTED_MODE = "unsupported_mode"


class ExternalChannelFileMetadata(BaseModel):
    """Bounded provider-neutral metadata persisted for one observed file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ExternalChannelProvider
    provider_file_id: str | None = Field(
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH,
    )
    name: str | None = Field(max_length=MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH)
    title: str | None = Field(max_length=MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH)
    media_type: str | None = Field(max_length=MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH)
    declared_size: int | None = Field(ge=0)
    mode: str | None = Field(max_length=MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH)
    external: bool
    file_access: str | None = Field(max_length=MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH)
    supported: bool
    unsupported_reason: ExternalChannelFileUnsupportedReason | None

    @model_validator(mode="after")
    def validate_supported_state(self) -> "ExternalChannelFileMetadata":
        """Keep supported state and rejection reason internally consistent."""
        if self.supported:
            if self.provider_file_id is None:
                raise ValueError("Supported External Channel file requires an ID.")
            if self.unsupported_reason is not None:
                raise ValueError(
                    "Supported External Channel file cannot have a reason."
                )
        elif self.unsupported_reason is None:
            raise ValueError("Unsupported External Channel file requires a reason.")
        return self


class ExternalChannelOutboundFileManifest(BaseModel):
    """Bounded Runtime source metadata persisted for one outbound file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=4_096)
    filename: str = Field(
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH,
    )
    media_type: str = Field(
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH,
    )
    expected_size: int = Field(gt=0)


@dataclass(frozen=True)
class ExternalChannelFileLocator:
    """Decoded provider-neutral address for one binding-scoped provider file."""

    provider: ExternalChannelProvider
    binding_id: str
    provider_file_id: str

    def __post_init__(self) -> None:
        if not self.binding_id.strip():
            raise ValueError("External Channel file locator binding ID is blank.")
        if not self.provider_file_id.strip():
            raise ValueError("External Channel file locator provider file ID is blank.")

    def encode(self) -> str:
        """Encode the locator as a versioned opaque Agent-visible value."""
        return ":".join(
            (
                EXTERNAL_CHANNEL_FILE_LOCATOR_PREFIX,
                self.provider.value,
                quote(self.binding_id, safe=""),
                quote(self.provider_file_id, safe=""),
            )
        )

    @classmethod
    def parse(cls, value: str) -> "ExternalChannelFileLocator":
        """Parse one versioned locator and reject unknown or malformed values."""
        parts = value.split(":", 4)
        valid_prefix = (
            len(parts) == 5
            and ":".join(parts[:2]) == EXTERNAL_CHANNEL_FILE_LOCATOR_PREFIX
        )
        if not valid_prefix:
            raise ValueError("External Channel file locator is malformed.")
        try:
            provider = ExternalChannelProvider(parts[2])
        except ValueError as error:
            raise ValueError(
                "External Channel file locator provider is unsupported."
            ) from error
        binding_id = unquote(parts[3])
        provider_file_id = unquote(parts[4])
        return cls(
            provider=provider,
            binding_id=binding_id,
            provider_file_id=provider_file_id,
        )


def external_channel_file_metadata_items(
    attachment_metadata: dict[str, object],
) -> tuple[dict[str, object], ...]:
    """Return only object-shaped file entries from bounded attachment metadata."""
    files = attachment_metadata.get("files")
    if not isinstance(files, list):
        return ()
    return tuple(item for item in files if isinstance(item, dict))


def add_external_channel_file_locators(
    attachment_metadata: dict[str, object],
    *,
    binding_id: str,
) -> dict[str, object]:
    """Return a detached metadata copy with binding-scoped Agent-visible locators."""
    enriched = copy.deepcopy(attachment_metadata)
    files = enriched.get("files")
    if not isinstance(files, list):
        return enriched
    for item in files:
        if not isinstance(item, dict):
            continue
        provider_value = item.get("provider")
        provider_file_id = item.get("provider_file_id")
        if not isinstance(provider_value, str) or not isinstance(provider_file_id, str):
            continue
        try:
            provider = ExternalChannelProvider(provider_value)
        except ValueError:
            continue
        item["file"] = ExternalChannelFileLocator(
            provider=provider,
            binding_id=binding_id,
            provider_file_id=provider_file_id,
        ).encode()
    return enriched
