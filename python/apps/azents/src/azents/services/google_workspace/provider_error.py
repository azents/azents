"""Bounded original provider diagnostics without SDK request dumps."""

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_MAXIMUM_TEXT = 4000


class _Reason(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    reason: str | None = None


class _ProviderError(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    message: str | None = None
    status: str | None = None
    errors: list[_Reason] = Field(default_factory=list)
    details: list[_Reason] = Field(default_factory=list)


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    error: _ProviderError


class GoogleProviderError(BaseModel):
    """Only response-owned fields, not SDK exception/request serialization."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str | None
    reasons: tuple[str, ...]
    message: str | None

    def describe(self, http_status: int | None) -> str:
        """Preserve useful provider wording, identifiers and console links."""
        fields = [f"HTTP {http_status}"] if http_status is not None else []
        if self.status:
            fields.append(self.status)
        fields.extend(self.reasons)
        label = "; ".join(fields)
        return (
            f"Google response ({label}): {self.message or 'No error message returned.'}"
        )


def decode_provider_error(content: bytes) -> GoogleProviderError | None:
    """Retain bounded original fields, including unknown provider reasons."""
    try:
        value = _Envelope.model_validate_json(content).error
    except ValidationError:
        return None

    reasons = tuple(
        dict.fromkeys(
            item.reason[:256] for item in (*value.errors, *value.details) if item.reason
        )
    )[:10]
    return GoogleProviderError(
        status=value.status[:256] if value.status is not None else None,
        reasons=reasons,
        message=value.message[:_MAXIMUM_TEXT] if value.message is not None else None,
    )
