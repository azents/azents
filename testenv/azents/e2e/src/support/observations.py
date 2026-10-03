"""Runtime-validated projections for E2E observation boundaries.

Generated response models own represented public/admin HTTP contracts. The small
models below own only interpreted fixture/browser/event fields. Unknown extension
fields are retained or ignored rather than rejected; opaque event content remains
JSON and is decoded again only when a scenario actually interprets its shape.
"""

from __future__ import annotations

import datetime
from typing import Literal, Self

from azentsadminclient.models.runtime_provider_list_response import (
    RuntimeProviderListResponse,
)
from azentsadminclient.models.system_bootstrap_first_admin_response import (
    SystemBootstrapFirstAdminResponse,
)
from azentsadminclient.models.system_bootstrap_status_response import (
    SystemBootstrapStatusResponse,
)
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.applied_inference_profile import AppliedInferenceProfile
from azentspublicclient.models.chat_event_page_response import ChatEventPageResponse
from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.chat_write_response import ChatWriteResponse
from azentspublicclient.models.historical_memory_list_response import (
    HistoricalMemoryListResponse,
)
from azentspublicclient.models.historical_memory_response import (
    HistoricalMemoryResponse,
)
from azentspublicclient.models.subagent_tree_response import SubagentTreeResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)


class ExtensionObservation(BaseModel):
    """Interpret declared fields while preserving forward-compatible extensions."""

    model_config = ConfigDict(extra="allow", frozen=True)


class HistoryEventObservation(ChatEventResponse):
    """Generated event contract retaining forward-compatible wire extensions."""

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def retain_wire_extensions(self) -> Self:
        """Expose unknown envelope evidence through generated extension storage."""
        self.additional_properties.update(self.model_extra or {})
        return self


class HistoryPageObservation(ChatEventPageResponse):
    """Generated pagination defaults and event fields with retained extensions."""

    model_config = ConfigDict(extra="allow")
    items: list[HistoryEventObservation]


class RequestedProfileObservation(ExtensionObservation):
    """Prepared input settings, with explicit nullable reasoning effort."""

    model_target_label: StrictStr
    reasoning_effort: StrictStr | None
    enabled_execution_options: list[StrictStr]


class InputMessageObservation(ExtensionObservation):
    """Interpreted input/message fields; arbitrary content is an opaque relay."""

    content: JsonValue = None
    summary: StrictStr | None = None
    requested_inference_profile: RequestedProfileObservation | None = None


class ToolkitSourceObservation(ExtensionObservation):
    """Public immutable source identity retained by a selected tool."""

    toolkit_config_id: StrictStr
    toolkit_name: StrictStr
    toolkit_slug: StrictStr
    toolkit_namespace: StrictStr
    source_identity: dict[str, StrictStr]


class ToolCallObservation(ExtensionObservation):
    """Durable/live tool call identity and opaque provider arguments."""

    call_id: StrictStr
    name: StrictStr
    arguments: JsonValue = None
    toolkit_source: ToolkitSourceObservation | None = None


class ToolResultObservation(ExtensionObservation):
    """Durable result identity with uninterpreted output content."""

    call_id: StrictStr
    name: StrictStr | None = None
    status: StrictStr | None = None
    output: JsonValue = None


class UsageObservation(ExtensionObservation):
    """Token evidence interpreted by persistence assertions."""

    total_tokens: StrictInt | None = None
    prompt_tokens: StrictInt | None = None
    completion_tokens: StrictInt | None = None
    raw: dict[str, JsonValue] | None = None
    cost_usd: StrictFloat | StrictInt | None = None


class AppliedProfileObservation(AppliedInferenceProfile):
    """Generated profile fields projected through null-omitting Event transport.

    Event serialization may omit a null effort even though the direct generated
    profile response requires the nullable key. The default preserves this wire
    tolerance and fields_set distinguishes omission from explicit null.
    """

    reasoning_effort: StrictStr | None = None


class TurnMarkerObservation(ExtensionObservation):
    """Public turn provenance, with omitted/null optional evidence preserved."""

    run_id: StrictStr | None = None
    usage: UsageObservation | None = None
    applied_inference_profile: AppliedProfileObservation | None = None
    effective_context_window_tokens: StrictInt | None = None
    effective_auto_compaction_threshold_tokens: StrictInt | None = None


class RunMarkerObservation(ExtensionObservation):
    """The terminal status used to recognize a completed durable turn."""

    run_id: StrictStr | None = None
    status: StrictStr


