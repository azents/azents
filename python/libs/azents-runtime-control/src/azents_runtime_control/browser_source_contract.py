"""Connection-bound proof scope for an API-owned Browser stream."""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from azents_runtime_control.proto import runtime_stream_session_pb2 as pb
from azents_runtime_control.runtime_stream_authority_codec import (
    decode_stream_authority,
)
from azents_runtime_control.runtime_stream_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
    BrowserStreamAuthority,
)

BROWSER_SOURCE_AUDIENCE = "azents/runtime-browser-source"
BROWSER_SOURCE_OPERATION = "RuntimeBrowserSourceSession/Connect"
BROWSER_SOURCE_SETUP_SECONDS = 10
BROWSER_SOURCE_MAXIMUM_SECONDS = 3600


class BrowserScopeState(StrEnum):
    """Current authority classification, independent of native resource lifetime."""

    CURRENT = "current"
    UNAVAILABLE = "unavailable"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass(frozen=True)
class BrowserSourceCredentialRequest:
    """Exact server challenge, source Hello and single admitted OPEN."""

    challenge_nonce: str
    control_boot_id: str
    challenge_deadline_at: datetime
    hello: pb.RuntimeStreamSessionEnvelope
    open_envelope: pb.RuntimeStreamSessionEnvelope

    def digest(self) -> str:
        """Bind unambiguous lengths and deterministic wire bytes to the proof."""
        chunks = (
            BROWSER_SOURCE_AUDIENCE.encode(),
            BROWSER_SOURCE_OPERATION.encode(),
            self.challenge_nonce.encode(),
            self.control_boot_id.encode(),
            self.challenge_deadline_at.isoformat().encode(),
            self.hello.SerializeToString(deterministic=True),
            self.open_envelope.SerializeToString(deterministic=True),
        )
        digest = hashlib.sha256()
        for chunk in chunks:
            digest.update(len(chunk).to_bytes(8, "big"))
            digest.update(chunk)
        return digest.hexdigest()

    def validate(self, now: datetime) -> BrowserStreamAuthority:
        """Reject incomplete, wrong-domain or unbounded admission before effects."""
        if (
            now.tzinfo is None
            or self.challenge_deadline_at.tzinfo is None
            or not re.fullmatch(r"[0-9a-f]{64}", self.challenge_nonce)
            or not 0 < len(self.control_boot_id) <= 128
            or not now < self.challenge_deadline_at <= now + timedelta(seconds=10)
        ):
            raise ValueError("Browser source challenge is invalid or expired")
        hello = self.hello
        opened = self.open_envelope
        if (
            hello.WhichOneof("payload") != "hello"
            or hello.stream_id != 0
            or hello.frame_sequence != 0
            or hello.protocol_fingerprint != RUNTIME_STREAM_PROTOCOL_FINGERPRINT
            or not 0 < len(hello.session_id) <= 128
            or not 0 < len(hello.peer_boot_id) <= 128
            or hello.hello.role != pb.RUNTIME_STREAM_SESSION_PEER_ROLE_API_BROWSER
            or not hello.hello.HasField("deadline_at")
            or any(
                hello.HasField(name)
                for name in ("owner_boot_id", "session_lease_id", "lease_generation")
            )
            or opened.WhichOneof("payload") != "open"
            or opened.stream_id != 1
            or opened.frame_sequence != 0
            or opened.session_id != hello.session_id
            or opened.peer_boot_id != hello.peer_boot_id
            or opened.protocol_fingerprint != RUNTIME_STREAM_PROTOCOL_FINGERPRINT
            or any(
                opened.HasField(name)
                for name in ("owner_boot_id", "session_lease_id", "lease_generation")
            )
        ):
            raise ValueError("Browser source scope is invalid")
        profile = APPROVED_SESSION_PROFILE
        source_profile = hello.hello
        if (
            source_profile.maximum_data_frame_bytes != profile.data_frame_bytes
            or source_profile.request_stream_window_bytes
            != profile.request_stream_window_bytes
            or source_profile.response_stream_window_bytes
            != profile.response_stream_window_bytes
            or source_profile.request_session_window_bytes
            != profile.request_session_window_bytes
            or source_profile.response_session_window_bytes
            != profile.response_session_window_bytes
        ):
            raise ValueError("Browser source profile is incompatible")
        authority = decode_stream_authority(opened.open.authority)
        if not isinstance(authority, BrowserStreamAuthority):
            raise ValueError("Browser source requires Browser authority")
        head = opened.open.request_head
        if (
            head.protocol != pb.RUNTIME_STREAM_SESSION_PROTOCOL_WEBSOCKET
            or head.method != b"GET"
            or head.target != b"/browser"
            or head.headers
            or not now < authority.open_deadline_at <= now + timedelta(seconds=10)
            or not now < authority.transport_deadline_at <= now + timedelta(hours=1)
            or hello.hello.deadline_at.ToDatetime(tzinfo=UTC)
            != authority.transport_deadline_at
        ):
            raise ValueError("Browser source lifetime or request is invalid")
        return authority
