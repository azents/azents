"""Slack HTTP callback orchestration tests."""

import datetime
import hashlib
import hmac
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelInteractionAdmission,
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelTrigger,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.connection_revocation import (
    ExternalChannelConnectionRevocationService,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.http_admission import (
    SlackHTTPAdmissionService,
    SlackHTTPMessageIngressQuiesced,
    SlackHTTPRetryableIngestion,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
)
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
    ExternalChannelInteractionProcessor,
)
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
)
from azents.services.external_channel.slack_events import SlackConnectionRevocation
from azents.services.external_channel.slack_http import (
    SlackHTTPInvalidPayload,
    SlackHTTPUnauthorized,
)
from azents.services.external_channel.transport_ingestion import (
    ExternalChannelTransportIngestionService,
)

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

    def __init__(
        self,
        *,
        fail: bool = False,
        retryable: bool = False,
        awaiting_access: bool = False,
    ) -> None:
        self.fail = fail
        self.retryable = retryable
        self.awaiting_access = awaiting_access
        self.revocation_changed = True
        self.events: list[ExternalChannelTrigger] = []
        self.interactions: list[
            tuple[
                ExternalChannelInteractionCreate,
                ExternalChannelPrincipalCreate,
            ]
        ] = []
        self.claimed_interaction_ids: list[str] = []
        self.claimed = True
        self.finished: list[tuple[str, str, str | None]] = []
        self.revocations: list[SlackConnectionRevocation] = []

    async def ingest_slack_event(
        self,
        *,
        event: ExternalChannelTrigger,
        authority: object,
        deadline: object,
    ) -> ExternalChannelIngestionOutcome | SlackConnectionRevocation | None:
        del authority, deadline
        self.events.append(event)
        if self.fail:
            raise RuntimeError("database unavailable")
        if self.retryable:
            return ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                reason=ExternalChannelIngestionReason.HISTORY_UNAVAILABLE,
                batch_id=None,
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        if self.awaiting_access:
            return ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.AWAITING_ACCESS,
                reason=ExternalChannelIngestionReason.ACCESS_REQUIRED,
                batch_id=None,
                control_delivery_attempt_id="delivery-1",
                connection_id=event.connection_id,
            )
        if event.event_type == "app_uninstalled":
            return SlackConnectionRevocation(kind="app_uninstalled")
        if event.event_type == "tokens_revoked":
            return SlackConnectionRevocation(kind="tokens_revoked")
        payload = event.envelope.get("event")
        if (
            event.event_type == "message"
            and isinstance(payload, dict)
            and payload.get("subtype") in {"message_changed", "message_deleted"}
        ):
            return None
        return ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
            reason=ExternalChannelIngestionReason.ACCEPTED,
            batch_id="batch-1",
            control_delivery_attempt_id=None,
            connection_id=None,
        )

    async def apply(
        self,
        *,
        connection_id: str,
        revocation: SlackConnectionRevocation,
        required_configuration_generation: int,
        required_socket_lease_owner: str | None,
        now: datetime.datetime,
    ) -> bool:
        assert required_configuration_generation == 1
        del connection_id, required_socket_lease_owner, now
        self.revocations.append(revocation)
        return self.revocation_changed

    async def admit_interaction(
        self,
        *,
        create: ExternalChannelInteractionCreate,
        principal: ExternalChannelPrincipalCreate,
    ) -> ExternalChannelInteractionAdmission:
        self.interactions.append((create, principal))
        if self.fail:
            raise RuntimeError("database unavailable")
        return cast(
            ExternalChannelInteractionAdmission,
            SimpleNamespace(
                interaction=SimpleNamespace(id="interaction-row-1"),
                created=True,
            ),
        )

    async def begin_interaction_provider_mutation(
        self,
        *,
        interaction_id: str,
        now: datetime.datetime,
    ) -> object:
        assert now == _NOW
        self.claimed_interaction_ids.append(interaction_id)
        return SimpleNamespace(
            interaction=SimpleNamespace(id=interaction_id),
            claimed=self.claimed,
        )

    async def finish_interaction_provider_mutation(
        self,
        *,
        interaction_id: str,
        status: object,
        error_kind: str | None,
        error_summary: str | None,
    ) -> None:
        del error_summary
        self.finished.append((interaction_id, str(status), error_kind))

    async def run_interaction_provider_mutation(
        self,
        *,
        handoff: ExternalChannelInteractionHandoff,
        callback: Callable[[ExternalChannelInteractionHandoff], Awaitable[None]],
    ) -> None:
        await callback(handoff)
        self.finished.append((handoff.interaction_id, "completed", None))


