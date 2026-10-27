"""Exact Browser source purpose, connection scope and bounded validity tests."""

import base64
import dataclasses
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.browser_source_contract import (
    BROWSER_SOURCE_AUDIENCE,
    BROWSER_SOURCE_OPERATION,
    BrowserSourceCredentialRequest,
)
from azents_runtime_control.proto import runtime_stream_session_pb2 as pb
from azents_runtime_control.runtime_stream_authority_codec import (
    encode_stream_authority,
)
from azents_runtime_control.runtime_stream_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
    BrowserStreamAuthority,
)

from azents.core.runtime_browser_source_credential import (
    RuntimeBrowserSourceCredentialInvalid,
    RuntimeBrowserSourceCredentialVerifier,
)

KEY = base64.urlsafe_b64encode(b"b" * 32).decode()
NOW = datetime(2026, 10, 15, tzinfo=UTC)


def source_request(now: datetime = NOW) -> BrowserSourceCredentialRequest:
    profile = APPROVED_SESSION_PROFILE
    hello = pb.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id="source-session",
        peer_boot_id="api-boot",
        hello=pb.RuntimeStreamSessionHello(
            role=pb.RUNTIME_STREAM_SESSION_PEER_ROLE_API_BROWSER,
            session_nonce="hello-nonce",
            maximum_data_frame_bytes=profile.data_frame_bytes,
            request_stream_window_bytes=profile.request_stream_window_bytes,
            response_stream_window_bytes=profile.response_stream_window_bytes,
            request_session_window_bytes=profile.request_session_window_bytes,
            response_session_window_bytes=profile.response_session_window_bytes,
        ),
    )
    deadline = now + timedelta(minutes=10)
    hello.hello.deadline_at.FromDatetime(deadline)
    authority = BrowserStreamAuthority(
        correlation_id="correlation",
        authentication_session_id="authentication-session",
        user_id="user",
        agent_id="agent",
        runtime_id="runtime",
        desired_generation=1,
        runner_generation=2,
        open_deadline_at=now + timedelta(seconds=8),
        transport_deadline_at=deadline,
        session_id="concrete-session",
        task_id="task",
        page_id="page",
        resource_incarnation="incarnation",
        allow_input=False,
    )
    opened = pb.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        session_id=hello.session_id,
        peer_boot_id=hello.peer_boot_id,
        stream_id=1,
        open=pb.RuntimeStreamSessionOpen(
            authority=encode_stream_authority(authority),
            request_head=pb.RuntimeStreamSessionRequestHead(
                protocol=pb.RUNTIME_STREAM_SESSION_PROTOCOL_WEBSOCKET,
                method=b"GET",
                target=b"/browser",
            ),
        ),
    )
    return BrowserSourceCredentialRequest(
        "a" * 64, "control-boot", now + timedelta(seconds=10), hello, opened
    )


@pytest.mark.parametrize("field", range(5))
def test_browser_source_rejects_each_incompatible_profile_field(field: int) -> None:
    """Every fixed profile dimension is independently enforced."""
    request = source_request()
    profile = request.hello.hello
    match field:
        case 0:
            profile.maximum_data_frame_bytes += 1
        case 1:
            profile.request_stream_window_bytes += 1
        case 2:
            profile.response_stream_window_bytes += 1
        case 3:
            profile.request_session_window_bytes += 1
        case 4:
            profile.response_session_window_bytes += 1
    with pytest.raises(ValueError, match="profile is incompatible"):
        request.validate(NOW)


def test_browser_proof_roundtrip_does_not_make_live_lifetime_proof_lifetime() -> None:
    request = source_request()
    verifier = RuntimeBrowserSourceCredentialVerifier(KEY, clock=lambda: NOW)
    credential = verifier.issue(request)
    verifier.verify(credential, request=request)
    assert request.validate(NOW).transport_deadline_at == NOW + timedelta(minutes=10)


