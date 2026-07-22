"""Slack HTTP callback orchestration tests."""

import datetime
import hashlib
import hmac
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelEventAdmission,
    ExternalChannelEventCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.http_admission import SlackHTTPAdmissionService
from azents.services.external_channel.slack_http import SlackHTTPUnauthorized

_NOW = datetime.datetime(2026, 7, 22, 1, 0, tzinfo=datetime.UTC)
_SECRET = "signing-secret"


class _RepositoryDouble:
    """Return one selected internal connection configuration."""

    def __init__(
        self,
        configuration: ExternalChannelConnectionConfiguration | None,
    ) -> None:
        self.configuration = configuration
        self.identities: list[tuple[str, str]] = []

    async def get_slack_http_configuration_by_provider_identity(
        self,
        session: AsyncSession,
        *,
        provider_app_id: str,
        provider_tenant_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        del session
        self.identities.append((provider_app_id, provider_tenant_id))
        if self.configuration is None:
            return None
        if (
            self.configuration.provider_app_id != provider_app_id
            or self.configuration.provider_tenant_id != provider_tenant_id
        ):
            return None
        return self.configuration


class _AdmissionDouble:
    """Record normalized events and optionally expose a database failure."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[ExternalChannelEventCreate] = []

    async def admit(
        self,
        create: ExternalChannelEventCreate,
    ) -> ExternalChannelEventAdmission:
        self.events.append(create)
        if self.fail:
            raise RuntimeError("database unavailable")
        return cast(
            ExternalChannelEventAdmission,
            SimpleNamespace(
                event=SimpleNamespace(id="event-row-1"),
                created=True,
            ),
        )


def _configuration(
    codec: ExternalChannelCredentialsCodec,
    *,
    status: ExternalChannelConnectionStatus,
) -> ExternalChannelConnectionConfiguration:
    return ExternalChannelConnectionConfiguration(
        id="connection-1",
        workspace_id="workspace-1",
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        status=status,
        provider_app_id="A-1",
        provider_tenant_id="T-1",
        provider_bot_user_id="B-1",
        http_callback_selector_hash=None,
        encrypted_credentials=codec.encrypt(
            SlackConnectionCredentials(
                bot_token="xoxb-secret",
                signing_secret=_SECRET,
                app_token=None,
            )
        ),
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        disconnected_at=None,
        socket_lease_owner=None,
        socket_lease_until=None,
        socket_heartbeat_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _service(
    *,
    configuration: ExternalChannelConnectionConfiguration | None,
    codec: ExternalChannelCredentialsCodec,
    admission: _AdmissionDouble,
) -> tuple[SlackHTTPAdmissionService, _RepositoryDouble]:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, object())

    repository = _RepositoryDouble(configuration)
    return (
        SlackHTTPAdmissionService(
            session_manager=cast(SessionManager[AsyncSession], session_manager),
            repository=cast(ExternalChannelRepository, repository),
            credentials_codec=codec,
            admission_service=cast(ExternalChannelAdmissionService, admission),
        ),
        repository,
    )


def _signed(body: bytes) -> tuple[str, str]:
    timestamp = str(int(_NOW.timestamp()))
    base = b"v0:" + timestamp.encode() + b":" + body
    signature = "v0=" + hmac.new(_SECRET.encode(), base, hashlib.sha256).hexdigest()
    return timestamp, signature


def _event_body(*, app_id: str = "A-1", tenant_id: str = "T-1") -> bytes:
    return json.dumps(
        {
            "type": "event_callback",
            "event_id": "Ev-1",
            "event_time": int(_NOW.timestamp()),
            "api_app_id": app_id,
            "team_id": tenant_id,
            "event": {
                "type": "app_mention",
                "channel": "C-1",
                "user": "U-1",
                "text": "Run the agent",
                "ts": "100.1",
            },
        }
    ).encode()


@pytest.fixture
def codec() -> ExternalChannelCredentialsCodec:
    """Return a real encrypted credential codec."""
    return ExternalChannelCredentialsCodec(
        CredentialCipher(Fernet.generate_key().decode())
    )


@pytest.mark.asyncio
async def test_url_verification_returns_challenge_without_admission(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Allow signed setup verification before provider identity activation."""
    admission = _AdmissionDouble()
    service, repository = _service(
        configuration=None,
        codec=codec,
        admission=admission,
    )
    body = json.dumps({"type": "url_verification", "challenge": "challenge-1"}).encode()

    result = await service.handle(
        raw_body=body,
        timestamp_header=None,
        signature_header=None,
        received_at=_NOW,
    )

    assert result.challenge == "challenge-1"
    assert admission.events == []
    assert repository.identities == []


@pytest.mark.asyncio
async def test_matching_active_event_is_admitted_before_return(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Normalize and commit an authenticated App/tenant event."""
    admission = _AdmissionDouble()
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
    )
    body = _event_body()
    timestamp, signature = _signed(body)

    result = await service.handle(
        raw_body=body,
        timestamp_header=timestamp,
        signature_header=signature,
        received_at=_NOW,
    )

    assert result.event_id == "event-row-1"
    assert result.created is True
    assert [event.provider_event_id for event in admission.events] == ["Ev-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_id", "tenant_id"),
    [("A-other", "T-1"), ("A-1", "T-other")],
)
async def test_event_identity_mismatch_is_rejected_before_admission(
    codec: ExternalChannelCredentialsCodec,
    app_id: str,
    tenant_id: str,
) -> None:
    """Fail closed when the signed callback targets another installation."""
    admission = _AdmissionDouble()
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
    )
    body = _event_body(app_id=app_id, tenant_id=tenant_id)
    timestamp, signature = _signed(body)

    with pytest.raises(SlackHTTPUnauthorized):
        await service.handle(
            raw_body=body,
            timestamp_header=timestamp,
            signature_header=signature,
            received_at=_NOW,
        )

    assert admission.events == []


@pytest.mark.asyncio
async def test_unknown_provider_identity_is_indistinguishable_from_auth_failure(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Reject unknown App and tenant identity before signature verification."""
    admission = _AdmissionDouble()
    service, _ = _service(
        configuration=None,
        codec=codec,
        admission=admission,
    )
    body = _event_body()
    timestamp, signature = _signed(body)

    with pytest.raises(SlackHTTPUnauthorized):
        await service.handle(
            raw_body=body,
            timestamp_header=timestamp,
            signature_header=signature,
            received_at=_NOW,
        )


@pytest.mark.asyncio
async def test_database_failure_propagates_without_success_acknowledgement(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Surface admission failure so Slack may redeliver the provider event."""
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=_AdmissionDouble(fail=True),
    )
    body = _event_body()
    timestamp, signature = _signed(body)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.handle(
            raw_body=body,
            timestamp_header=timestamp,
            signature_header=signature,
            received_at=_NOW,
        )