class FailedAttemptObservation(ExtensionObservation):
    """Interpreted retry/terminal attempt evidence, not raw provider content."""

    attempt_number: StrictInt
    error_kind: StrictStr | None = None
    retryability: StrictStr | None = None
    failure_code: StrictStr | None = None
    user_message: StrictStr


class FailedRunObservation(ExtensionObservation):
    """Failed-run controls and terminal provenance consumed by polling."""

    kind: StrictStr
    attempts: list[FailedAttemptObservation] | None = None
    error_kind: StrictStr | None = None
    retryability: StrictStr | None = None
    failure_code: StrictStr | None = None
    failed_attempt_count: StrictInt | None = None
    max_retries: StrictInt | None = None


class SystemErrorObservation(ExtensionObservation):
    """A system error may omit failed-run controls for other error families."""

    failure: FailedRunObservation | None = None
    message: StrictStr | None = None


class MailboxPresentationObservation(ExtensionObservation):
    """Fields consumed by the native user-message mailbox journey."""

    type: StrictStr
    content: JsonValue = None


class MailboxItemObservation(ExtensionObservation):
    """Stable native item identity and presentation."""

    id: StrictStr
    item_key: StrictStr
    presentation: MailboxPresentationObservation


class MailboxObservation(ExtensionObservation):
    """Native mailbox envelope identity shared by REST and WebSocket."""

    mailbox_item_id: StrictStr
    session_id: StrictStr
    kind: StrictStr
    items: list[MailboxItemObservation]


class ChatActionObservation(ExtensionObservation):
    """Interpreted canonical Chat action envelope, retaining wire extensions."""

    type: Literal[
        "action_execution_removed",
        "action_execution_updated",
        "mailbox_item_removed",
        "mailbox_item_upserted",
        "history_event_appended",
        "input_actions_updated",
        "live_event_removed",
        "live_event_upserted",
        "live_projection_reset",
        "live_run_cleared",
        "live_run_updated",
        "subagent_tree_changed",
        "subscribed",
        "subscription_health_check_ack",
        "todo_state_changed",
    ]
    session_id: StrictStr | None = None
    mailbox_item_id: StrictStr | None = None
    request_id: StrictStr | None = None
    event: HistoryEventObservation | None = None
    mailbox_item: MailboxObservation | None = None

    @model_validator(mode="after")
    def validate_interpreted_variant(self) -> Self:
        """Require the decision fields belonging to each interpreted variant."""
        if self.type not in {"subagent_tree_changed", "todo_state_changed"}:
            if self.session_id is None:
                raise ValueError("Canonical action must include session_id")
        if self.type == "history_event_appended" and self.event is None:
            raise ValueError("History append action must include event")
        if self.type == "mailbox_item_upserted" and self.mailbox_item is None:
            raise ValueError("Mailbox upsert action must include mailbox_item")
        if self.type == "mailbox_item_removed" and self.mailbox_item_id is None:
            raise ValueError("Mailbox removal action must include mailbox_item_id")
        return self


class RuntimeHookObservation(ExtensionObservation):
    """Structured hook log evidence; unrelated log fields stay extensions."""

    runtime_hook_qa_lifecycle: StrictStr | None
    message: StrictStr | None = None
    tool_name: StrictStr | None = None
    toolkit_slug: StrictStr | None = None


def decode_runtime_hook(value: object) -> RuntimeHookObservation | None:
    """Select structured hook evidence; unrelated or incomplete logs cannot match."""
    if not isinstance(value, dict):
        return None
    if value.get("message") != "Runtime hook QA lifecycle event":
        return None
    if "runtime_hook_qa_lifecycle" not in value:
        return None
    return RuntimeHookObservation.model_validate(value)


class HistoricalSampleObservation(ExtensionObservation):
    """Testenv sampler evidence; it does not claim scheduler dispatch coverage."""

    now: datetime.datetime
    admitted: StrictInt
    due_agents: StrictInt
    attempted: StrictInt
    prepared: StrictInt
    empty: StrictInt
    failed: StrictInt
    quota_advanced: StrictInt


class ProxyToolObservation(ExtensionObservation):
    """Only a named tool declaration is interpreted from a provider journal."""

    name: StrictStr | None = None
    type: StrictStr | None = None


class ProxyRequestObservation(ExtensionObservation):
    """Fixture request fields used for selection; provider body stays opaque."""

    model: StrictStr | None = None
    input: JsonValue = None
    messages: JsonValue = None
    tools: list[ProxyToolObservation] | None = None


class ProxyJournalObservation(BaseModel):
    """An operation-specific provider request list, not a dictionary adapter."""

    requests: list[ProxyRequestObservation]