@pytest.mark.parametrize(
    "mutation",
    [
        "nonce",
        "replica",
        "input",
        "page",
        "session",
        "user",
        "auth",
        "generation",
        "profile",
        "head",
        "role",
        "deadline",
        "web",
    ],
)
def test_browser_proof_rejects_altered_exact_scope(mutation: str) -> None:
    request = source_request()
    verifier = RuntimeBrowserSourceCredentialVerifier(KEY, clock=lambda: NOW)
    credential = verifier.issue(request)
    hello = pb.RuntimeStreamSessionEnvelope()
    hello.CopyFrom(request.hello)
    opened = pb.RuntimeStreamSessionEnvelope()
    opened.CopyFrom(request.open_envelope)
    changed = dataclasses.replace(request, hello=hello, open_envelope=opened)
    match mutation:
        case "nonce":
            changed = dataclasses.replace(changed, challenge_nonce="c" * 64)
        case "replica":
            changed = dataclasses.replace(
                changed, control_boot_id="replacement-control"
            )
        case "input":
            opened.open.authority.browser.allow_input = True
        case "page":
            opened.open.authority.browser.page_id = "other-page"
        case "session":
            opened.open.authority.browser.session_id = "other-session"
        case "user":
            opened.open.authority.user_id = "other-user"
        case "auth":
            opened.open.authority.authentication_session_id = "other-auth"
        case "generation":
            opened.open.authority.runner_generation = 3
        case "profile":
            hello.hello.request_session_window_bytes += 1
        case "head":
            opened.open.request_head.target = b"/anything"
        case "role":
            hello.hello.role = pb.RUNTIME_STREAM_SESSION_PEER_ROLE_GATEWAY
        case "deadline":
            opened.open.authority.transport_deadline_at.FromDatetime(
                NOW + timedelta(hours=2)
            )
        case "web":
            opened.open.authority.web.service_id = "web-service"
    with pytest.raises(RuntimeBrowserSourceCredentialInvalid):
        verifier.verify(credential, request=changed)


@pytest.mark.parametrize("seconds", [10, 31, 3601])
def test_browser_initial_proof_expiry_requires_fresh_admission(seconds: int) -> None:
    request = source_request()
    issuer = RuntimeBrowserSourceCredentialVerifier(KEY, clock=lambda: NOW)
    credential = issuer.issue(request)
    verifier = RuntimeBrowserSourceCredentialVerifier(
        KEY, clock=lambda: NOW + timedelta(seconds=seconds)
    )
    with pytest.raises(RuntimeBrowserSourceCredentialInvalid):
        verifier.verify(credential, request=request)


@pytest.mark.parametrize(
    "credential",
    ["ctr1.body.signature", "brs1.invalid.invalid", "brs1..", "", " brs1.x.y"],
)
def test_browser_wrong_purpose_or_malformed_proof_is_rejected(credential: str) -> None:
    with pytest.raises(RuntimeBrowserSourceCredentialInvalid):
        RuntimeBrowserSourceCredentialVerifier(KEY, clock=lambda: NOW).verify(
            credential, request=source_request()
        )


@pytest.mark.parametrize(
    "mutation",
    ["extra", "missing", "null", "number", "bool", "list", "object"],
)
def test_signed_browser_proof_rejects_nonclosed_or_nonstring_payload(
    mutation: str,
) -> None:
    request = source_request()
    verifier = RuntimeBrowserSourceCredentialVerifier(KEY, clock=lambda: NOW)
    payload: dict[str, object] = {
        "audience": BROWSER_SOURCE_AUDIENCE,
        "operation": BROWSER_SOURCE_OPERATION,
        "service_identity": "azents-api",
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(seconds=5)).isoformat(),
        "request_sha256": request.digest(),
    }
    match mutation:
        case "extra":
            payload["unexpected"] = "private-input"
        case "missing":
            del payload["issued_at"]
        case "null":
            payload["issued_at"] = None
        case "number":
            payload["issued_at"] = 123
        case "bool":
            payload["issued_at"] = True
        case "list":
            payload["issued_at"] = ["private-input"]
        case "object":
            payload["issued_at"] = {"value": "private-input"}
    encoded = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    )
    key = hmac.new(
        base64.urlsafe_b64decode(KEY),
        b"azents/runtime-browser-source-proof/v1",
        hashlib.sha256,
    ).digest()
    signature = (
        base64.urlsafe_b64encode(
            hmac.new(key, encoded.encode(), hashlib.sha256).digest()
        )
        .decode()
        .rstrip("=")
    )
    with pytest.raises(RuntimeBrowserSourceCredentialInvalid) as error:
        verifier.verify(f"brs1.{encoded}.{signature}", request=request)
    assert str(error.value) == "Browser source credential is invalid"
