"""Transient, scoped Slack selector-modal interaction processing."""

import base64
import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Annotated, assert_never

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelConversationAdmission,
    ExternalChannelInteraction,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.event_processor import (
    ExternalChannelEventProcessorService,
    get_slack_conversation_client,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcomeKind,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
    admission_uses_typed_replay,
    external_channel_replay_deadline,
)
from azents.services.external_channel.selector import (
    ExternalChannelSelectorCatalog,
    ExternalChannelSelectorService,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackInteractionView,
)

_SELECTOR_CALLBACK_ID = "azents_agent_selector"
_SELECTOR_TITLE = "Select an Agent"
_SELECTOR_PAGE_OFFSET = 0
_SELECTOR_PAGE_SIZE = 20
_SELECTOR_METADATA_VERSION = 1


class SlackInteractionTriggerExpired(RuntimeError):
    """The provider rejected an ephemeral interaction trigger as expired."""


@dataclass(frozen=True)
class ExternalChannelInteractionHandoff:
    """One committed interaction claim with an in-memory-only provider trigger."""

    interaction_id: str
    trigger_id: str | None = field(default=None, repr=False)
    selector_admission_id: str | None = field(default=None, repr=False)
    selector_metadata: str | None = field(default=None, repr=False)
    selected_route_id: str | None = field(default=None, repr=False)
    selector_navigation: str | None = field(default=None, repr=False)
    selector_search: str | None = field(default=None, repr=False)
    selector_view_id: str | None = field(default=None, repr=False)
    selector_view_hash: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class _SelectorMetadata:
    """Verified opaque modal scope retained only in Slack private metadata."""

    connection_id: str
    resource_id: str
    admission_id: str
    interaction_id: str
    principal_id: str
    offset: int


