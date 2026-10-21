"""Canonical file arguments and internal bytes, never provider bearer locations."""

import dataclasses
import hashlib
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from azents.core.file_transfer import GENERAL_FILE_MAXIMUM_BYTES

MediaType = Annotated[
    str,
    StringConstraints(
        max_length=255, pattern=r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$"
    ),
]


def safe_file_name(value: str, *, fallback: str) -> str:
    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(
        character
        for character in name
        if ord(character) >= 32 and ord(character) != 127
    ).strip()
    return name[:255] if name and name not in {".", ".."} else fallback


class GoogleFileInput(BaseModel):
    """Resolve source through current file/Runner authority before opening bytes."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    source: str = Field(
        min_length=1,
        max_length=4096,
        pattern=r"^[^\r\n\x00]+$",
        description=(
            "Authorized Exchange/Artifact/current-run VFS URI or absolute "
            "Runner-authorized Runtime path. Not an HTTP URL or Worker-local path."
        ),
    )
    filename: str | None = Field(min_length=1, max_length=255)
    media_type: MediaType | None

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        if "://" in value and not value.startswith(
            ("exchange://", "artifact://", "azents://")
        ):
            raise ValueError(
                "Use canonical product file resources or authorized Runtime paths."
            )
        return value

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str | None) -> str | None:
        if value is not None and (
            safe_file_name(value, fallback="") != value or "/" in value or "\\" in value
        ):
            raise ValueError("File name must be a single safe nonempty name.")
        return value


@dataclasses.dataclass(frozen=True)
class GooglePreparedFile:
    """Verified input or bounded provider output awaiting canonical publication."""

    filename: str
    media_type: str
    content: bytes = dataclasses.field(repr=False)
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            safe_file_name(self.filename, fallback="") != self.filename
            or not self.filename
            or len(self.content) > GENERAL_FILE_MAXIMUM_BYTES
            or re.fullmatch(
                r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", self.media_type
            )
            is None
        ):
            raise ValueError("Invalid bounded Google file metadata or size.")

    @property
    def size(self) -> int:
        return len(self.content)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclasses.dataclass(frozen=True)
class GoogleWorkspaceOutput[T: BaseModel]:
    """Root publishes files after current authority revalidation, never raw bytes."""

    value: T
    files: tuple[GooglePreparedFile, ...]
