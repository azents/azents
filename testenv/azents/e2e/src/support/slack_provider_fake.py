"""Deterministic Slack HTTP and Socket Mode boundary for E2E tests."""

import base64
import hashlib
import json
import os
import re
import socket
import socketserver
import struct
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import ClassVar, NamedTuple
from urllib.parse import parse_qs, urlencode, urlparse

_HTTP_PORT = 8083
_WEBSOCKET_PORT = 8084
_MAX_CONFIGURED_FILE_BYTES = 8 * 1024 * 1024
_MAX_SCENARIO_SEQUENCE_LENGTH = 10
_MAX_RETRY_AFTER_SECONDS = 300
_APPROVAL_PATH = re.compile(r"/external-channel/access/([^/?\s]+)")
_BARRIER_OPERATIONS = frozenset(
    {
        "chat.update",
        "conversations.history",
        "conversations.replies",
    }
)


def _control(value: object, allowed: set[str]) -> dict[str, object]:
    """Decode a closed private control without echoing input or credentials."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected a private control object.")
    if set(value) - allowed:
        raise ValueError("Unsupported private control field.")
    return value


def _nullable_string(value: object, *, nonempty: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or (nonempty and not value):
        raise ValueError("Expected a configured string.")
    return value


def _configured_int(value: object, *, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError("Configured integer is outside its supported bounds.")
    return value


def _string_list(
    value: object, *, maximum: int | None = None, nonempty: bool = False
) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Expected configured string list.")
    if (nonempty and not value) or (maximum is not None and len(value) > maximum):
        raise ValueError("Configured sequence is outside its supported bounds.")
    return [item for item in value if isinstance(item, str)]


def _optional_string(value: object) -> str | None:
    """Validate one nonempty optional request string at ingress."""
    return value if isinstance(value, str) and value else None


def _objects(value: object) -> list[dict[str, object]]:
    """Malformed optional object lists project to empty, including mixed lists."""
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return []
    return [item for item in value if isinstance(item, dict)]


def _scenario_map(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Expected configured scenario map.")
    # The existing private control explicitly stringifies map keys and values.
    return {str(key): str(item) for key, item in value.items()}


@dataclass(frozen=True)
class OAuthConfiguration:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    user_id: str | None
    user_label: str | None
    team_id: str | None
    team_label: str | None
    authorize_scenario: str | None
    token_scenario: str | None
    userinfo_scenario: str | None
    delay_seconds: int | None


def decode_oauth_configuration(value: object) -> OAuthConfiguration:
    if isinstance(value, OAuthConfiguration):
        return value
    raw = _control(
        value,
        {
            "client_id",
            "client_secret",
            "redirect_uri",
            "user_id",
            "user_label",
            "team_id",
            "team_label",
            "authorize_scenario",
            "token_scenario",
            "userinfo_scenario",
            "delay_seconds",
        },
    )
    authorize = _nullable_string(raw.get("authorize_scenario"))
    token = _nullable_string(raw.get("token_scenario"))
    userinfo = _nullable_string(raw.get("userinfo_scenario"))
    if authorize is not None and authorize not in {
        "success",
        "cancel",
        "provider_error",
        "delay",
        "malformed",
    }:
        raise ValueError("Unsupported OAuth authorize scenario.")
    if any(
        item is not None and item not in {"success", "rejected", "malformed"}
        for item in (token, userinfo)
    ):
        raise ValueError("Unsupported OAuth response scenario.")
    delay = raw.get("delay_seconds")
    return OAuthConfiguration(
        client_id=_nullable_string(raw.get("client_id"), nonempty=True),
        client_secret=_nullable_string(raw.get("client_secret"), nonempty=True),
        redirect_uri=_nullable_string(raw.get("redirect_uri"), nonempty=True),
        user_id=_nullable_string(raw.get("user_id"), nonempty=True),
        user_label=_nullable_string(raw.get("user_label"), nonempty=True),
        team_id=_nullable_string(raw.get("team_id"), nonempty=True),
        team_label=_nullable_string(raw.get("team_label"), nonempty=True),
        authorize_scenario=authorize,
        token_scenario=token,
        userinfo_scenario=userinfo,
        delay_seconds=None
        if delay is None
        else _configured_int(delay, minimum=0, maximum=5),
    )


@dataclass(frozen=True)
class ConfiguredFile:
    """Validated file identity/content alongside opaque provider metadata."""

    id: str
    content: bytes
    metadata: dict[str, object]


def _configured_file(value: object) -> ConfiguredFile:
    raw = _control(
        value,
        {
            "id",
            "name",
            "title",
            "mimetype",
            "size",
            "mode",
            "external_type",
            "file_access",
            "is_external",
            "deleted",
            "content_base64",
        },
    )
    file_id = _nullable_string(raw.get("id"), nonempty=True)
    encoded = raw.get("content_base64")
    if file_id is None or not isinstance(encoded, str):
        raise ValueError("Configured Slack files require identity and content.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("Configured Slack file content is invalid.") from exc
    if len(content) > 8 * 1024 * 1024:
        raise ValueError("Configured Slack file content is too large.")
    metadata = {key: item for key, item in raw.items() if key != "content_base64"}
    metadata.setdefault("size", len(content))
    return ConfiguredFile(id=file_id, content=content, metadata=metadata)


@dataclass(frozen=True)
class SocketEnvelope:
    """Interpreted identity with an opaque provider envelope for egress."""

    envelope_id: str | None
    wire: dict[str, object]


@dataclass(frozen=True)
class SocketSession:
    envelopes: list[SocketEnvelope]
    disconnect_reason: str | None


def _configured_socket_session(value: object) -> SocketSession:
    raw = _control(value, {"envelopes", "disconnect_reason"})
    envelopes = raw.get("envelopes")
    if not isinstance(envelopes, list) or not all(
        isinstance(item, dict) for item in envelopes
    ):
        raise ValueError("Socket envelopes must be an object list.")
    projected: list[SocketEnvelope] = []
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            raise ValueError("Socket envelope must be an object.")
        envelope_id = envelope.get("envelope_id")
        projected.append(
            SocketEnvelope(
                envelope_id=envelope_id if isinstance(envelope_id, str) else None,
                wire=envelope,
            )
        )
    return SocketSession(
        envelopes=projected,
        disconnect_reason=_nullable_string(raw.get("disconnect_reason")),
    )


@dataclass(frozen=True)
class FakeConfiguration:
    oauth: OAuthConfiguration | None
    auth_scenario: str | None
    membership_scenario: str | None
    history_scenario: str | None
    permalink_scenario: str | None
    provider_app_id: str | None
    provider_team_id: str | None
    provider_bot_user_id: str | None
    granted_scopes: list[str] | None
    delivery_scenarios: dict[str, str] | None
    delivery_scenario_sequences: dict[str, list[str]] | None
    presence_scenarios: dict[str, str] | None
    file_scenarios: dict[str, str] | None
    view_scenarios: dict[str, str] | None
    files: list[ConfiguredFile] | None
    history_pages: list[list[dict[str, object]]] | None
    history_scenario_sequence: list[str] | None
    history_retry_after_seconds: list[int] | None
    socket_sessions: list[SocketSession] | None


def decode_fake_configuration(value: object) -> FakeConfiguration:
    raw = _control(
        value,
        {
            "oauth",
            "auth_scenario",
            "membership_scenario",
            "history_scenario",
            "permalink_scenario",
            "provider_app_id",
            "provider_team_id",
            "provider_bot_user_id",
            "granted_scopes",
            "delivery_scenarios",
            "delivery_scenario_sequences",
            "presence_scenarios",
            "file_scenarios",
            "view_scenarios",
            "files",
            "history_pages",
            "history_scenario_sequence",
            "history_retry_after_seconds",
            "socket_sessions",
        },
    )
    oauth = raw.get("oauth")
    scopes = raw.get("granted_scopes")
    sequences = raw.get("delivery_scenario_sequences")
    sequence_map: dict[str, list[str]] | None = None
    if sequences is not None:
        if not isinstance(sequences, dict) or not all(
            isinstance(key, str) for key in sequences
        ):
            raise ValueError("Delivery sequences must be a string-keyed object.")
        sequence_map = {
            key: _string_list(item, nonempty=True) for key, item in sequences.items()
        }
    files = raw.get("files")
    configured_files: list[ConfiguredFile] | None = None
    if files is not None:
        if not isinstance(files, list):
            raise ValueError("Configured files must be a list.")
        configured_files = [_configured_file(item) for item in files]
    pages = raw.get("history_pages")
    history_pages: list[list[dict[str, object]]] | None = None
    if pages is not None:
        if not isinstance(pages, list):
            raise ValueError("History pages must be a list.")
        history_pages = []
        for page in pages:
            if not isinstance(page, list) or not all(
                isinstance(item, dict) for item in page
            ):
                raise ValueError("History page must be an object list.")
            history_pages.append([item for item in page if isinstance(item, dict)])
    history_sequence = raw.get("history_scenario_sequence")
    retry = raw.get("history_retry_after_seconds")
    retry_sequence: list[int] | None = None
    if retry is not None:
        if not isinstance(retry, list) or not retry or len(retry) > 10:
            raise ValueError("Retry sequence must have 1-10 integers.")
        retry_sequence = [
            _configured_int(item, minimum=1, maximum=300) for item in retry
        ]
    sockets = raw.get("socket_sessions")
    socket_sessions: list[SocketSession] | None = None
    if sockets is not None:
        if not isinstance(sockets, list) or not sockets:
            raise ValueError("Socket sessions must be a nonempty list.")
        socket_sessions = [_configured_socket_session(item) for item in sockets]
    return FakeConfiguration(
        oauth=None if oauth is None else decode_oauth_configuration(oauth),
        auth_scenario=_nullable_string(raw.get("auth_scenario")),
        membership_scenario=_nullable_string(raw.get("membership_scenario")),
        history_scenario=_nullable_string(raw.get("history_scenario")),
        permalink_scenario=_nullable_string(raw.get("permalink_scenario")),
        provider_app_id=_nullable_string(raw.get("provider_app_id")),
        provider_team_id=_nullable_string(raw.get("provider_team_id")),
        provider_bot_user_id=_nullable_string(raw.get("provider_bot_user_id")),
        granted_scopes=None if scopes is None else _string_list(scopes),
        delivery_scenarios=_scenario_map(raw.get("delivery_scenarios")),
        delivery_scenario_sequences=sequence_map,
        presence_scenarios=_scenario_map(raw.get("presence_scenarios")),
        file_scenarios=_scenario_map(raw.get("file_scenarios")),
        view_scenarios=_scenario_map(raw.get("view_scenarios")),
        files=configured_files,
        history_pages=history_pages,
        history_scenario_sequence=None
        if history_sequence is None
        else _string_list(history_sequence, maximum=10, nonempty=True),
        history_retry_after_seconds=retry_sequence,
        socket_sessions=socket_sessions,
    )


@dataclass(frozen=True)
class OperationBarrier:
    operation: str
    occurrence: int


def decode_operation_barrier(value: object) -> OperationBarrier:
    # Barrier controls historically allow ignored extensions.
    if not isinstance(value, dict):
        raise ValueError("Expected a barrier control object.")
    operation = value.get("operation")
    if not isinstance(operation, str):
        raise ValueError("Expected a Slack operation.")
    if operation not in {
        "chat.update",
        "conversations.history",
        "conversations.replies",
    }:
        raise ValueError("Unsupported Slack barrier operation.")
    occurrence = value.get("occurrence")
    if (
        isinstance(occurrence, bool)
        or not isinstance(occurrence, int)
        or occurrence < 1
    ):
        raise ValueError("Barrier occurrence must be positive.")
    return OperationBarrier(operation=operation, occurrence=occurrence)


@dataclass
class UploadState:
    expected_length: int
    received_length: int | None
    uploaded: bool
    content_sha256: str | None


@dataclass(frozen=True)
class TextObservation:
    text: str | None


@dataclass(frozen=True)
class OptionObservation:
    value: str | None
    text: TextObservation | None


@dataclass(frozen=True)
class ElementObservation:
    type: str | None
    action_id: str | None
    url: str | None
    value: str | None
    options: list[OptionObservation]
    initial_option: OptionObservation | None


@dataclass(frozen=True)
class BlockObservation:
    type: str | None
    block_id: str | None
    text: TextObservation | None
    element: ElementObservation | None
    accessory: ElementObservation | None
    elements: list[ElementObservation]


@dataclass(frozen=True)
class ViewObservation:
    callback_id: str | None
    private_metadata: str | None
    has_submit: bool
    blocks: list[BlockObservation]


def _text(value: object) -> TextObservation | None:
    if not isinstance(value, dict):
        return None
    # Empty text is a valid rendered string, even though it cannot classify presence.
    text = value.get("text")
    return TextObservation(text=text if isinstance(text, str) else None)


def _option(value: object) -> OptionObservation | None:
    if not isinstance(value, dict):
        return None
    return OptionObservation(
        value=_optional_string(value.get("value")), text=_text(value.get("text"))
    )


def _element(value: object) -> ElementObservation | None:
    if not isinstance(value, dict):
        return None
    return ElementObservation(
        type=_optional_string(value.get("type")),
        action_id=_optional_string(value.get("action_id")),
        url=_optional_string(value.get("url")),
        value=_optional_string(value.get("value")),
        options=[
            option
            for item in _objects(value.get("options"))
            if (option := _option(item)) is not None
        ],
        initial_option=_option(value.get("initial_option")),
    )


def _blocks(value: object) -> list[BlockObservation]:
    return [
        BlockObservation(
            type=_optional_string(block.get("type")),
            block_id=_optional_string(block.get("block_id")),
            text=_text(block.get("text")),
            element=_element(block.get("element")),
            accessory=_element(block.get("accessory")),
            elements=[
                element
                for item in _objects(block.get("elements"))
                if (element := _element(item)) is not None
            ],
        )
        for block in _objects(value)
    ]


@dataclass(frozen=True)
class RequestMetadata:
    channel: str | None
    channel_id: str | None
    thread_ts: str | None
    ts: str | None
    length: int | None
    file_count: int | None

    def evidence(self) -> dict[str, object]:
        """Serialize only declared privacy-safe request fields."""
        return {
            key: value
            for key, value in {
                "channel": self.channel,
                "channel_id": self.channel_id,
                "thread_ts": self.thread_ts,
                "ts": self.ts,
                "length": self.length,
                "file_count": self.file_count,
            }.items()
            if value is not None
        }


def decode_metadata(raw: dict[str, object]) -> RequestMetadata:
    """Keep empty strings in metadata, unlike the optional control projections."""

    def string(name: str) -> str | None:
        value = raw.get(name)
        return value if isinstance(value, str) else None

    length = raw.get("length")
    files = raw.get("files")
    return RequestMetadata(
        channel=string("channel"),
        channel_id=string("channel_id"),
        thread_ts=string("thread_ts"),
        ts=string("ts"),
        length=length
        if isinstance(length, int) and not isinstance(length, bool)
        else None,
        file_count=len(files) if isinstance(files, list) else None,
    )


@dataclass(frozen=True)
class MessageRequest:
    channel: str | None
    thread_ts: str | None
    ts: str | None
    text: str | None
    blocks: list[BlockObservation]
    has_plan: bool
    blocks_wire: list[object] | None


def decode_message(raw: dict[str, object]) -> MessageRequest:
    blocks = raw.get("blocks")
    return MessageRequest(
        channel=_optional_string(raw.get("channel")),
        thread_ts=_optional_string(raw.get("thread_ts")),
        ts=_optional_string(raw.get("ts")),
        text=_optional_string(raw.get("text")),
        blocks=_blocks(blocks),
        has_plan=isinstance(blocks, list)
        and any(
            isinstance(block, dict) and block.get("type") == "plan" for block in blocks
        ),
        blocks_wire=blocks if isinstance(blocks, list) else None,
    )


@dataclass(frozen=True)
class PresenceRequest:
    channel_id: str | None
    thread_ts: str | None
    status: str | None
    initiator_user_id: str | None


def decode_presence(raw: dict[str, object]) -> PresenceRequest:
    return PresenceRequest(
        channel_id=_optional_string(raw.get("channel_id")),
        thread_ts=_optional_string(raw.get("thread_ts")),
        status=_optional_string(raw.get("status")),
        initiator_user_id=_optional_string(raw.get("initiator_user_id")),
    )


@dataclass(frozen=True)
class ViewRequest:
    view_id: str | None
    view: ViewObservation


def decode_view(raw: dict[str, object]) -> ViewRequest:
    value = raw.get("view")
    view = value if isinstance(value, dict) else {}
    return ViewRequest(
        view_id=_optional_string(raw.get("view_id")),
        view=ViewObservation(
            callback_id=_optional_string(view.get("callback_id")),
            private_metadata=_optional_string(view.get("private_metadata")),
            has_submit=isinstance(view.get("submit"), dict),
            blocks=_blocks(view.get("blocks")),
        ),
    )


@dataclass(frozen=True)
class UploadAllocationRequest:
    length: int | None


def decode_upload_allocation(raw: dict[str, object]) -> UploadAllocationRequest:
    length = raw.get("length")
    return UploadAllocationRequest(
        length=length
        if isinstance(length, int) and not isinstance(length, bool) and length > 0
        else None
    )


@dataclass(frozen=True)
class UploadCompletionRequest:
    file_ids: list[str | None]
    channel_id: str | None
    thread_ts: str | None
    has_initial_comment: bool


def decode_upload_completion(raw: dict[str, object]) -> UploadCompletionRequest:
    return UploadCompletionRequest(
        file_ids=[
            _optional_string(item.get("id")) for item in _objects(raw.get("files"))
        ],
        channel_id=_optional_string(raw.get("channel_id")),
        thread_ts=_optional_string(raw.get("thread_ts")),
        has_initial_comment=_optional_string(raw.get("initial_comment")) is not None,
    )


@dataclass(frozen=True)
class OAuthExchangeRequest:
    code: str | None
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    pkce_present: bool


@dataclass(frozen=True)
class OAuthAuthorizeRequest:
    """Validated single-valued SDK authorization query fields."""

    client_id: str | None
    redirect_uri: str | None
    state: str | None
    scope: str | None
    response_type: str | None
    pkce_present: bool


def decode_oauth_authorize(query: dict[str, list[str]]) -> OAuthAuthorizeRequest:
    """Project duplicate or absent query fields as invalid optional values."""
    return OAuthAuthorizeRequest(
        client_id=_query_one(query, "client_id"),
        redirect_uri=_query_one(query, "redirect_uri"),
        state=_query_one(query, "state"),
        scope=_query_one(query, "scope"),
        response_type=_query_one(query, "response_type"),
        pkce_present=_query_one(query, "code_challenge") is not None,
    )


def decode_oauth_exchange(raw: dict[str, object]) -> OAuthExchangeRequest:
    """Preserve empty credential strings so Basic fallback follows the SDK contract."""

    def string(name: str) -> str | None:
        value = raw.get(name)
        return value if isinstance(value, str) else None

    return OAuthExchangeRequest(
        code=string("code"),
        client_id=string("client_id"),
        client_secret=string("client_secret"),
        redirect_uri=string("redirect_uri"),
        pkce_present=raw.get("code_verifier") is not None,
    )


@dataclass(frozen=True)
class ControlHandoff:
    """Declared private controls; field names track supplied egress keys."""

    action_ids: list[str]
    input_action_ids: list[str]
    block_ids: list[str]
    option_values: dict[str, list[str]]
    option_labels: dict[str, dict[str, str]]
    action_values: dict[str, str]
    link_paths: list[str]
    supplied_fields: frozenset[str]

    def wire(self) -> dict[str, object]:
        """Serialize private handoff only at the transient control egress."""
        return {
            key: value
            for key, value in {
                "action_ids": self.action_ids,
                "input_action_ids": self.input_action_ids,
                "block_ids": self.block_ids,
                "option_values": self.option_values,
                "option_labels": self.option_labels,
                "action_values": self.action_values,
                "link_paths": self.link_paths,
            }.items()
            if key in self.supplied_fields
        }


def decode_control_handoff(value: object) -> ControlHandoff:
    if isinstance(value, ControlHandoff):
        return value
    raw = _control(
        value,
        {
            "action_ids",
            "input_action_ids",
            "block_ids",
            "option_values",
            "option_labels",
            "action_values",
            "link_paths",
        },
    )

    def strings(name: str) -> list[str]:
        return _string_list(raw.get(name, []))

    def string_map(value: object) -> dict[str, str]:
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in value.items()
        ):
            raise ValueError("Expected a private string map.")
        return {
            key: item
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str)
        }

    options = raw.get("option_values", {})
    if not isinstance(options, dict) or not all(
        isinstance(key, str) for key in options
    ):
        raise ValueError("Expected a private option map.")
    labels = raw.get("option_labels", {})
    if not isinstance(labels, dict) or not all(isinstance(key, str) for key in labels):
        raise ValueError("Expected a private label map.")
    return ControlHandoff(
        action_ids=strings("action_ids"),
        input_action_ids=strings("input_action_ids"),
        block_ids=strings("block_ids"),
        option_values={key: _string_list(item) for key, item in options.items()},
        option_labels={key: string_map(item) for key, item in labels.items()},
        action_values=string_map(raw.get("action_values", {})),
        link_paths=strings("link_paths"),
        supplied_fields=frozenset(raw),
    )


@dataclass(frozen=True)
class ActionHandoff:
    action_id: str
    block_id: str | None
    value: str | None

    def wire(self) -> dict[str, object]:
        """Serialize transient action identities without visible message content."""
        return {
            key: value
            for key, value in {
                "action_id": self.action_id,
                "block_id": self.block_id,
                "value": self.value,
            }.items()
            if value is not None
        }


def decode_acknowledgement(raw: object) -> str | None:
    """Validate the interpreted ACK identity; unrelated frames remain ignored."""
    if not isinstance(raw, dict):
        return None
    value = raw.get("envelope_id")
    return value if isinstance(value, str) else None


class _UploadAllocation(NamedTuple):
    """Allocated fake upload identity and path."""

    file_id: str
    upload_path: str


class _RecordedView(NamedTuple):
    """Recorded provider view identity and hash."""

    view_id: str
    view_hash: str


class _CompletedUploads(NamedTuple):
    """Upload completion status and aggregate received bytes."""

    completed: bool
    total_bytes: int


class _SelectorControlEvidence(NamedTuple):
    """Selector action IDs and its opaque admission identity."""

    action_ids: list[str]
    selector_admission_id: str | None


class _OAuthResponse(NamedTuple):
    """One fake OAuth HTTP response."""

    status: int
    payload: dict[str, object] | None
    redirect: str | None


class SlackOAuthState:
    """Deterministic Slack OpenID flow with redacted durable evidence."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.reset()

    def reset(self) -> None:
        """Reset OAuth configuration, one-time credentials, and evidence."""
        with self.lock:
            self.client_id = "slack-oauth-client"
            self.client_secret = "slack-oauth-secret"
            self.redirect_uri = (
                "https://azents.example/oauth/external-account/slack/callback"
            )
            self.authorize_scenario = "success"
            self.token_scenario = "success"
            self.userinfo_scenario = "success"
            self.delay_seconds = 0
            self.user_id = "U-OAUTH-E2E"
            self.user_label = "Slack OAuth User"
            self.team_id = "T-OAUTH-E2E"
            self.team_label = "Slack OAuth Team"
            self.requests: list[dict[str, object]] = []
            self._codes: dict[str, str] = {}
            self._tokens: set[str] = set()
            self._handoff: dict[str, object] | None = None
            self._sequence = 0

    def configure(self, payload: object) -> None:
        """Apply one bounded test-only OAuth configuration."""
        config = decode_oauth_configuration(payload)
        with self.lock:
            if config.client_id is not None:
                self.client_id = config.client_id
            if config.client_secret is not None:
                self.client_secret = config.client_secret
            if config.redirect_uri is not None:
                self.redirect_uri = config.redirect_uri
            if config.user_id is not None:
                self.user_id = config.user_id
            if config.user_label is not None:
                self.user_label = config.user_label
            if config.team_id is not None:
                self.team_id = config.team_id
            if config.team_label is not None:
                self.team_label = config.team_label
            if config.authorize_scenario is not None:
                self.authorize_scenario = config.authorize_scenario
            if config.token_scenario is not None:
                self.token_scenario = config.token_scenario
            if config.userinfo_scenario is not None:
                self.userinfo_scenario = config.userinfo_scenario
            if config.delay_seconds is not None:
                self.delay_seconds = config.delay_seconds
            self.requests = []
            self._codes = {}
            self._tokens = set()
            self._handoff = None
            self._sequence = 0

    def authorize(self, query: OAuthAuthorizeRequest) -> _OAuthResponse:
        """Validate fixed Slack OpenID input and issue one callback."""
        client_id = query.client_id
        redirect_uri = query.redirect_uri
        state = query.state
        client_valid = client_id == self.client_id
        redirect_valid = redirect_uri == self.redirect_uri
        scope_valid = query.scope == "openid profile"
        valid = (
            client_valid
            and redirect_valid
            and scope_valid
            and query.response_type == "code"
            and state is not None
            and bool(state)
        )
        if not valid:
            self._record(
                "authorize",
                "rejected",
                client_valid=client_valid,
                redirect_valid=redirect_valid,
                scope_valid=scope_valid,
                state_present=bool(state),
                pkce_present=query.pkce_present,
            )
            return _OAuthResponse(400, {"error": "invalid_request"}, None)
        scenario = self.authorize_scenario
        delay_seconds = self.delay_seconds
        if scenario == "delay":
            time.sleep(delay_seconds)
            scenario = "success"
        assert redirect_uri is not None
        assert state is not None
        if scenario == "cancel":
            callback = _callback_url(
                redirect_uri,
                {"error": "access_denied", "state": state},
            )
            outcome = "cancelled"
        elif scenario == "provider_error":
            callback = _callback_url(
                redirect_uri,
                {"error": "server_error", "state": state},
            )
            outcome = "provider_error"
        elif scenario == "malformed":
            callback = _callback_url(
                redirect_uri,
                {"code": "malformed-without-state"},
            )
            outcome = "malformed"
        else:
            with self.lock:
                self._sequence += 1
                code = f"slack-oauth-code-{self._sequence}"
                self._codes[code] = redirect_uri
            callback = _callback_url(redirect_uri, {"code": code, "state": state})
            outcome = "authorized"
        with self.lock:
            self._handoff = {"redirect_url": callback}
        self._record(
            "authorize",
            outcome,
            client_valid=True,
            redirect_valid=True,
            scope_valid=True,
            state_present=True,
            pkce_present=False,
        )
        return _OAuthResponse(302, None, callback)

    def exchange(
        self,
        body: OAuthExchangeRequest,
        authorization: str,
    ) -> _OAuthResponse:
        """Consume one authorization code and return one bearer token."""
        code = body.code
        client_id, client_secret = _oauth_client_credentials(body, authorization)
        client_valid = client_id == self.client_id
        secret_valid = client_secret == self.client_secret
        redirect_valid = body.redirect_uri == self.redirect_uri
        with self.lock:
            code_redirect = self._codes.pop(code, None) if code is not None else None
        code_valid = code_redirect == body.redirect_uri
        valid = client_valid and secret_valid and redirect_valid and code_valid
        payload: dict[str, object]
        if not valid or self.token_scenario == "rejected":
            outcome = "rejected"
            payload = {"ok": False, "error": "invalid_code"}
        elif self.token_scenario == "malformed":
            outcome = "malformed"
            payload = {"ok": True}
        else:
            token = f"slack-oauth-token-{self._sequence}"
            with self.lock:
                self._tokens.add(token)
            outcome = "exchanged"
            payload = {
                "ok": True,
                "access_token": token,
                "token_type": "Bearer",
            }
        self._record(
            "token",
            outcome,
            client_valid=client_valid,
            secret_valid=secret_valid,
            redirect_valid=redirect_valid,
            code_present=code is not None and bool(code),
            code_valid=code_valid,
            pkce_present=body.pkce_present,
        )
        return _OAuthResponse(200, payload, None)

    def userinfo(self, authorization: str) -> _OAuthResponse:
        """Return one deterministic identity for a valid bearer token."""
        token = authorization.removeprefix("Bearer ").strip()
        with self.lock:
            token_valid = token in self._tokens
        if not token_valid or self.userinfo_scenario == "rejected":
            outcome = "rejected"
            response = _OAuthResponse(
                401,
                {"ok": False, "error": "invalid_auth"},
                None,
            )
        elif self.userinfo_scenario == "malformed":
            outcome = "malformed"
            response = _OAuthResponse(200, {"ok": True, "sub": self.user_id}, None)
        else:
            outcome = "identified"
            response = _OAuthResponse(
                200,
                {
                    "ok": True,
                    "sub": self.user_id,
                    "name": self.user_label,
                    "https://slack.com/team_id": self.team_id,
                    "https://slack.com/team_name": self.team_label,
                },
                None,
            )
        self._record(
            "userinfo",
            outcome,
            authorization_present=bool(authorization),
            token_valid=token_valid,
        )
        return response

    def transient_handoff(self) -> dict[str, object] | None:
        """Return the callback URL only through transient test control state."""
        with self.lock:
            return dict(self._handoff) if self._handoff is not None else None

    def evidence(self) -> dict[str, object]:
        """Return OAuth evidence without codes, state, tokens, or secrets."""
        with self.lock:
            return {
                "requests": list(self.requests),
                "outstanding_code_count": len(self._codes),
                "active_token_count": len(self._tokens),
            }

    def _record(self, operation: str, outcome: str, **metadata: object) -> None:
        """Record only bounded OAuth request-shape observations."""
        with self.lock:
            self.requests.append(
                {"operation": operation, "outcome": outcome, **metadata}
            )


