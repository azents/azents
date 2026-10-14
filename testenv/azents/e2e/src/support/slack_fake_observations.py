"""Typed interpreted responses from the deterministic Slack fake.

The provider owns response extensions; native contract assertions may serialize
these observations back to wire for literal comparison. Decision fields remain
strict and are consumed directly.
"""

from pydantic import BaseModel, ConfigDict, Field


class SlackObservation(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow", hide_input_in_errors=True)


class BarrierObservation(SlackObservation):
    operation: str | None
    occurrence: int | None
    request_count: int
    reached: bool
    released: bool


class UploadTargetObservation(SlackObservation):
    ok: bool
    upload_url: str = Field(min_length=1)
    file_id: str = Field(min_length=1)


class OAuthTokenObservation(SlackObservation):
    ok: bool
    access_token: str = Field(min_length=1)
    token_type: str


class RequestObservation(SlackObservation):
    operation: str
    method: str


class OAuthRequestObservation(SlackObservation):
    operation: str
    outcome: str


class OAuthEvidenceObservation(SlackObservation):
    requests: list[OAuthRequestObservation]
    outstanding_code_count: int
    active_token_count: int


class SocketEvidenceObservation(SlackObservation):
    connections: int
    envelope_ids: list[str]
    acknowledgements: list[str]
    configured_sessions: int


class FakeEvidenceObservation(SlackObservation):
    """Declared decision fields; delivery/presence/view evidence is wire-only."""

    request_counts: dict[str, int]
    requests: list[RequestObservation]
    oauth: OAuthEvidenceObservation
    socket: SocketEvidenceObservation
    deliveries: list[dict[str, object]]
    presence: list[dict[str, object]]
    views: list[dict[str, object]]
