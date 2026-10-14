"""Typed interpreted operation responses from the Discord provider fixture."""

from pydantic import BaseModel, ConfigDict, Field


class DiscordCommandIdentity(BaseModel):
    """Provider command identity used in later update/delete requests.

    Discord owns command extensions; this projection neither inspects nor
    mutates them. Snowflake identities remain opaque strings.
    """

    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)

    id: str = Field(min_length=1)


class DiscordOAuthToken(BaseModel):
    """OAuth token used only for the subsequent authorized user-info operation.

    Provider-owned token response extensions remain outside the interpreted
    projection. Error displays and model representations exclude credentials.
    """

    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)

    access_token: str = Field(min_length=1, repr=False)


class DiscordDeliveryBarrier(BaseModel):
    """Complete private fixture control response, with explicit unset operation.

    This five-field protocol is owned by delivery_barrier_evidence rather than
    Discord; unknown fields and coercions are errors. Omitted and null operation
    remain distinct: the producer always emits the nullable key.
    """

    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    operation: str | None
    occurrence: int
    request_count: int
    reached: bool
    released: bool