class InfrastructureProfileObservation(ExtensionObservation):
    """Compatibility evidence returned by infrastructure Profile creation."""

    compatible: StrictBool
    compatibility_reason_code: StrictStr | None = None


class SeleniumStatusValueObservation(ExtensionObservation):
    """The ready flag is the only Selenium status decision field."""

    ready: StrictBool


class SeleniumStatusObservation(ExtensionObservation):
    """Selenium's status envelope has an explicit ready-value projection."""

    value: SeleniumStatusValueObservation


class DockerNetworkObservation(ExtensionObservation):
    """Docker network fields consumed by browser endpoint discovery."""

    gateway: StrictStr = Field(alias="Gateway")


class BrowserEchoObservation(ExtensionObservation):
    """Echo endpoint evidence produced by the real browser transport journey."""

    body: StrictStr
    method: StrictStr


class BrowserUploadObservation(ExtensionObservation):
    """Upload framing and checksum observations; null framing is meaningful."""

    bytes: StrictInt
    sha256: StrictStr
    content_length: StrictInt
    transfer_encoding: StrictStr | None


class BrowserWebSocketObservation(ExtensionObservation):
    """Opaque text plus exact binary octets observed by the browser."""

    text: StrictStr
    binary: list[StrictInt]


class BrowserTransportObservation(ExtensionObservation):
    """Successful browser HTTP/fan-out/SSE/WebSocket evidence."""

    echo: BrowserEchoObservation = Field(alias="echoBody")
    expected_upload_digest: StrictStr = Field(alias="expectedUploadDigest")
    upload: BrowserUploadObservation = Field(alias="uploadEvidence")
    events_body: StrictStr = Field(alias="eventsBody")
    redirect_status: StrictInt = Field(alias="redirectStatus")
    redirected_body: StrictStr = Field(alias="redirectedBody")
    redirected_url: StrictStr = Field(alias="redirectedUrl")
    bytes: StrictInt
    asset_count: StrictInt = Field(alias="assetCount")
    assets_valid: StrictBool = Field(alias="assetsValid")
    websocket: BrowserWebSocketObservation


class BrowserTransportFailure(ExtensionObservation):
    """The browser reports errors separately from successful evidence."""

    error: StrictStr


def decode_history_page(value: object) -> ChatEventPageResponse:
    """Decode the generated durable history/pagination contract at ingress."""
    return HistoryPageObservation.model_validate(value)


def decode_session(value: object) -> AgentSessionResponse:
    """Decode the generated Session identity/readiness/profile contract."""
    return AgentSessionResponse.model_validate(value)


def decode_chat_write(value: object) -> ChatWriteResponse:
    """Decode an accepted write identity without dropping snapshot evidence."""
    return ChatWriteResponse.model_validate(value)


def decode_historical_memories(value: object) -> HistoricalMemoryListResponse:
    """Decode current historical settings rows using the generated API model."""
    return HistoricalMemoryListResponse.model_validate(value)


def decode_historical_memory(value: object) -> HistoricalMemoryResponse:
    """Decode one current historical settings/detail observation."""
    return HistoricalMemoryResponse.model_validate(value)


def decode_subagent_tree(value: object) -> SubagentTreeResponse:
    """Decode the recursive generated public Subagent Tree contract."""
    return SubagentTreeResponse.model_validate(value)


def decode_runtime_providers(value: object) -> RuntimeProviderListResponse:
    """Decode durable provider inventory and capability-revision readiness."""
    return RuntimeProviderListResponse.model_validate(value)


def decode_bootstrap_status(value: object) -> SystemBootstrapStatusResponse:
    """Decode initial/post-bootstrap availability as an actual boolean."""
    return SystemBootstrapStatusResponse.model_validate(value)


def decode_bootstrap_session(value: object) -> SystemBootstrapFirstAdminResponse:
    """Decode the complete authenticated bootstrap session contract."""
    return SystemBootstrapFirstAdminResponse.model_validate(value)


def decode_proxy_journal(value: object) -> list[ProxyRequestObservation]:
    """Validate request-list structure once; retain each request's extensions."""
    return ProxyJournalObservation.model_validate({"requests": value}).requests


def decode_browser_transport(value: object) -> BrowserTransportObservation:
    """Reject reported browser failures before interpreting successful evidence."""
    try:
        if isinstance(value, dict) and "error" in value:
            failure = BrowserTransportFailure.model_validate(value)
            raise AssertionError(f"Browser transport failed: {failure.error}")
        return BrowserTransportObservation.model_validate(value)
    except ValidationError as error:
        raise AssertionError("Browser transport evidence is malformed") from error