def _configuration(
    codec: ExternalChannelCredentialsCodec,
    *,
    status: ExternalChannelConnectionStatus,
    app_mode: ExternalChannelAppMode = ExternalChannelAppMode.MULTI,
) -> ExternalChannelConnectionConfiguration:
    return ExternalChannelConnectionConfiguration(
        id="connection-1",
        workspace_id="workspace-1",
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        status=status,
        app_mode=app_mode,
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
    interaction_processor: ExternalChannelInteractionProcessor | None = None,
    config: Config | None = None,
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
            interaction_processor=(
                cast(ExternalChannelInteractionProcessor, AsyncMock())
                if interaction_processor is None
                else interaction_processor
            ),
            shortcut_source_service=cast(
                ExternalChannelShortcutSourceService,
                AsyncMock(),
            ),
            transport_ingestion_service=cast(
                ExternalChannelTransportIngestionService,
                admission,
            ),
            revocation_service=cast(
                ExternalChannelConnectionRevocationService,
                admission,
            ),
            config=config,
        ),
        repository,
    )


def _signed(body: bytes) -> tuple[str, str]:
    timestamp = str(int(_NOW.timestamp()))
    base = b"v0:" + timestamp.encode() + b":" + body
    signature = "v0=" + hmac.new(_SECRET.encode(), base, hashlib.sha256).hexdigest()
    return timestamp, signature


def _event_body(
    *,
    app_id: str = "A-1",
    tenant_id: str = "T-1",
    event_type: str = "app_mention",
    subtype: str | None = None,
) -> bytes:
    event: dict[str, object] = {
        "type": event_type,
        "channel": "C-1",
        "user": "U-1",
        "text": "Run the agent",
        "ts": "100.1",
    }
    if subtype is not None:
        event["subtype"] = subtype
    return json.dumps(
        {
            "type": "event_callback",
            "event_id": "Ev-1",
            "event_time": int(_NOW.timestamp()),
            "api_app_id": app_id,
            "team_id": tenant_id,
            "event": event,
        }
    ).encode()


def _interaction_body(
    *,
    interaction_type: str = "message_action",
    app_id: str = "A-1",
    tenant_id: str = "T-1",
) -> bytes:
    payload: dict[str, object] = {
        "type": interaction_type,
        "api_app_id": app_id,
        "team": {"id": tenant_id},
        "user": {"id": "U-1"},
        "callback_id": "ask-agent",
        "trigger_id": "trigger-secret-must-not-persist",
        "response_url": "https://hooks.slack.com/actions/private",
        "channel": {"id": "C-1"},
        "message": {
            "ts": "100.0001",
            "thread_ts": "100.0001",
            "text": "private source text",
        },
    }
    if interaction_type in {"block_actions", "block_suggestion"}:
        payload["actions"] = [{"action_id": "agent-selector", "value": "route-1"}]
    if interaction_type == "view_submission":
        payload["view"] = {
            "callback_id": "agent-selector",
            "private_metadata": "opaque-interaction-id",
        }
    return urlencode({"payload": json.dumps(payload)}).encode()


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

    assert result.event_id == "Ev-1"
    assert result.created is True
    assert [event.provider_event_id for event in admission.events] == ["Ev-1"]


