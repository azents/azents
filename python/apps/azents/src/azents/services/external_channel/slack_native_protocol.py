"""Bounded request-local Slack personal controls and signed private scope."""

import base64
import datetime
import hashlib
import hmac
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId

NativeAction = Literal[
    "azents_account_link_start",
    "azents_account_link_code_open",
    "azents_account_link_code",
    "azents_model_open",
    "azents_model_select",
    "azents_model_effort",
    "azents_model_execution",
    "azents_model_previous",
    "azents_model_next",
    "azents_model_apply",
    "azents_model_cancel",
]
NATIVE_ACTIONS = frozenset(get_args(NativeAction)) - {
    "azents_account_link_code",
    "azents_model_apply",
}


class SlackNativeScope(BaseModel):
    """Signed locator, never sufficient authority without the current actor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    connection_id: str = Field(min_length=1, max_length=32)
    principal_id: str = Field(min_length=1, max_length=32)
    channel_id: str = Field(min_length=1, max_length=255)
    thread_id: str | None = Field(max_length=255)
    expires_at: datetime.datetime
    origin_id: str | None = Field(max_length=32)
    draft_id: str | None = Field(max_length=32)
    selection_fingerprint: str | None = Field(min_length=16, max_length=16)
    offset: int = Field(ge=0)


def sign_native_scope(scope: SlackNativeScope, *, secret: str) -> str:
    """Sign bounded native scope without retaining proof or catalog contents."""
    encoded = base64.urlsafe_b64encode(scope.model_dump_json().encode()).rstrip(b"=")
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).hexdigest()
    return encoded.decode() + "." + signature


def parse_native_scope(
    metadata: str, *, secret: str, now: datetime.datetime
) -> SlackNativeScope:
    """Reject tampered, oversized, and expired private metadata."""
    if len(metadata) > 3000:
        raise ValueError("Slack private control is unavailable.")
    encoded, separator, signature = metadata.partition(".")
    expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if (
        not separator
        or not signature.isascii()
        or not hmac.compare_digest(signature, expected)
    ):
        raise ValueError("Slack private control is unavailable.")
    scope = SlackNativeScope.model_validate_json(
        base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    )
    if scope.expires_at.tzinfo is None or scope.expires_at <= now:
        raise ValueError("Slack private control expired. Reopen settings.")
    return scope


class SlackNativeControl(BaseModel):
    """Transient callback content excluded from durable interaction projections."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: NativeAction
    metadata: str = Field(min_length=1, max_length=3000, repr=False)
    code: str | None = Field(max_length=128, repr=False)
    option_id: str | None = Field(max_length=64)
    reasoning_effort: ModelReasoningEffort | None
    execution_options: list[ModelExecutionOptionId] | None
    view_id: str | None = Field(max_length=255)
    view_hash: str | None = Field(max_length=255)


class _Option(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str = Field(max_length=128)


class _Action(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action_id: str
    value: str | None = None
    selected_option: _Option | None = None
    selected_options: list[_Option] | None = Field(default=None, max_length=25)


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str | None = Field(default=None, max_length=128, repr=False)


class _State(BaseModel):
    model_config = ConfigDict(extra="ignore")
    values: dict[str, dict[str, _Input]]


class _View(BaseModel):
    model_config = ConfigDict(extra="ignore")
    private_metadata: str = Field(max_length=3000)
    id: str | None = None
    hash: str | None = None
    state: _State | None = None


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    view: _View | None = None
    actions: list[_Action] = Field(default_factory=list, max_length=1)


def decode_native_control(
    payload: dict[str, object], *, action: str
) -> SlackNativeControl:
    """Decode Slack's open provider schema into one closed operation payload."""
    parsed = _Payload.model_validate(payload)
    item = parsed.actions[0] if parsed.actions else None
    view = parsed.view
    metadata = (
        item.value
        if item is not None and item.value is not None
        else view.private_metadata
        if view is not None
        else None
    )
    code = None
    if action == "azents_account_link_code" and view is not None and view.state:
        code_input = view.state.values.get("azents_account_link_code", {}).get("value")
        code = code_input.value if code_input is not None else None
        if not code or not code.strip():
            raise ValueError("Enter the verification code from Azents.")
    selected = item.selected_option.value if item and item.selected_option else None
    if action in {"azents_model_select", "azents_model_effort"} and selected is None:
        raise ValueError("Slack model selection is missing.")
    return SlackNativeControl.model_validate(
        {
            "action": action,
            "metadata": metadata,
            "code": code,
            "option_id": selected if action == "azents_model_select" else None,
            "reasoning_effort": (
                selected
                if action == "azents_model_effort" and selected != "default"
                else None
            ),
            "execution_options": (
                [option.value for option in item.selected_options or []]
                if item is not None and action == "azents_model_execution"
                else None
            ),
            "view_id": view.id if view else None,
            "view_hash": view.hash if view else None,
        }
    )
