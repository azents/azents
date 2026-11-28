"""Bounded, value-free Vault request contracts."""

import re
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from azents.core.enums import ExternalChannelProvider

type VaultRequestId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


def _validate_button_label(label: str) -> str:
    if (
        not label.strip()
        or not label.isprintable()
        or len(label.encode("utf-16-le")) > 150
    ):
        raise ValueError("Invalid Vault request button label.")
    return label


VaultRequestButtonLabel = Annotated[
    str, Field(min_length=1, max_length=75), AfterValidator(_validate_button_label)
]


class VaultRequestField(BaseModel):
    """One exact Vault entry name and the label shown to a submitter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(min_length=1, max_length=255)]
    label: Annotated[str, Field(min_length=1, max_length=120)]

    @field_validator("name", "label")
    @classmethod
    def validate_display_text(cls, value: str) -> str:
        """Reject blank or non-printable field identifiers."""
        if not value.strip() or not value.isprintable():
            raise ValueError("Invalid request field.")
        return value


class VaultChannelReference(BaseModel):
    """An explicit provider channel; never infer a target from the source Session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ExternalChannelProvider
    channel_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9]{1,32}$")]

    @model_validator(mode="after")
    def validate_channel_id(self) -> "VaultChannelReference":
        """Accept only a provider channel ID, not a URL or message reference."""
        if self.provider is ExternalChannelProvider.DISCORD:
            valid = re.fullmatch(r"[0-9]{1,20}", self.channel_id)
        else:
            valid = re.fullmatch(r"[CGD][A-Z0-9]{1,31}", self.channel_id)
        if valid is None:
            raise ValueError("Invalid provider channel.")
        return self


class VaultRequestSpec(BaseModel):
    """Tool input with no values, deadline override or submitter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: Annotated[str, Field(min_length=1, max_length=500)]
    fields: Annotated[tuple[VaultRequestField, ...], Field(min_length=1, max_length=16)]
    destination: VaultChannelReference | None = None
    button_label: VaultRequestButtonLabel | None = Field(
        default=None,
        description="Plain-text input button label for the specified channel.",
    )

    @model_validator(mode="after")
    def validate_spec(self) -> "VaultRequestSpec":
        """Keep metadata bounded and reject duplicate exact names."""
        if (
            not self.purpose.strip()
            or not self.purpose.isprintable()
            or len({field.name for field in self.fields}) != len(self.fields)
            or (self.button_label is not None and self.destination is None)
        ):
            raise ValueError("Invalid Vault request specification.")
        return self


class VaultRequestIdentityPayload(BaseModel):
    """Value-free identity for the history anchor and completion input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: VaultRequestId
    mailbox_item_id: str | None = Field(
        default=None,
        min_length=32,
        max_length=32,
        exclude_if=lambda value: value is None,
    )
    mailbox_item_key: str | None = Field(
        default=None, max_length=120, exclude_if=lambda value: value is None
    )

    def model_content(self) -> str:
        """Describe settlement without values or form metadata."""
        return f"Vault request {self.request_id} was submitted."


class VaultRequestValue(BaseModel):
    """A submit-only field whose value is never included in diagnostics."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    name: Annotated[str, Field(strict=True, min_length=1, max_length=255)]
    value: Annotated[SecretStr, Field(min_length=1, max_length=32768)]


class VaultRequestSubmission(BaseModel):
    """One value per requested exact name, with duplicates explicitly detectable."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    values: Annotated[tuple[VaultRequestValue, ...], Field(min_length=1, max_length=16)]