@pytest.mark.asyncio
async def test_awaiting_access_exposes_only_committed_control_delivery_identity(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Return the durable approval-control handoff without provider payload data."""
    admission = _AdmissionDouble(awaiting_access=True)
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

    assert result.event_id == "Ev-1"
    assert result.created is False
    assert result.control_delivery_attempt_id == "delivery-1"
    assert result.control_delivery_connection_id == "connection-1"


@pytest.mark.asyncio
async def test_retryable_http_ingestion_is_not_acknowledgeable(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """A retryable synchronous failure escapes instead of becoming HTTP success."""
    admission = _AdmissionDouble(retryable=True)
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

    with pytest.raises(SlackHTTPRetryableIngestion):
        await service.handle(
            raw_body=body,
            timestamp_header=timestamp,
            signature_header=signature,
            received_at=_NOW,
        )

    assert len(admission.events) == 1


@pytest.mark.asyncio
async def test_quiesced_http_blocks_normal_message_event(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """HTTP quiesce rejects normal message ingress before legacy admission."""
    admission = _AdmissionDouble()
    config = MagicMock()
    config.external_channel_conversation.quiesce.slack_http = True
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
        config=config,
    )
    body = _event_body()
    timestamp, signature = _signed(body)

    with pytest.raises(SlackHTTPMessageIngressQuiesced):
        await service.handle(
            raw_body=body,
            timestamp_header=timestamp,
            signature_header=signature,
            received_at=_NOW,
        )

    assert admission.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["app_uninstalled", "tokens_revoked"])
async def test_quiesced_http_keeps_slack_revocation_events_available(
    codec: ExternalChannelCredentialsCodec,
    event_type: Literal["app_uninstalled", "tokens_revoked"],
) -> None:
    """Connection lifecycle revocation remains available while messages drain."""
    admission = _AdmissionDouble()
    config = MagicMock()
    config.external_channel_conversation.quiesce.slack_http = True
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
        config=config,
    )
    body = _event_body(event_type=event_type)
    timestamp, signature = _signed(body)

    result = await service.handle(
        raw_body=body,
        timestamp_header=timestamp,
        signature_header=signature,
        received_at=_NOW,
    )

    assert result.event_id == "Ev-1"
    assert len(admission.events) == 1
    assert admission.revocations == [SlackConnectionRevocation(kind=event_type)]


@pytest.mark.asyncio
async def test_stale_http_revocation_generation_is_not_acknowledged(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """A configuration replacement wins over an in-flight signed revocation."""
    admission = _AdmissionDouble()
    admission.revocation_changed = False
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
    )
    body = _event_body(event_type="tokens_revoked")
    timestamp, signature = _signed(body)

    with pytest.raises(SlackHTTPUnauthorized):
        await service.handle(
            raw_body=body,
            timestamp_header=timestamp,
            signature_header=signature,
            received_at=_NOW,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("subtype", ["message_changed", "message_deleted"])
async def test_quiesced_http_keeps_message_lifecycle_events_available(
    codec: ExternalChannelCredentialsCodec,
    subtype: str,
) -> None:
    """Message updates and deletions remain available while messages drain."""
    admission = _AdmissionDouble()
    config = MagicMock()
    config.external_channel_conversation.quiesce.slack_http = True
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
        config=config,
    )
    body = _event_body(event_type="message", subtype=subtype)
    timestamp, signature = _signed(body)

    result = await service.handle(
        raw_body=body,
        timestamp_header=timestamp,
        signature_header=signature,
        received_at=_NOW,
    )

    assert result.event_id == "Ev-1"
    assert len(admission.events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("interaction_type", "expected_type", "expected_surface", "supported"),
    [
        ("message_action", "shortcut", "unknown", True),
        ("block_actions", "block_action", "unknown", False),
        ("block_suggestion", "options", "unknown", False),
        ("view_submission", "view_submission", "modal", False),
    ],
)
async def test_matching_active_interaction_is_admitted_without_raw_payload(
    codec: ExternalChannelCredentialsCodec,
    interaction_type: str,
    expected_type: str,
    expected_surface: str,
    supported: bool,
) -> None:
    """Commit one signed form interaction before returning acknowledgement."""
    admission = _AdmissionDouble()
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
    )
    body = _interaction_body(interaction_type=interaction_type)
    timestamp, signature = _signed(body)
    shortcut_source_ensure = cast(
        AsyncMock,
        service.shortcut_source_service.ensure,
    )

    result = await service.handle(
        raw_body=body,
        timestamp_header=timestamp,
        signature_header=signature,
        received_at=_NOW,
    )

    assert result.challenge is None
    assert result.event_id is None
    assert result.interaction_id == "interaction-row-1"
    assert result.created is True
    assert admission.claimed_interaction_ids == (
        ["interaction-row-1"] if supported else []
    )
    assert (result.interaction_handoff is not None) is supported
    if result.interaction_handoff is not None:
        assert result.interaction_handoff.interaction_id == "interaction-row-1"
    assert admission.finished == (
        []
        if supported
        else [("interaction-row-1", "rejected", "interaction_unsupported")]
    )
    assert admission.events == []
    assert len(admission.interactions) == 1
    create, principal = admission.interactions[0]
    assert create.interaction_type.value == expected_type
    assert create.provider_interaction_key.startswith("http-")
    assert create.resource_correlation_key == "C-1:100.0001"
    assert create.projection == {
        "interaction_type": expected_type,
        "surface": expected_surface,
    }
    assert principal.provider_user_id == "U-1"
    persisted = repr((create, principal))
    assert "trigger-secret" not in persisted
    assert "hooks.slack.com" not in persisted
    assert "private source text" not in persisted
    assert "trigger-secret" not in repr(result)
    if interaction_type == "message_action":
        shortcut_source_ensure.assert_awaited_once()
        shortcut_source_call = shortcut_source_ensure.await_args
        assert shortcut_source_call is not None
        shortcut_source_event = shortcut_source_call.kwargs["shortcut_source_event"]
        assert shortcut_source_event is not None
        assert shortcut_source_event.provider_event_id == (
            f"shortcut-{create.provider_interaction_key}"
        )
        assert shortcut_source_event.resource_correlation_key == "C-1:100.0001"
        assert shortcut_source_event.envelope["event"] == {
            "type": "app_mention",
            "channel": "C-1",
            "user": "U-1",
            "ts": "100.0001",
            "thread_ts": "100.0001",
            "text": "private source text",
        }
    else:
        shortcut_source_ensure.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_shortcut_is_durably_rejected_without_selector_source() -> None:
    """Single Apps acknowledge shortcuts without creating Multi selector work."""
    codec = ExternalChannelCredentialsCodec(
        CredentialCipher(Fernet.generate_key().decode())
    )
    admission = _AdmissionDouble()
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
            app_mode=ExternalChannelAppMode.SINGLE,
        ),
        codec=codec,
        admission=admission,
    )
    body = _interaction_body()
    timestamp, signature = _signed(body)

    result = await service.handle(
        raw_body=body,
        timestamp_header=timestamp,
        signature_header=signature,
        received_at=_NOW,
    )

    assert result.interaction_id == "interaction-row-1"
    assert result.interaction_handoff is None
    assert admission.claimed_interaction_ids == []
    assert admission.finished == [
        ("interaction-row-1", "rejected", "interaction_unsupported")
    ]
    assert len(admission.interactions) == 1
    cast(AsyncMock, service.shortcut_source_service.ensure).assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_interaction_claim_suppresses_ephemeral_handoff(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """An already-processing interaction cannot schedule provider I/O again."""
    admission = _AdmissionDouble()
    admission.claimed = False
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
    )
    body = _interaction_body()
    timestamp, signature = _signed(body)

    result = await service.handle(
        raw_body=body,
        timestamp_header=timestamp,
        signature_header=signature,
        received_at=_NOW,
    )

    assert admission.claimed_interaction_ids == ["interaction-row-1"]
    assert result.interaction_handoff is None


@pytest.mark.asyncio
async def test_provider_processor_runs_only_after_http_admission_returns(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """The request path returns a handoff before any provider mutation runs."""
    admission = _AdmissionDouble()
    processor = AsyncMock()
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
        interaction_processor=cast(ExternalChannelInteractionProcessor, processor),
    )
    body = _interaction_body()
    timestamp, signature = _signed(body)

    result = await service.handle(
        raw_body=body,
        timestamp_header=timestamp,
        signature_header=signature,
        received_at=_NOW,
    )

    assert result.interaction_handoff is not None
    processor.process.assert_not_awaited()

    await service.run_interaction_handoff(result.interaction_handoff)

    processor.process.assert_awaited_once_with(result.interaction_handoff)
    assert admission.finished == [
        ("interaction-row-1", "completed", None),
    ]


@pytest.mark.asyncio
async def test_claim_failure_prevents_http_success_ack_result(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """A failure before the durable claim must escape rather than acknowledge."""
    admission = _AdmissionDouble()

    async def fail_claim(**_: object) -> object:
        raise RuntimeError("claim failed")

    admission.begin_interaction_provider_mutation = fail_claim
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
    )
    body = _interaction_body()
    timestamp, signature = _signed(body)

    with pytest.raises(RuntimeError, match="claim failed"):
        await service.handle(
            raw_body=body,
            timestamp_header=timestamp,
            signature_header=signature,
            received_at=_NOW,
        )


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


@pytest.mark.asyncio
async def test_invalid_signed_interaction_does_not_admit_trusted_work(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Reject a malformed form after HMAC verification without admission."""
    admission = _AdmissionDouble()
    service, _ = _service(
        configuration=_configuration(
            codec,
            status=ExternalChannelConnectionStatus.ACTIVE,
        ),
        codec=codec,
        admission=admission,
    )
    body = b"payload=not-json"
    timestamp, signature = _signed(body)

    with pytest.raises(SlackHTTPInvalidPayload):
        await service.handle(
            raw_body=body,
            timestamp_header=timestamp,
            signature_header=signature,
            received_at=_NOW,
        )

    assert admission.events == []
    assert admission.interactions == []