@dataclass
class ExternalChannelInteractionProcessor:
    """Open one bounded selector modal from a committed interaction claim."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    selector_service: Annotated[
        ExternalChannelSelectorService,
        Depends(ExternalChannelSelectorService),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    slack_client: Annotated[
        SlackConversationClient,
        Depends(get_slack_conversation_client),
    ]
    event_processor: Annotated[
        ExternalChannelEventProcessorService,
        Depends(ExternalChannelEventProcessorService),
    ]
    ingestion_replay_service: Annotated[
        ExternalChannelIngestionReplayService,
        Depends(ExternalChannelIngestionReplayService),
    ]
    config: Annotated[Config, Depends(get_config)]

    async def process(
        self,
        handoff: ExternalChannelInteractionHandoff,
    ) -> None:
        """Open or submit one selector interaction after durable scope checks."""
        now = datetime.datetime.now(datetime.UTC)
        if handoff.selector_navigation is not None:
            await self._process_selector_navigation(handoff, now=now)
            return
        if (
            handoff.selector_metadata is not None
            and handoff.selected_route_id is not None
        ):
            await self._process_selector_submission(handoff, now=now)
            return
        if handoff.trigger_id is None:
            raise ValueError("Slack selector interaction is unavailable.")
        interaction, configuration, resource, admission = await self._load_scope(
            handoff,
            now=now,
        )
        principal_id = interaction.principal_id
        assert principal_id is not None
        catalog = await self.selector_service.project_catalog(
            admission_id=admission.id,
            principal_id=principal_id,
            search=None,
            offset=_SELECTOR_PAGE_OFFSET,
            now=now,
        )
        credentials = self.credentials_codec.decrypt(
            _required_ciphertext(configuration)
        )
        if not isinstance(credentials, SlackConnectionCredentials):
            raise RuntimeError("Slack interaction credentials are unavailable.")
        view = _selector_view(
            catalog=catalog,
            metadata=build_selector_metadata(
                secret=self.config.auth.jwt.secret_key,
                connection_id=configuration.id,
                resource_id=resource.id,
                admission_id=admission.id,
                interaction_id=interaction.id,
                principal_id=principal_id,
                offset=_SELECTOR_PAGE_OFFSET,
            ),
            search=None,
            offset=_SELECTOR_PAGE_OFFSET,
        )
        result = await self.slack_client.open_interaction_view(
            bot_token=credentials.bot_token,
            trigger_id=handoff.trigger_id,
            view=view,
        )
        if result.status == "opened":
            return
        if result.status == "expired":
            raise SlackInteractionTriggerExpired
        raise RuntimeError("Slack selector modal could not be opened.")

    async def _process_selector_navigation(
        self,
        handoff: ExternalChannelInteractionHandoff,
        *,
        now: datetime.datetime,
    ) -> None:
        """Requery one bounded catalog page and update the current modal."""
        if (
            handoff.selector_metadata is None
            or handoff.selector_view_id is None
            or handoff.selector_navigation not in {"search", "previous", "next"}
        ):
            raise ValueError("Slack selector navigation is unavailable.")
        (
            interaction,
            configuration,
            _,
            admission,
            metadata,
        ) = await self._load_submission_scope(handoff, now=now)
        if handoff.selector_navigation == "search":
            offset = 0
        elif handoff.selector_navigation == "previous":
            offset = max(0, metadata.offset - _SELECTOR_PAGE_SIZE)
        else:
            offset = metadata.offset + _SELECTOR_PAGE_SIZE
        assert interaction.principal_id is not None
        catalog = await self.selector_service.project_catalog(
            admission_id=admission.id,
            principal_id=interaction.principal_id,
            search=handoff.selector_search,
            offset=offset,
            now=now,
        )
        credentials = self.credentials_codec.decrypt(
            _required_ciphertext(configuration)
        )
        if not isinstance(credentials, SlackConnectionCredentials):
            raise RuntimeError("Slack interaction credentials are unavailable.")
        view = _selector_view(
            catalog=catalog,
            metadata=build_selector_metadata(
                secret=self.config.auth.jwt.secret_key,
                connection_id=configuration.id,
                resource_id=metadata.resource_id,
                admission_id=admission.id,
                interaction_id=metadata.interaction_id,
                principal_id=interaction.principal_id,
                offset=offset,
            ),
            search=handoff.selector_search,
            offset=offset,
        )
        result = await self.slack_client.update_interaction_view(
            bot_token=credentials.bot_token,
            view_id=handoff.selector_view_id,
            view_hash=handoff.selector_view_hash,
            view=view,
        )
        if result.status in {"updated", "conflict"}:
            return
        raise RuntimeError("Slack selector modal could not be updated.")

    async def _process_selector_submission(
        self,
        handoff: ExternalChannelInteractionHandoff,
        *,
        now: datetime.datetime,
    ) -> None:
        """Revalidate a signed modal submission before applying one selection."""
        interaction, _, _, admission, metadata = await self._load_submission_scope(
            handoff,
            now=now,
        )
        assert interaction.principal_id is not None
        assert handoff.selected_route_id is not None
        if (
            admission.status
            is ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS
        ):
            return
        if admission.status is ExternalChannelConversationAdmissionStatus.SELECTED:
            if admission.selected_route_id != handoff.selected_route_id:
                raise ValueError("Slack selector route is immutable.")
            selected_admission = admission
        else:
            selection = await self.selector_service.select_route(
                admission_id=admission.id,
                principal_id=interaction.principal_id,
                route_id=handoff.selected_route_id,
                now=now,
            )
            if selection.status == "expired":
                raise ValueError("Slack selector admission expired.")
            if selection.status == "already_bound":
                return
            selected_admission = selection.admission
        if selected_admission.id != metadata.admission_id:
            raise ValueError("Slack selector admission is unavailable.")
        if admission_uses_typed_replay(selected_admission):
            outcome = await self.ingestion_replay_service.replay_selected_admission(
                admission_id=selected_admission.id,
                principal_id=interaction.principal_id,
                deadline=external_channel_replay_deadline(now=now),
            )
            match outcome.kind:
                case (
                    ExternalChannelIngestionOutcomeKind.ACCEPTED
                    | ExternalChannelIngestionOutcomeKind.DUPLICATE
                ):
                    return
                case ExternalChannelIngestionOutcomeKind.AWAITING_ACCESS:
                    if outcome.control_delivery_attempt_id is not None:
                        assert outcome.connection_id is not None
                        await self.attempt_control_delivery(
                            connection_id=outcome.connection_id,
                            delivery_attempt_id=outcome.control_delivery_attempt_id,
                        )
                    return
                case (
                    ExternalChannelIngestionOutcomeKind.AWAITING_SELECTION
                    | ExternalChannelIngestionOutcomeKind.IGNORED
                    | ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
                    | ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION
                ):
                    raise RuntimeError(
                        "Slack selector ingestion could not be completed."
                    )
                case _ as unreachable:
                    assert_never(unreachable)
        continuation = await self.event_processor.continue_selected_admission(
            admission_id=selected_admission.id,
            principal_id=interaction.principal_id,
            now=now,
        )
        if continuation.control_delivery_attempt_id is not None:
            await self.event_processor.attempt_selected_admission_control_delivery(
                connection_id=interaction.connection_id,
                delivery_attempt_id=continuation.control_delivery_attempt_id,
            )

    async def attempt_control_delivery(
        self,
        *,
        connection_id: str,
        delivery_attempt_id: str,
    ) -> None:
        """Attempt one committed access control through the provider adapter."""
        await self.event_processor.attempt_selected_admission_control_delivery(
            connection_id=connection_id,
            delivery_attempt_id=delivery_attempt_id,
        )

    async def _load_scope(
        self,
        handoff: ExternalChannelInteractionHandoff,
        *,
        now: datetime.datetime,
    ) -> tuple[
        ExternalChannelInteraction,
        ExternalChannelConnectionConfiguration,
        ExternalChannelResource,
        ExternalChannelConversationAdmission,
    ]:
        """Reload all trusted durable owners before any selector provider I/O."""
        async with self.session_manager() as session:
            interaction = await self.repository.lock_interaction(
                session,
                interaction_id=handoff.interaction_id,
            )
            if (
                interaction is None
                or interaction.status is not ExternalChannelInteractionStatus.PROCESSING
                or interaction.principal_id is None
                or interaction.resource_correlation_key is None
                or interaction.interaction_type
                not in {
                    ExternalChannelInteractionType.SHORTCUT,
                    ExternalChannelInteractionType.BLOCK_ACTION,
                }
            ):
                raise ValueError("Slack selector interaction is unavailable.")
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=interaction.connection_id,
            )
            if (
                configuration is None
                or configuration.status
                not in {
                    ExternalChannelConnectionStatus.ACTIVE,
                    ExternalChannelConnectionStatus.DEGRADED,
                }
                or configuration.app_mode is not ExternalChannelAppMode.MULTI
                or configuration.provider_tenant_id is None
            ):
                raise ValueError("Slack selector connection is unavailable.")
            resource = await self._resource_for_interaction(
                session,
                interaction=interaction,
                configuration=configuration,
            )
            admission = await self._admission_for_interaction(
                session,
                interaction=interaction,
                resource=resource,
                handoff=handoff,
                now=now,
            )
            return interaction, configuration, resource, admission

    async def _resource_for_interaction(
        self,
        session: AsyncSession,
        *,
        interaction: ExternalChannelInteraction,
        configuration: ExternalChannelConnectionConfiguration,
    ) -> ExternalChannelResource:
        """Resolve the canonical retained Slack conversation from correlation only."""
        assert interaction.resource_correlation_key is not None
        channel_id, separator, thread_ts = (
            interaction.resource_correlation_key.partition(":")
        )
        if not separator or not channel_id or not thread_ts:
            raise ValueError("Slack selector resource is unavailable.")
        resource = await self.repository.get_resource_by_provider_key(
            session,
            connection_id=configuration.id,
            provider_resource_key=(
                f"slack:{configuration.provider_tenant_id}:{channel_id}:{thread_ts}"
            ),
        )
        if resource is None or resource.connection_id != configuration.id:
            raise ValueError("Slack selector resource is unavailable.")
        return resource

    async def _admission_for_interaction(
        self,
        session: AsyncSession,
        *,
        interaction: ExternalChannelInteraction,
        resource: ExternalChannelResource,
        handoff: ExternalChannelInteractionHandoff,
        now: datetime.datetime,
    ) -> ExternalChannelConversationAdmission:
        """Require one still-pending admission in the exact interaction scope."""
        admission = (
            await self.repository.get_conversation_admission(
                session,
                admission_id=handoff.selector_admission_id,
            )
            if handoff.selector_admission_id is not None
            else await self.repository.get_open_conversation_admission(
                session,
                resource_id=resource.id,
            )
        )
        if (
            admission is None
            or admission.connection_id != interaction.connection_id
            or admission.resource_id != resource.id
            or admission.initiating_principal_id != interaction.principal_id
            or admission.status
            is not ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
            or admission.expires_at <= now
        ):
            raise ValueError("Slack selector admission is unavailable.")
        return admission

    async def _load_submission_scope(
        self,
        handoff: ExternalChannelInteractionHandoff,
        *,
        now: datetime.datetime,
    ) -> tuple[
        ExternalChannelInteraction,
        ExternalChannelConnectionConfiguration,
        ExternalChannelResource,
        ExternalChannelConversationAdmission,
        _SelectorMetadata,
    ]:
        """Join one transient submission to its signed, durable selector scope."""
        assert handoff.selector_metadata is not None
        metadata = _parse_selector_metadata(
            metadata=handoff.selector_metadata,
            secret=self.config.auth.jwt.secret_key,
        )
        async with self.session_manager() as session:
            interaction = await self.repository.lock_interaction(
                session,
                interaction_id=handoff.interaction_id,
            )
            if (
                interaction is None
                or interaction.status is not ExternalChannelInteractionStatus.PROCESSING
                or interaction.principal_id is None
                or interaction.interaction_type
                not in {
                    ExternalChannelInteractionType.BLOCK_ACTION,
                    ExternalChannelInteractionType.VIEW_SUBMISSION,
                }
                or interaction.connection_id != metadata.connection_id
                or interaction.principal_id != metadata.principal_id
            ):
                raise ValueError("Slack selector submission is unavailable.")
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=interaction.connection_id,
            )
            if (
                configuration is None
                or configuration.status
                not in {
                    ExternalChannelConnectionStatus.ACTIVE,
                    ExternalChannelConnectionStatus.DEGRADED,
                }
                or configuration.app_mode is not ExternalChannelAppMode.MULTI
            ):
                raise ValueError("Slack selector connection is unavailable.")
            resource = await self.repository.get_resource(
                session,
                resource_id=metadata.resource_id,
            )
            if resource is None or resource.connection_id != configuration.id:
                raise ValueError("Slack selector resource is unavailable.")
            admission = await self.repository.get_conversation_admission(
                session,
                admission_id=metadata.admission_id,
            )
            if (
                admission is None
                or admission.connection_id != configuration.id
                or admission.resource_id != resource.id
                or admission.initiating_principal_id != interaction.principal_id
                or admission.status
                not in {
                    ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
                    ExternalChannelConversationAdmissionStatus.SELECTED,
                    ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                }
                or admission.expires_at <= now
            ):
                raise ValueError("Slack selector admission is unavailable.")
            opened = await self.repository.lock_interaction(
                session,
                interaction_id=metadata.interaction_id,
            )
            if (
                opened is None
                or opened.connection_id != configuration.id
                or opened.principal_id != interaction.principal_id
                or opened.interaction_type
                not in {
                    ExternalChannelInteractionType.SHORTCUT,
                    ExternalChannelInteractionType.BLOCK_ACTION,
                }
                or opened.status
                not in {
                    ExternalChannelInteractionStatus.PROCESSING,
                    ExternalChannelInteractionStatus.COMPLETED,
                }
            ):
                raise ValueError("Slack selector modal is unavailable.")
            opened_resource = await self._resource_for_interaction(
                session,
                interaction=opened,
                configuration=configuration,
            )
            if opened_resource.id != resource.id:
                raise ValueError("Slack selector resource is unavailable.")
            verify_selector_metadata(
                metadata=handoff.selector_metadata,
                secret=self.config.auth.jwt.secret_key,
                connection_id=configuration.id,
                resource_id=resource.id,
                admission_id=admission.id,
                interaction_id=opened.id,
                principal_id=interaction.principal_id,
            )
            return interaction, configuration, resource, admission, metadata


def build_selector_metadata(
    *,
    secret: str,
    connection_id: str,
    resource_id: str,
    admission_id: str,
    interaction_id: str,
    principal_id: str,
    offset: int,
) -> str:
    """Build compact signed modal metadata from opaque durable identifiers only."""
    if offset < 0:
        raise ValueError("Selector offset must not be negative.")
    payload: dict[str, object] = {
        "v": _SELECTOR_METADATA_VERSION,
        "c": connection_id,
        "r": resource_id,
        "a": admission_id,
        "i": interaction_id,
        "p": principal_id,
        "o": offset,
    }
    encoded = _selector_metadata_payload(payload)
    signature = hmac.new(
        secret.encode(),
        encoded,
        hashlib.sha256,
    ).digest()
    return (
        base64.urlsafe_b64encode(encoded).decode().rstrip("=")
        + "."
        + base64.urlsafe_b64encode(signature).decode().rstrip("=")
    )


def verify_selector_metadata(
    *,
    metadata: str,
    secret: str,
    connection_id: str,
    resource_id: str,
    admission_id: str,
    interaction_id: str,
    principal_id: str,
) -> int:
    """Verify opaque metadata integrity and all durable scope bindings."""
    parsed = _parse_selector_metadata(metadata=metadata, secret=secret)
    expected = {
        "connection_id": connection_id,
        "resource_id": resource_id,
        "admission_id": admission_id,
        "interaction_id": interaction_id,
        "principal_id": principal_id,
    }
    if any(getattr(parsed, key) != value for key, value in expected.items()):
        raise ValueError("Slack selector metadata scope is invalid.")
    return parsed.offset


def _parse_selector_metadata(
    *,
    metadata: str,
    secret: str,
) -> _SelectorMetadata:
    """Verify one signed metadata envelope before reading opaque identifiers."""
    encoded_part, separator, signature_part = metadata.partition(".")
    if not separator or not encoded_part or not signature_part:
        raise ValueError("Slack selector metadata is invalid.")
    try:
        encoded = _base64url_decode(encoded_part)
        signature = _base64url_decode(signature_part)
        payload = json.loads(encoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Slack selector metadata is invalid.") from error
    if not isinstance(payload, dict):
        raise ValueError("Slack selector metadata is invalid.")
    expected_signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Slack selector metadata is invalid.")
    required = {
        "c": "connection_id",
        "r": "resource_id",
        "a": "admission_id",
        "i": "interaction_id",
        "p": "principal_id",
    }
    if payload.get("v") != _SELECTOR_METADATA_VERSION:
        raise ValueError("Slack selector metadata is invalid.")
    values: dict[str, str] = {}
    for payload_key, attribute in required.items():
        value = payload.get(payload_key)
        if not isinstance(value, str) or not value or len(value) > 64:
            raise ValueError("Slack selector metadata is invalid.")
        values[attribute] = value
    offset = payload.get("o")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("Slack selector metadata is invalid.")
    return _SelectorMetadata(offset=offset, **values)


def _selector_view(
    *,
    catalog: ExternalChannelSelectorCatalog,
    metadata: str,
    search: str | None,
    offset: int,
) -> SlackInteractionView:
    """Render one bounded searchable selector page with explicit navigation."""
    blocks: list[dict[str, object]] = [
        {
            "type": "input",
            "block_id": "azents_agent_selector_search",
            "optional": True,
            "dispatch_action": False,
            "label": {"type": "plain_text", "text": "Search"},
            "element": {
                "type": "plain_text_input",
                "action_id": "azents_agent_selector_search",
                "initial_value": search or "",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Search Agents",
                },
            },
        }
    ]
    if not catalog.candidates:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "No eligible Agents are available on this page.",
                },
            }
        )
    else:
        options = [
            {
                "text": {
                    "type": "plain_text",
                    "text": _candidate_label(candidate.agent_name, candidate.access),
                },
                "value": candidate.route_id,
            }
            for candidate in catalog.candidates
        ]
        blocks.append(
            {
                "type": "input",
                "block_id": "azents_agent_selector_route",
                "label": {"type": "plain_text", "text": "Agent"},
                "element": {
                    "type": "static_select",
                    "action_id": "azents_agent_selector_route",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Choose an Agent",
                    },
                    "options": options,
                },
            }
        )
    actions: list[dict[str, object]] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Search"},
            "action_id": "azents_agent_selector_search",
        }
    ]
    if offset > 0:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Previous"},
                "action_id": "azents_agent_selector_previous",
            }
        )
    if catalog.next_offset is not None:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Next"},
                "action_id": "azents_agent_selector_next",
            }
        )
    blocks.append({"type": "actions", "elements": actions})
    return SlackInteractionView(
        callback_id=_SELECTOR_CALLBACK_ID,
        title=_SELECTOR_TITLE,
        private_metadata=metadata,
        blocks=blocks,
        submit_title="Continue" if catalog.candidates else None,
        close_title="Cancel",
    )


def _candidate_label(access_name: str, access: str) -> str:
    suffix = "" if access == "available" else " — Access required"
    return (access_name + suffix)[:75]


def _selector_metadata_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _required_ciphertext(
    configuration: ExternalChannelConnectionConfiguration,
) -> str:
    if configuration.encrypted_credentials is None:
        raise RuntimeError("Slack interaction credentials are unavailable.")
    return configuration.encrypted_credentials