def _object(value: object) -> dict[str, object]:
    """Validate one provider object with string keys."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected an object with string keys.")
    return value


def _list(value: object) -> list[object]:
    """Validate one provider list."""
    if not isinstance(value, list):
        raise ValueError("Expected a list.")
    return value


def _string(value: object) -> str:
    """Validate one provider string."""
    if not isinstance(value, str):
        raise ValueError("Expected a string.")
    return value


def _query_one(query: dict[str, list[str]], name: str) -> str | None:
    """Return one exact OAuth query value or reject duplicate values."""
    values = query.get(name)
    if values is None or len(values) != 1:
        return None
    return values[0]


def _callback_url(redirect_uri: str, parameters: dict[str, str]) -> str:
    """Build one transient provider callback URL."""
    separator = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{separator}{urlencode(parameters)}"


class _OAuthClientCredentials(NamedTuple):
    client_id: str | None
    client_secret: str | None


def _oauth_client_credentials(
    body: OAuthExchangeRequest,
    authorization: str,
) -> _OAuthClientCredentials:
    """Resolve form or Basic client credentials for Slack SDK exchange."""
    client_id = body.client_id
    client_secret = body.client_secret
    if client_id is not None and client_secret is not None:
        return _OAuthClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
    encoded = authorization.removeprefix("Basic ").strip()
    if not encoded:
        return _OAuthClientCredentials(client_id=None, client_secret=None)
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except ValueError, UnicodeDecodeError:
        return _OAuthClientCredentials(client_id=None, client_secret=None)
    basic_client_id, separator, basic_client_secret = decoded.partition(":")
    if not separator:
        return _OAuthClientCredentials(client_id=None, client_secret=None)
    return _OAuthClientCredentials(
        client_id=basic_client_id,
        client_secret=basic_client_secret,
    )


def _socket(value: object) -> socket.socket:
    """Validate the accepted Socket Mode connection."""
    if not isinstance(value, socket.socket):
        raise TypeError("Expected a socket connection.")
    return value


class FakeState:
    """Thread-safe provider scenario and sanitized evidence store."""

    def __init__(self) -> None:
        self.oauth = SlackOAuthState()
        self.lock = Lock()
        self.reset()

    def reset(self) -> None:
        """Reset scenarios, provider data, and evidence between journeys."""
        self.oauth.reset()
        with self.lock:
            self.auth_scenario = "valid"
            self.membership_scenario = "member"
            self.history_scenario = "ok"
            self.history_scenario_sequence: list[str] = []
            self.history_retry_after_seconds: list[int] = []
            self.permalink_scenario = "ok"
            self.provider_app_id = "A-E2E"
            self.provider_team_id = "T-E2E"
            self.provider_bot_user_id = "U-BOT-E2E"
            self.granted_scopes = (
                "assistant:write",
                "app_mentions:read",
                "channels:history",
                "channels:read",
                "groups:history",
                "groups:read",
                "chat:write",
                "commands",
                "users:read",
                "files:read",
                "files:write",
            )
            self.delivery_scenarios: dict[str, str] = {
                "chat.postMessage": "delivered",
                "chat.update": "delivered",
                "chat.delete": "delivered",
            }
            self.delivery_scenario_sequences: dict[str, list[str]] = {}
            self.presence_scenarios: dict[str, str] = {
                "assistant.threads.setStatus": "delivered",
                "agents.sessions.setStatus": "delivered",
            }
            self.file_scenarios: dict[str, str] = {
                "files.info": "available",
                "file.download": "available",
                "files.getUploadURLExternal": "available",
                "file.upload": "available",
                "files.completeUploadExternal": "available",
            }
            self.view_scenarios: dict[str, str] = {
                "views.open": "available",
                "views.update": "available",
            }
            self.files: dict[str, ConfiguredFile] = {}
            self.uploads: dict[str, UploadState] = {}
            self.history_pages: list[list[dict[str, object]]] = []
            self.socket_sessions = [SocketSession(envelopes=[], disconnect_reason=None)]
            self.request_counts: dict[str, int] = {}
            self.requests: list[dict[str, object]] = []
            self.deliveries: list[dict[str, object]] = []
            self.presence: list[dict[str, object]] = []
            self.views: list[dict[str, object]] = []
            self._transient_views: dict[str, dict[str, object]] = {}
            self._transient_actions: dict[str, ActionHandoff] = {}
            self.socket_connections = 0
            self.socket_envelope_ids: list[str] = []
            self.socket_acknowledgements: list[str] = []
            self._message_sequence = 0
            self._upload_sequence = 0
            self._view_sequence = 0
            self._operation_barrier_operation: str | None = None
            self._operation_barrier_occurrence: int | None = None
            self._operation_barrier_reached = threading.Event()
            self._operation_barrier_release = threading.Event()

    def configure(self, payload: object) -> None:
        """Decode private controls once, then apply declared provider state."""
        config = decode_fake_configuration(payload)
        files = (
            {item.id: item for item in config.files}
            if config.files is not None
            else None
        )
        if config.oauth is not None:
            self.oauth.configure(config.oauth)
        with self.lock:
            if config.auth_scenario is not None:
                self.auth_scenario = config.auth_scenario
            if config.membership_scenario is not None:
                self.membership_scenario = config.membership_scenario
            if config.history_scenario is not None:
                self.history_scenario = config.history_scenario
            if config.permalink_scenario is not None:
                self.permalink_scenario = config.permalink_scenario
            if config.provider_app_id is not None:
                self.provider_app_id = config.provider_app_id
            if config.provider_team_id is not None:
                self.provider_team_id = config.provider_team_id
            if config.provider_bot_user_id is not None:
                self.provider_bot_user_id = config.provider_bot_user_id
            if config.granted_scopes is not None:
                self.granted_scopes = tuple(config.granted_scopes)
            if config.delivery_scenarios is not None:
                self.delivery_scenarios = config.delivery_scenarios
            if config.delivery_scenario_sequences is not None:
                self.delivery_scenario_sequences = config.delivery_scenario_sequences
            if config.presence_scenarios is not None:
                self.presence_scenarios = config.presence_scenarios
            if config.file_scenarios is not None:
                self.file_scenarios = config.file_scenarios
            if config.view_scenarios is not None:
                self.view_scenarios = config.view_scenarios
            if files is not None:
                self.files = files
            if config.history_pages is not None:
                self.history_pages = config.history_pages
            if config.history_scenario_sequence is not None:
                self.history_scenario_sequence = config.history_scenario_sequence
            if config.history_retry_after_seconds is not None:
                self.history_retry_after_seconds = config.history_retry_after_seconds
            if config.socket_sessions is not None:
                self.socket_sessions = config.socket_sessions
            self.request_counts = {}
            self.requests = []
            self.deliveries = []
            self.presence = []
            self.views = []
            self._transient_views = {}
            self._transient_actions = {}
            self.uploads = {}
            self.socket_connections = 0
            self.socket_envelope_ids = []
            self.socket_acknowledgements = []
            self._upload_sequence = 0
            self._view_sequence = 0
            self._operation_barrier_operation = None
            self._operation_barrier_occurrence = None
            self._operation_barrier_reached.clear()
            self._operation_barrier_release.clear()

    def record_request(
        self,
        operation: str,
        *,
        method: str,
        metadata: Mapping[str, object],
    ) -> None:
        """Record one sanitized provider call without credentials or message text."""
        with self.lock:
            self.request_counts[operation] = self.request_counts.get(operation, 0) + 1
            self.requests.append(
                {
                    "operation": operation,
                    "method": method,
                    **metadata,
                }
            )

    def next_history_scenario(self) -> str:
        """Return and consume one configured history outcome."""
        with self.lock:
            if self.history_scenario_sequence:
                return self.history_scenario_sequence.pop(0)
            return self.history_scenario

    def next_history_retry_after(self) -> int:
        """Return and consume one bounded provider Retry-After value."""
        with self.lock:
            if self.history_retry_after_seconds:
                return self.history_retry_after_seconds.pop(0)
            return 1

    def configure_operation_barrier(self, payload: object) -> None:
        """Decode and arm one exact provider operation barrier."""
        barrier = decode_operation_barrier(payload)
        with self.lock:
            self._operation_barrier_operation = barrier.operation
            self._operation_barrier_occurrence = barrier.occurrence
            self._operation_barrier_reached.clear()
            self._operation_barrier_release.clear()

    def operation_barrier_evidence(self) -> dict[str, object]:
        """Return safe barrier evidence without provider payloads."""
        with self.lock:
            operation = self._operation_barrier_operation
            occurrence = self._operation_barrier_occurrence
            request_count = (
                self.request_counts.get(operation, 0) if operation is not None else 0
            )
        return {
            "operation": operation,
            "occurrence": occurrence,
            "request_count": request_count,
            "reached": self._operation_barrier_reached.is_set(),
            "released": self._operation_barrier_release.is_set(),
        }

    def release_operation_barrier(self) -> None:
        """Release one armed provider operation."""
        self._operation_barrier_release.set()

    def wait_for_operation_barrier(self, operation: str) -> bool:
        """Hold one targeted provider operation until explicitly released."""
        with self.lock:
            if (
                self._operation_barrier_operation != operation
                or self._operation_barrier_occurrence is None
                or self.request_counts.get(operation, 0)
                != self._operation_barrier_occurrence
            ):
                return True
        self._operation_barrier_reached.set()
        return self._operation_barrier_release.wait(timeout=60)

    def next_message_timestamp(self) -> str:
        """Return one deterministic provider message identity."""
        with self.lock:
            self._message_sequence += 1
            return f"1721600100.{self._message_sequence:06d}"

    def next_upload(self, *, expected_length: int) -> _UploadAllocation:
        """Allocate one deterministic temporary upload identity and path."""
        with self.lock:
            self._upload_sequence += 1
            file_id = f"F-UPLOAD-{self._upload_sequence}"
            upload_path = f"/upload/{file_id}"
            self.uploads[file_id] = UploadState(
                expected_length=expected_length,
                received_length=None,
                uploaded=False,
                content_sha256=None,
            )
            return _UploadAllocation(file_id, upload_path)

    def record_upload(
        self,
        *,
        file_id: str,
        received_length: int,
        content_sha256: str,
    ) -> bool:
        """Record sanitized upload length and digest evidence."""
        with self.lock:
            upload = self.uploads.get(file_id)
            if upload is None:
                return False
            matched = upload.expected_length == received_length
            upload.received_length = received_length
            upload.content_sha256 = content_sha256
            upload.uploaded = matched
            return matched

    def record_view(
        self,
        *,
        operation: str,
        requested_view_id: str | None,
        callback_id: str | None,
        private_metadata: str | None,
        route_ids: list[str],
        has_submit: bool,
        control_handoff: ControlHandoff | dict[str, object],
    ) -> _RecordedView:
        """Record bounded view evidence without persisting signed metadata."""
        controls = decode_control_handoff(control_handoff)
        with self.lock:
            self._view_sequence += 1
            view_id = requested_view_id or f"V-E2E-{self._view_sequence}"
            view_hash = f"hash-{self._view_sequence}"
            control_scope = _view_control_scope(callback_id)
            evidence: dict[str, object] = {
                "operation": operation,
                "control_scope": control_scope,
                "route_count": len(route_ids),
                "has_submit": has_submit,
                "outcome": "delivered",
            }
            if control_scope == "model":
                evidence["control_count"] = len(controls.action_ids)
                evidence["input_count"] = len(controls.input_action_ids)
                evidence["option_count"] = sum(
                    len(values) for values in controls.option_values.values()
                )
            self.views.append(evidence)
            self._transient_views[control_scope] = {
                "view_id": view_id,
                "view_hash": view_hash,
                "private_metadata": private_metadata,
                "route_ids": route_ids,
                **controls.wire(),
            }
            return _RecordedView(view_id, view_hash)

    def transient_view(self, control_scope: str) -> dict[str, object] | None:
        """Return one test-local signed view handoff outside persistent evidence."""
        with self.lock:
            view = self._transient_views.get(control_scope)
            return dict(view) if view is not None else None

    def record_transient_actions(
        self,
        actions: list[ActionHandoff],
    ) -> None:
        """Retain signed Block Kit action values only in transient test state."""
        with self.lock:
            for action in actions:
                self._transient_actions[action.action_id] = action

    def transient_action(self, action_id: str) -> dict[str, object] | None:
        """Return one signed action handoff without adding it to evidence."""
        with self.lock:
            action = self._transient_actions.get(action_id)
            return action.wire() if action is not None else None

    def completed_uploads(
        self,
        file_ids: list[str],
    ) -> _CompletedUploads:
        """Return whether every ordered ID uploaded and its aggregate byte count."""
        with self.lock:
            total_bytes = 0
            for file_id in file_ids:
                upload = self.uploads.get(file_id)
                if upload is None or not upload.uploaded:
                    return _CompletedUploads(False, 0)
                received_length = upload.received_length
                if received_length is None:
                    return _CompletedUploads(False, 0)
                total_bytes += received_length
            return _CompletedUploads(True, total_bytes)

    def evidence(self) -> dict[str, object]:
        """Return sanitized evidence suitable for test assertions and failure output."""
        with self.lock:
            return {
                "request_counts": dict(self.request_counts),
                "requests": list(self.requests),
                "deliveries": list(self.deliveries),
                "presence": list(self.presence),
                "views": list(self.views),
                "oauth": self.oauth.evidence(),
                "socket": {
                    "connections": self.socket_connections,
                    "envelope_ids": list(self.socket_envelope_ids),
                    "acknowledgements": list(self.socket_acknowledgements),
                    "configured_sessions": len(self.socket_sessions),
                },
            }


STATE = FakeState()


class SlackHTTPHandler(BaseHTTPRequestHandler):
    """Serve controllable Slack Web API behavior and sanitized evidence."""

    state: ClassVar[FakeState] = STATE

    def do_GET(self) -> None:
        """Handle readiness, evidence, membership, history, and permalinks."""
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json_response(200, {"status": "ok"})
            return
        if parsed.path == "/__testenv/state":
            self._json_response(200, self.state.evidence())
            return
        if parsed.path == "/__testenv/barrier":
            self._json_response(200, self.state.operation_barrier_evidence())
            return
        if parsed.path == "/__testenv/transient-view":
            scope = parse_qs(parsed.query).get("scope", [""])[0]
            self._json_response(200, self.state.transient_view(scope) or {})
            return
        if parsed.path == "/__testenv/transient-action":
            action_id = parse_qs(parsed.query).get("action_id", [""])[0]
            self._json_response(200, self.state.transient_action(action_id) or {})
            return
        if parsed.path == "/__testenv/transient-oauth":
            self._json_response(200, self.state.oauth.transient_handoff() or {})
            return
        if parsed.path == "/oauth/authorize":
            self._oauth_response(
                self.state.oauth.authorize(
                    decode_oauth_authorize(
                        parse_qs(parsed.query, keep_blank_values=True)
                    )
                )
            )
            return
        if parsed.path == "/api/openid.connect.userInfo":
            self._oauth_response(
                self.state.oauth.userinfo(self.headers.get("Authorization", ""))
            )
            return
        if parsed.path.startswith("/files/"):
            provider_file_id = parsed.path.removeprefix("/files/")
            self.state.record_request(
                "file.download",
                method="GET",
                metadata={"file": provider_file_id},
            )
            self._file_download(provider_file_id)
            return
        operation = parsed.path.removeprefix("/api/")
        query = parse_qs(parsed.query)
        metadata = _query_metadata(query)
        self.state.record_request(operation, method="GET", metadata=metadata)
        if not self.state.wait_for_operation_barrier(operation):
            self._close_connection()
            return
        if operation == "conversations.info":
            self._conversation_info()
            return
        if operation == "users.info":
            self._user_info(query)
            return
        if operation in {"conversations.history", "conversations.replies"}:
            self._conversation_history(query)
            return
        if operation == "chat.getPermalink":
            self._permalink(query)
            return
        if operation == "bots.info":
            self._bot_info(query)
            return
        if operation == "files.info":
            self._file_info(query)
            return
        self._json_response(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        """Handle scenario control, validation, Socket endpoints, and delivery."""
        if self.path == "/__testenv/reset":
            self.state.reset()
            self._json_response(200, {"status": "reset"})
            return
        if self.path == "/__testenv/configure":
            try:
                self.state.configure(self._json_body())
            except ValueError:
                self._json_response(422, {"error": "invalid_configuration"})
                return
            self._json_response(200, {"status": "configured"})
            return
        if self.path == "/__testenv/barrier":
            try:
                self.state.configure_operation_barrier(self._json_body())
            except ValueError:
                self._json_response(422, {"error": "invalid_barrier"})
                return
            self._json_response(200, {"status": "configured"})
            return
        if self.path == "/__testenv/barrier/release":
            self.state.release_operation_barrier()
            self._json_response(200, {"status": "released"})
            return
        if self.path.startswith("/upload/"):
            file_id = urlparse(self.path).path.removeprefix("/upload/")
            self._file_upload(file_id)
            return
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/api/openid.connect.userInfo":
            self._oauth_response(
                self.state.oauth.userinfo(self.headers.get("Authorization", ""))
            )
            return
        if parsed_path.path == "/api/openid.connect.token":
            self._oauth_response(
                self.state.oauth.exchange(
                    decode_oauth_exchange(self._json_body()),
                    self.headers.get("Authorization", ""),
                )
            )
            return
        operation = parsed_path.path.removeprefix("/api/")
        query = {
            key: _form_value(key, values)
            for key, values in parse_qs(
                parsed_path.query,
                keep_blank_values=True,
            ).items()
        }
        body = {**query, **self._json_body()}
        self.state.record_request(
            operation,
            method="POST",
            metadata=decode_metadata(body).evidence(),
        )
        if not self.state.wait_for_operation_barrier(operation):
            self._close_connection()
            return
        if operation == "auth.test":
            self._auth_test()
            return
        if operation == "apps.connections.open":
            self._connections_open()
            return
        if operation in {"chat.postMessage", "chat.update", "chat.delete"}:
            self._delivery(operation, decode_message(body))
            return
        if operation in {
            "assistant.threads.setStatus",
            "agents.sessions.setStatus",
        }:
            self._presence(operation, decode_presence(body))
            return
        if operation in {"views.open", "views.update"}:
            self._view_mutation(operation, decode_view(body))
            return
        if operation == "files.getUploadURLExternal":
            self._get_upload_url(decode_upload_allocation(body))
            return
        if operation == "files.completeUploadExternal":
            self._complete_upload(decode_upload_completion(body))
            return
        self._json_response(404, {"ok": False, "error": "not_found"})

    def log_message(self, format: str, *args: object) -> None:
        """Avoid logging request headers, credentials, or provider message content."""
        del format, args

    def _oauth_response(self, response: _OAuthResponse) -> None:
        """Write one OAuth response without logging its transient redirect."""
        if response.redirect is not None:
            self.send_response(response.status)
            self.send_header("Location", response.redirect)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._json_response(response.status, response.payload or {})

    def _auth_test(self) -> None:
        scenario = self.state.auth_scenario
        if self._common_failure(scenario):
            return
        self._json_response(
            200,
            {
                "ok": True,
                "team_id": self.state.provider_team_id,
                "user_id": self.state.provider_bot_user_id,
                "bot_id": "B-E2E",
            },
            headers={"X-OAuth-Scopes": ",".join(self.state.granted_scopes)},
        )

    def _bot_info(self, query: dict[str, list[str]]) -> None:
        scenario = self.state.auth_scenario
        if self._common_failure(scenario):
            return
        bot_id = query.get("bot", [""])[0]
        self._json_response(
            200,
            {
                "ok": True,
                "bot": {
                    "id": bot_id,
                    "app_id": self.state.provider_app_id,
                },
            },
        )

    def _view_mutation(
        self,
        operation: str,
        body: ViewRequest,
    ) -> None:
        """Capture bounded selector state without retaining triggers or visible text."""
        with self.state.lock:
            scenario = self.state.view_scenarios.get(operation, "available")
        if scenario == "trigger_expired":
            self._json_response(200, {"ok": False, "error": "trigger_expired"})
            return
        if scenario == "invalid_hash":
            self._json_response(200, {"ok": False, "error": "invalid_hash"})
            return
        if self._common_failure(scenario):
            return
        typed_view = body.view
        route_ids = _selector_route_ids(typed_view)
        control_handoff = _view_control_handoff(typed_view)
        callback_id = typed_view.callback_id
        private_metadata = typed_view.private_metadata
        view_id, view_hash = self.state.record_view(
            operation=operation,
            requested_view_id=body.view_id,
            callback_id=callback_id,
            private_metadata=private_metadata,
            route_ids=route_ids,
            has_submit=typed_view.has_submit,
            control_handoff=control_handoff,
        )
        self._json_response(
            200,
            {
                "ok": True,
                "view": {
                    "id": view_id,
                    "hash": view_hash,
                },
            },
        )

    def _user_info(self, query: dict[str, list[str]]) -> None:
        scenario = self.state.auth_scenario
        if self._common_failure(scenario):
            return
        user_id = query.get("user", ["unknown"])[0]
        self._json_response(
            200,
            {
                "ok": True,
                "user": {
                    "id": user_id,
                    "name": user_id.lower(),
                    "real_name": f"User {user_id}",
                    "profile": {
                        "display_name": f"User {user_id}",
                        "real_name": f"User {user_id}",
                    },
                },
            },
        )

    def _conversation_info(self) -> None:
        scenario = self.state.membership_scenario
        if self._common_failure(scenario):
            return
        self._json_response(
            200,
            {
                "ok": True,
                "channel": {
                    "name": "e2e",
                    "is_member": scenario != "not_member",
                    "is_channel": scenario != "dm",
                    "is_group": False,
                    "is_ext_shared": scenario == "slack_connect",
                    "is_org_shared": False,
                    "is_im": scenario == "dm",
                    "is_mpim": False,
                },
            },
        )

    def _conversation_history(self, query: dict[str, list[str]]) -> None:
        scenario = self.state.next_history_scenario()
        retry_after_seconds = (
            self.state.next_history_retry_after() if scenario == "rate_limited" else 1
        )
        if self._common_failure(
            scenario,
            retry_after_seconds=retry_after_seconds,
        ):
            return
        cursor = query.get("cursor", [None])[0]
        try:
            page_index = int(cursor.removeprefix("page-")) if cursor else 0
        except ValueError:
            page_index = 0
        with self.state.lock:
            pages = list(self.state.history_pages)
        messages = pages[page_index] if page_index < len(pages) else []
        next_cursor = f"page-{page_index + 1}" if page_index + 1 < len(pages) else ""
        self._json_response(
            200,
            {
                "ok": True,
                "messages": messages,
                "response_metadata": {"next_cursor": next_cursor},
            },
        )

    def _permalink(self, query: dict[str, list[str]]) -> None:
        scenario = self.state.permalink_scenario
        if self._common_failure(scenario):
            return
        channel = query.get("channel", ["C-E2E"])[0]
        timestamp = query.get("message_ts", ["1721600000.000100"])[0]
        self._json_response(
            200,
            {
                "ok": True,
                "permalink": (
                    f"https://example.slack.com/archives/{channel}/"
                    f"p{timestamp.replace('.', '')}"
                ),
            },
        )

    def _connections_open(self) -> None:
        scenario = self.state.auth_scenario
        if self._common_failure(scenario):
            return
        self._json_response(
            200,
            {
                "ok": True,
                "url": f"ws://slack-fake:{_WEBSOCKET_PORT}/socket",
            },
        )

    def _file_info(self, query: dict[str, list[str]]) -> None:
        scenario = self.state.file_scenarios.get("files.info", "available")
        if self._file_failure(scenario):
            return
        provider_file_id = query.get("file", [""])[0]
        with self.state.lock:
            configured = self.state.files.get(provider_file_id)
            metadata = dict(configured.metadata) if configured is not None else None
        if metadata is None:
            self._json_response(200, {"ok": False, "error": "file_not_found"})
            return
        host = self.headers.get("Host") or f"slack-fake:{_HTTP_PORT}"
        metadata["url_private_download"] = f"http://{host}/files/{provider_file_id}"
        if scenario == "malformed":
            metadata["id"] = "F-MISMATCH"
        self._json_response(200, {"ok": True, "file": metadata})

    def _file_download(self, provider_file_id: str) -> None:
        scenario = self.state.file_scenarios.get("file.download", "available")
        if scenario == "ambiguous":
            self._close_connection()
            return
        if scenario == "timeout":
            time.sleep(21)
            return
        if scenario == "rate_limited":
            self._json_response(
                429,
                {"ok": False, "error": "ratelimited"},
                headers={"Retry-After": "1"},
            )
            return
        if scenario == "revoked":
            self._json_response(401, {"ok": False, "error": "token_revoked"})
            return
        if scenario == "missing_scope":
            self._json_response(403, {"ok": False, "error": "missing_scope"})
            return
        if scenario in {"missing", "rejected"}:
            status = 404 if scenario == "missing" else 400
            self._json_response(status, {"ok": False, "error": "file_not_found"})
            return
        if scenario == "unavailable":
            self._json_response(503, {"ok": False, "error": "unavailable"})
            return
        with self.state.lock:
            configured = self.state.files.get(provider_file_id)
            content = configured.content if configured is not None else None
        if content is None:
            self._json_response(404, {"ok": False, "error": "file_not_found"})
            return
        declared_length = len(content)
        if scenario == "size_mismatch":
            declared_length += 1
        self._bytes_response(
            200,
            content,
            headers={"Content-Length": str(declared_length)},
        )

    def _get_upload_url(self, body: UploadAllocationRequest) -> None:
        scenario = self.state.file_scenarios.get(
            "files.getUploadURLExternal",
            "available",
        )
        if self._file_failure(scenario):
            return
        length = body.length
        if length is None:
            self._json_response(200, {"ok": False, "error": "invalid_arguments"})
            return
        file_id, upload_path = self.state.next_upload(expected_length=length)
        host = self.headers.get("Host") or f"slack-fake:{_HTTP_PORT}"
        self._json_response(
            200,
            {
                "ok": True,
                "upload_url": f"http://{host}{upload_path}",
                "file_id": file_id,
            },
        )

    def _file_upload(self, file_id: str) -> None:
        scenario = self.state.file_scenarios.get("file.upload", "available")
        content_length = int(self.headers.get("Content-Length", "0"))
        content = self.rfile.read(content_length)
        self.state.record_request(
            "file.upload",
            method="POST",
            metadata={
                "file": file_id,
                "content_length": content_length,
                "received_length": len(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
            },
        )
        if scenario == "ambiguous":
            self._close_connection()
            return
        if scenario == "timeout":
            time.sleep(21)
            return
        if scenario == "rate_limited":
            self._bytes_response(429, b"rate_limited")
            return
        if scenario == "unavailable":
            self._bytes_response(503, b"unavailable")
            return
        matched = self.state.record_upload(
            file_id=file_id,
            received_length=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
        if scenario in {"rejected", "size_mismatch"} or not matched:
            self._bytes_response(400, b"rejected")
            return
        self._bytes_response(200, b"OK")

    def _complete_upload(self, body: UploadCompletionRequest) -> None:
        scenario = self.state.file_scenarios.get(
            "files.completeUploadExternal",
            "available",
        )
        if scenario == "ambiguous":
            self._close_connection()
            return
        if scenario == "timeout":
            time.sleep(21)
            return
        if self._file_failure(scenario):
            return
        file_ids: list[str] = []
        for file_id in body.file_ids:
            if file_id is None:
                self._json_response(
                    200,
                    {"ok": False, "error": "file_not_found"},
                )
                return
            file_ids.append(file_id)
        completed, total_bytes = self.state.completed_uploads(file_ids)
        if not file_ids or not completed:
            self._json_response(200, {"ok": False, "error": "file_not_found"})
            return
        delivery: dict[str, object] = {
            "operation": "files.completeUploadExternal",
            "channel": body.channel_id,
            "thread_ts": body.thread_ts,
            "file_ids": file_ids,
            "file_count": len(file_ids),
            "total_bytes": total_bytes,
            "has_initial_comment": body.has_initial_comment,
            "outcome": "delivered",
        }
        with self.state.lock:
            self.state.deliveries.append(delivery)
        self._json_response(200, {"ok": True, "files": []})

    def _delivery(self, operation: str, body: MessageRequest) -> None:
        with self.state.lock:
            sequence = self.state.delivery_scenario_sequences.get(operation)
            if sequence:
                scenario = sequence.pop(0)
                if not sequence:
                    self.state.delivery_scenario_sequences.pop(operation, None)
            else:
                scenario = self.state.delivery_scenarios.get(operation, "delivered")
        if scenario == "ambiguous":
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        if scenario == "timeout":
            time.sleep(21)
            return
        if self._common_failure(scenario):
            return
        timestamp = body.ts or self.state.next_message_timestamp()
        approval_request_id = _approval_request_id(body)
        action_ids, selector_admission_id = _selector_control_evidence(body)
        self.state.record_transient_actions(_block_action_handoffs(body))
        delivery: dict[str, object] = {
            "operation": operation,
            "channel": body.channel,
            "thread_ts": body.thread_ts,
            "message_ts": timestamp,
            "outcome": "delivered",
            "approval_request_id": approval_request_id,
        }
        session_path = _session_path(body)
        if session_path is not None:
            delivery["session_path"] = session_path
        presence_state = _session_presence_state(body)
        if presence_state is not None:
            delivery["safe_category"] = f"session_presence_{presence_state}"
        elif session_path is not None:
            delivery["safe_category"] = "activity_tracker"
        if action_ids:
            delivery["action_ids"] = action_ids
        if selector_admission_id is not None:
            delivery["selector_admission_id"] = selector_admission_id
        if operation == "chat.update" and body.has_plan:
            delivery["text"] = body.text
            delivery["blocks"] = body.blocks_wire
        with self.state.lock:
            self.state.deliveries.append(delivery)
        self._json_response(200, {"ok": True, "ts": timestamp})

    def _presence(self, operation: str, body: PresenceRequest) -> None:
        """Record sanitized Slack Work status without retaining titles or users."""
        with self.state.lock:
            scenario = self.state.presence_scenarios.get(operation, "delivered")
        if scenario == "feature_disabled":
            self._json_response(200, {"ok": False, "error": "feature_disabled"})
            return
        if scenario == "missing_scope":
            self._json_response(200, {"ok": False, "error": "missing_scope"})
            return
        if self._common_failure(scenario):
            return
        status = body.status
        evidence: dict[str, object] = {
            "operation": operation,
            "channel": body.channel_id,
            "thread_ts": body.thread_ts,
            "desired_state": ("idle" if status in {"", "active"} else "processing"),
            "has_initiator": body.initiator_user_id is not None,
            "outcome": "delivered",
        }
        with self.state.lock:
            self.state.presence.append(evidence)
        self._json_response(200, {"ok": True})

    def _file_failure(self, scenario: str) -> bool:
        if scenario == "ambiguous":
            self._close_connection()
            return True
        if scenario == "timeout":
            time.sleep(21)
            return True
        if scenario == "missing_scope":
            self._json_response(200, {"ok": False, "error": "missing_scope"})
            return True
        if scenario in {"missing", "rejected"}:
            self._json_response(200, {"ok": False, "error": "file_not_found"})
            return True
        return self._common_failure(scenario)

    def _close_connection(self) -> None:
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

    def _common_failure(
        self,
        scenario: str,
        *,
        retry_after_seconds: int = 1,
    ) -> bool:
        if scenario == "invalid":
            self._json_response(200, {"ok": False, "error": "invalid_auth"})
            return True
        if scenario == "revoked":
            self._json_response(200, {"ok": False, "error": "token_revoked"})
            return True
        if scenario == "rate_limited":
            self._json_response(
                429,
                {"ok": False, "error": "ratelimited"},
                headers={"Retry-After": str(retry_after_seconds)},
            )
            return True
        if scenario in {"unavailable", "failed"}:
            status = 503 if scenario == "unavailable" else 200
            self._json_response(
                status,
                {"ok": False, "error": "channel_not_found"},
            )
            return True
        return False

    def _json_body(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/x-www-form-urlencoded"):
            try:
                encoded = raw_body.decode()
            except UnicodeDecodeError:
                return {}
            return {
                key: _form_value(key, values)
                for key, values in parse_qs(
                    encoded,
                    keep_blank_values=True,
                ).items()
            }
        try:
            payload: object = json.loads(raw_body)
        except UnicodeDecodeError:
            return {}
        except json.JSONDecodeError:
            return {}
        return _object(payload) if isinstance(payload, dict) else {}

    def _json_response(
        self,
        status: int,
        payload: Mapping[str, object],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if headers is not None:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _bytes_response(
        self,
        status: int,
        body: bytes,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        if headers is None or "Content-Length" not in headers:
            self.send_header("Content-Length", str(len(body)))
        if headers is not None:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


class SlackWebSocketHandler(socketserver.BaseRequestHandler):
    """Serve a minimal deterministic Socket Mode WebSocket."""

    state: ClassVar[FakeState] = STATE
    socket_timeout_seconds: ClassVar[float] = 10

    def handle(self) -> None:
        """Perform the handshake, send configured envelopes, and capture ACKs."""
        request = _socket(self.request)
        request.settimeout(self.socket_timeout_seconds)
        headers = _read_http_headers(request)
        key = headers.get("sec-websocket-key")
        if key is None:
            return
        accept = base64.b64encode(
            hashlib.sha1(f"{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode()).digest()
        ).decode()
        request.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        with self.state.lock:
            session_index = min(
                self.state.socket_connections,
                len(self.state.socket_sessions) - 1,
            )
            self.state.socket_connections += 1
            session = self.state.socket_sessions[session_index]
            envelopes = session.envelopes
            disconnect_reason = session.disconnect_reason
        _send_websocket_text(request, json.dumps({"type": "hello"}))
        for envelope in envelopes:
            envelope_id = envelope.envelope_id
            if envelope_id is not None:
                with self.state.lock:
                    self.state.socket_envelope_ids.append(envelope_id)
            _send_websocket_text(
                request,
                json.dumps(envelope.wire, separators=(",", ":")),
            )
            acknowledged_id = _receive_websocket_acknowledgement(request)
            if acknowledged_id is None:
                return
            with self.state.lock:
                self.state.socket_acknowledgements.append(acknowledged_id)
        if disconnect_reason is not None:
            _send_websocket_text(
                request,
                json.dumps(
                    {
                        "type": "disconnect",
                        "payload": {"reason": disconnect_reason},
                    },
                    separators=(",", ":"),
                ),
            )
            return
        while True:
            try:
                if not _receive_websocket_text(request):
                    return
            except TimeoutError:
                continue
            except ConnectionError:
                return
            except OSError:
                return


class ThreadingSocketServer(socketserver.ThreadingTCPServer):
    """Reusable threaded TCP server for deterministic WebSocket sessions."""

    allow_reuse_address = True
    daemon_threads = True


def _form_value(key: str, values: list[str]) -> object:
    """Restore typed Slack form fields while preserving identifiers as strings."""
    if len(values) != 1:
        return values
    value = values[0]
    if key == "length":
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, int) and not isinstance(parsed, bool):
            return parsed
        return value
    if key not in {"files", "blocks"}:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _approval_request_id(payload: MessageRequest) -> str | None:
    """Read approval identity from typed visible text and Block Kit URLs."""
    values = [payload.text]
    values.extend(element.url for block in payload.blocks for element in block.elements)
    for value in values:
        if value is not None and (match := _APPROVAL_PATH.search(value)) is not None:
            return match.group(1)
    return None


def _selector_control_evidence(payload: MessageRequest) -> _SelectorControlEvidence:
    """Return action IDs and opaque selector admission without visible copy."""
    action_ids: list[str] = []
    selector_admission_id: str | None = None
    for block in payload.blocks:
        for element in block.elements:
            if element.action_id is None:
                continue
            action_ids.append(element.action_id)
            if (
                element.action_id == "azents_agent_selector_open"
                and element.value is not None
            ):
                selector_admission_id = element.value
    return _SelectorControlEvidence(action_ids, selector_admission_id)


def _query_metadata(query: dict[str, list[str]]) -> dict[str, object]:
    """Project only privacy-safe query fields parsed by the HTTP ingress."""
    return {
        key: values[0]
        for key, values in query.items()
        if key in {"channel", "user", "ts", "message_ts", "cursor", "limit", "file"}
        and values
    }


def _session_path(body: MessageRequest) -> str | None:
    """Extract only the relative Azents Session route from a typed control."""
    for block in body.blocks:
        for element in block.elements:
            if element.action_id != "view_azents_session":
                continue
            if element.url is None:
                return None
            parsed = urlparse(element.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return None
            return parsed.path if parsed.path.startswith("/w/") else None
    return None


def _session_presence_state(body: MessageRequest) -> str | None:
    """Classify presence without retaining Agent-authored display text."""
    if _session_path(body) is None:
        return None
    for block in body.blocks:
        if block.text is None or block.text.text is None:
            continue
        rendered = block.text.text
        if rendered.endswith(" joined this conversation."):
            return "joined"
        if rendered.endswith(" left this conversation."):
            return "left"
    return None


def _selector_route_ids(view: ViewObservation) -> list[str]:
    """Extract selector option identities from decoded modal controls."""
    return [
        option.value
        for block in view.blocks
        if block.element is not None
        for option in block.element.options
        if option.value is not None
    ]


def _view_control_scope(callback_id: str | None) -> str:
    """Classify supported modal scope without retaining callback metadata."""
    if callback_id == "azents_agent_selector":
        return "selector"
    if callback_id == "azents_conversation_setup":
        return "setup"
    if callback_id == "azents_conversation_settings":
        return "settings"
    if callback_id == "azents_model_apply":
        return "model"
    return "unknown"


def _view_control_handoff(view: ViewObservation) -> ControlHandoff:
    """Extract opaque control identities for the next signed callback."""
    action_ids: list[str] = []
    input_action_ids: list[str] = []
    block_ids: list[str] = []
    option_values: dict[str, list[str]] = {}
    option_labels: dict[str, dict[str, str]] = {}
    action_values: dict[str, str] = {}
    link_paths: list[str] = []
    for block in view.blocks:
        if block.block_id is not None:
            block_ids.append(block.block_id)
        elements = [block.element] if block.element is not None else []
        elements.extend([block.accessory] if block.accessory is not None else [])
        elements.extend(block.elements)
        for element in elements:
            if element.url is not None:
                parsed = urlparse(element.url)
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    link_paths.append(parsed.path)
            action_id = element.action_id
            if action_id is None:
                continue
            action_ids.append(action_id)
            if element.type == "plain_text_input":
                input_action_ids.append(action_id)
            if element.value is not None:
                action_values[action_id] = element.value
            values = [
                option.value for option in element.options if option.value is not None
            ]
            labels = {
                option.value: option.text.text
                for option in element.options
                if option.value is not None
                and option.text is not None
                and option.text.text
            }
            if element.initial_option is not None:
                initial = element.initial_option.value
                if initial is not None and initial not in values:
                    values.append(initial)
            if values:
                option_values[action_id] = values
            if labels:
                option_labels[action_id] = labels
    return ControlHandoff(
        action_ids=action_ids,
        input_action_ids=input_action_ids,
        block_ids=block_ids,
        option_values=option_values,
        option_labels=option_labels,
        action_values=action_values,
        link_paths=link_paths,
        supplied_fields=frozenset(
            {
                "action_ids",
                "input_action_ids",
                "block_ids",
                "option_values",
                "option_labels",
                "action_values",
                "link_paths",
            }
        ),
    )


def _block_action_handoffs(payload: MessageRequest) -> list[ActionHandoff]:
    """Retain signed action values transiently, without visible Block Kit copy."""
    return [
        ActionHandoff(
            action_id=element.action_id, block_id=block.block_id, value=element.value
        )
        for block in payload.blocks
        for element in block.elements
        if element.action_id is not None
    ]


def _read_http_headers(connection: socket.socket) -> dict[str, str]:
    raw = bytearray()
    while b"\r\n\r\n" not in raw and len(raw) < 16 * 1024:
        chunk = connection.recv(4096)
        if not chunk:
            break
        raw.extend(chunk)
    lines = raw.decode(errors="replace").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if separator:
            headers[name.strip().lower()] = value.strip()
    return headers


def _send_websocket_text(connection: socket.socket, text: str) -> None:
    _send_websocket_frame(connection, opcode=0x1, payload=text.encode())


def _send_websocket_frame(
    connection: socket.socket,
    *,
    opcode: int,
    payload: bytes,
) -> None:
    header = bytearray([0x80 | opcode])
    if len(payload) < 126:
        header.append(len(payload))
    elif len(payload) < 65_536:
        header.append(126)
        header.extend(struct.pack("!H", len(payload)))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", len(payload)))
    connection.sendall(bytes(header) + payload)


def _receive_websocket_text(connection: socket.socket) -> str:
    while True:
        first, second = _receive_exact(connection, 2)
        opcode = first & 0x0F
        masked = second & 0x80
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", _receive_exact(connection, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _receive_exact(connection, 8))[0]
        mask = _receive_exact(connection, 4) if masked else b""
        payload = bytearray(_receive_exact(connection, length))
        if mask:
            for index in range(len(payload)):
                payload[index] ^= mask[index % 4]
        if opcode == 0x8:
            return ""
        if opcode == 0x9:
            _send_websocket_frame(connection, opcode=0xA, payload=bytes(payload))
            continue
        if opcode == 0xA:
            continue
        if opcode == 0x1:
            return payload.decode()
        raise ConnectionError("Unsupported WebSocket frame.")


def _receive_websocket_acknowledgement(connection: socket.socket) -> str | None:
    """Wait for one ACK while the client connection remains open."""
    previous_timeout = connection.gettimeout()
    connection.settimeout(None)
    try:
        while True:
            try:
                acknowledgement = _receive_websocket_text(connection)
            except OSError:
                return None
            if not acknowledgement:
                return None
            try:
                payload: object = json.loads(acknowledgement)
            except json.JSONDecodeError:
                continue
            acknowledged_id = decode_acknowledgement(payload)
            if acknowledged_id is not None:
                return acknowledged_id
    finally:
        connection.settimeout(previous_timeout)


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise ConnectionError("WebSocket connection closed.")
        result.extend(chunk)
    return bytes(result)


def serve() -> None:
    """Run the HTTP and WebSocket fake services until the process exits."""
    websocket_server = ThreadingSocketServer(
        ("0.0.0.0", _WEBSOCKET_PORT),
        SlackWebSocketHandler,
    )
    websocket_thread = threading.Thread(
        target=websocket_server.serve_forever,
        daemon=True,
    )
    websocket_thread.start()
    try:
        ThreadingHTTPServer(
            ("0.0.0.0", _HTTP_PORT),
            SlackHTTPHandler,
        ).serve_forever()
    finally:
        websocket_server.shutdown()
        websocket_server.server_close()


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    serve()
