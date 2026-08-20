"""Transient, scoped Slack selector-modal interaction processing."""

import base64
import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Annotated, Literal, assert_never

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelResponseMode,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelInteraction,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.scheduled_task.data import ScheduledTask
from azents.services.external_channel.channel_action import get_slack_delivery_client
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcomeKind,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
    external_channel_replay_deadline,
)
from azents.services.external_channel.participation import (
    ExternalChannelParticipationError,
    ExternalChannelParticipationService,
    ExternalChannelParticipationSettings,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
    get_external_channel_provider_control_service,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan
from azents.services.external_channel.selector import (
    ExternalChannelSelectorCatalog,
    ExternalChannelSelectorService,
)
from azents.services.external_channel.selector_state import (
    selector_state_from_interaction,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackInteractionView,
)
from azents.services.external_channel.slack_http import (
    SLACK_SCHEDULED_TASK_EDIT_VIEW_CALLBACK_ID,
    SLACK_SELECTOR_VIEW_CALLBACK_ID,
    SLACK_SETTINGS_VIEW_CALLBACK_ID,
    SLACK_SETUP_VIEW_CALLBACK_ID,
)
from azents.services.external_channel.slack_settings import (
    parse_slack_settings_locator,
)
from azents.services.scheduled_task.channel import (
    ScheduledTaskChannelService,
    get_scheduled_task_channel_service,
)
from azents.services.scheduled_task.control import (
    ScheduledTaskEditInput,
    ScheduledTaskProviderControlError,
    ScheduledTaskProviderControlService,
    build_scheduled_task_slack_edit_metadata,
    parse_scheduled_task_control_locator,
    parse_scheduled_task_slack_edit_metadata,
)

_SELECTOR_TITLE = "Select an Agent"
_SELECTOR_PAGE_OFFSET = 0
_SELECTOR_PAGE_SIZE = 20
_SELECTOR_METADATA_VERSION = 1
_SETTINGS_METADATA_VERSION = 1


class SlackInteractionTriggerExpired(RuntimeError):
    """The provider rejected an ephemeral interaction trigger as expired."""


@dataclass(frozen=True)
class ExternalChannelInteractionHandoff:
    """One committed interaction claim with an in-memory-only provider trigger."""

    interaction_id: str
    handler: Literal[
        "selector_open",
        "selector_navigation",
        "selector_submission",
        "settings_open",
        "settings_submission",
        "scheduled_task_edit_open",
        "scheduled_task_edit_submission",
        "scheduled_task_delete",
        "unsupported",
    ]
    provider_parent_channel_id: str | None = field(repr=False)
    provider_thread_key: str | None = field(repr=False)
    settings_metadata: str | None = field(repr=False)
    settings_location: ExternalChannelConversationLocation | None = field(repr=False)
    settings_response_mode: ExternalChannelResponseMode | None = field(repr=False)
    trigger_id: str | None = field(default=None, repr=False)
    selector_interaction_id: str | None = field(default=None, repr=False)
    selector_metadata: str | None = field(default=None, repr=False)
    selected_route_id: str | None = field(default=None, repr=False)
    selector_navigation: str | None = field(default=None, repr=False)
    selector_search: str | None = field(default=None, repr=False)
    selector_view_id: str | None = field(default=None, repr=False)
    selector_view_hash: str | None = field(default=None, repr=False)
    scheduled_task_locator: str | None = field(default=None, repr=False)
    scheduled_task_edit: ScheduledTaskEditInput | None = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True)
class _SelectorMetadata:
    """Verified opaque modal scope retained only in Slack private metadata."""

    connection_id: str
    resource_id: str
    selector_interaction_id: str
    interaction_id: str
    principal_id: str
    offset: int


@dataclass(frozen=True)
class _SettingsMetadata:
    """Verified settings-modal scope bound to one authenticated interaction."""

    target: Literal["setup", "parent", "thread"]
    connection_id: str
    provider_parent_channel_id: str
    principal_id: str
    interaction_id: str
    setup_claim_id: str | None
    claim_generation: int | None
    source_revision: int | None
    setting_id: str | None
    settings_generation: int | None
    resource_id: str | None
    binding_id: str | None
    binding_response_mode: ExternalChannelResponseMode | None
    binding_updated_at: datetime.datetime | None


@dataclass
class ExternalChannelInteractionProcessor:
    """Open or submit one selector interaction after durable scope checks."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
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
        Depends(get_slack_delivery_client),
    ]
    provider_control: Annotated[
        ExternalChannelProviderControlService,
        Depends(get_external_channel_provider_control_service),
    ]
    ingestion_replay_service: Annotated[
        ExternalChannelIngestionReplayService,
        Depends(ExternalChannelIngestionReplayService),
    ]
    participation_service: Annotated[
        ExternalChannelParticipationService,
        Depends(ExternalChannelParticipationService),
    ]
    scheduled_task_control: Annotated[
        ScheduledTaskProviderControlService,
        Depends(ScheduledTaskProviderControlService),
    ]
    scheduled_task_channel: Annotated[
        ScheduledTaskChannelService,
        Depends(get_scheduled_task_channel_service),
    ]
    config: Annotated[Config, Depends(get_config)]

    async def process(self, handoff: ExternalChannelInteractionHandoff) -> None:
        """Dispatch one explicitly identified selector or settings interaction."""
        now = datetime.datetime.now(datetime.UTC)
        if handoff.handler == "settings_open":
            await self._process_settings_open(handoff, now=now)
            return
        if handoff.handler == "settings_submission":
            await self._process_settings_submission(handoff, now=now)
            return
        if handoff.handler in {
            "scheduled_task_edit_open",
            "scheduled_task_edit_submission",
            "scheduled_task_delete",
        }:
            await self._process_scheduled_task_control(handoff, now=now)
            return
        if handoff.handler == "unsupported":
            raise ValueError("Slack interaction has no supported callback handler.")
        if handoff.handler not in {
            "selector_open",
            "selector_navigation",
            "selector_submission",
        }:
            raise AssertionError("Slack interaction handler is not exhaustive.")
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
        interaction, configuration, resource, selector = await self._load_scope(
            handoff,
            now=now,
        )
        principal_id = interaction.principal_id
        assert principal_id is not None
        catalog = await self.selector_service.project_catalog(
            selector_interaction_id=selector.id,
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
                selector_interaction_id=selector.id,
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
            selector,
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
            selector_interaction_id=selector.id,
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
                selector_interaction_id=selector.id,
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
        (
            interaction,
            configuration,
            _,
            selector,
            metadata,
        ) = await self._load_submission_scope(
            handoff,
            now=now,
        )
        assert interaction.principal_id is not None
        assert handoff.selected_route_id is not None
        selection = await self.selector_service.select_route(
            selector_interaction_id=selector.id,
            principal_id=interaction.principal_id,
            route_id=handoff.selected_route_id,
            now=now,
        )
        if selection.status == "expired":
            raise ValueError("Slack selector interaction expired.")
        if selection.status == "already_bound":
            return
        if selection.status == "setup_pending_location":
            setup_claim_id = selection.selector_interaction.setup_claim_id
            if setup_claim_id is None or handoff.trigger_id is None:
                raise ValueError("Slack setup location interaction is unavailable.")
            async with self.session_manager() as session:
                claim = await self.repository.get_setup_claim(
                    session,
                    claim_id=setup_claim_id,
                )
            if claim is None:
                raise ValueError("Slack setup location interaction is unavailable.")
            settings = await self.participation_service.resolve_settings(
                connection_id=configuration.id,
                provider_parent_channel_id=claim.provider_parent_channel_id,
                provider_thread_resource_key=None,
                principal_id=interaction.principal_id,
            )
            result = await self.slack_client.open_interaction_view(
                bot_token=self._slack_credentials(configuration).bot_token,
                trigger_id=handoff.trigger_id,
                view=_settings_view(
                    settings=settings,
                    metadata=build_settings_metadata(
                        secret=self.config.auth.jwt.secret_key,
                        settings=settings,
                        connection_id=configuration.id,
                        provider_parent_channel_id=(claim.provider_parent_channel_id),
                        principal_id=interaction.principal_id,
                        interaction_id=interaction.id,
                    ),
                ),
            )
            if result.status == "opened":
                return
            if result.status == "expired":
                raise SlackInteractionTriggerExpired
            raise RuntimeError("Slack setup location modal could not be opened.")
        if selection.selector_interaction.id != metadata.selector_interaction_id:
            raise ValueError("Slack selector interaction is unavailable.")
        outcome = await self.ingestion_replay_service.replay_selected_interaction(
            selector_interaction_id=selection.selector_interaction.id,
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
                if outcome.control_plans:
                    if outcome.connection_id is None:
                        raise RuntimeError(
                            "Slack selector controls require a connection identity."
                        )
                    for plan in outcome.control_plans:
                        await self.attempt_control_delivery(
                            connection_id=outcome.connection_id,
                            plan=plan,
                        )
                return
            case (
                ExternalChannelIngestionOutcomeKind.AWAITING_SELECTION
                | ExternalChannelIngestionOutcomeKind.IGNORED
                | ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
                | ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION
            ):
                raise RuntimeError("Slack selector ingestion could not be completed.")
            case _ as unreachable:
                assert_never(unreachable)

    async def _process_settings_open(
        self,
        handoff: ExternalChannelInteractionHandoff,
        *,
        now: datetime.datetime,
    ) -> None:
        """Open one current setup, parent, or connected-thread settings modal."""
        if handoff.trigger_id is None:
            raise SlackInteractionTriggerExpired
        interaction, configuration = await self._load_processing_interaction(
            handoff,
        )
        assert interaction.principal_id is not None
        provider_parent_channel_id = handoff.provider_parent_channel_id
        locator = None
        if handoff.settings_metadata is not None:
            locator = parse_slack_settings_locator(
                metadata=handoff.settings_metadata,
                secret=self.config.auth.jwt.secret_key,
            )
            if locator.connection_id != configuration.id:
                raise ValueError("Slack settings locator is unavailable.")
            provider_parent_channel_id = locator.provider_parent_channel_id
        if provider_parent_channel_id is None:
            raise ValueError("Slack conversation settings scope is unavailable.")
        provider_thread_resource_key = (
            None
            if (
                handoff.provider_thread_key is None
                or locator is not None
                and locator.resource_id is None
            )
            else _slack_thread_resource_key(
                tenant_id=configuration.provider_tenant_id,
                channel_id=provider_parent_channel_id,
                thread_key=handoff.provider_thread_key,
            )
        )
        try:
            settings = await self.participation_service.resolve_settings(
                connection_id=configuration.id,
                provider_parent_channel_id=provider_parent_channel_id,
                provider_thread_resource_key=provider_thread_resource_key,
                principal_id=interaction.principal_id,
            )
            if (
                locator is not None
                and locator.resource_id is not None
                and (
                    settings.resource is None
                    or settings.binding is None
                    or settings.resource.id != locator.resource_id
                    or settings.binding.id != locator.binding_id
                )
            ):
                raise ExternalChannelParticipationError(
                    "External Channel conversation settings changed."
                )
            view = _settings_view(
                settings=settings,
                metadata=build_settings_metadata(
                    secret=self.config.auth.jwt.secret_key,
                    settings=settings,
                    connection_id=configuration.id,
                    provider_parent_channel_id=provider_parent_channel_id,
                    principal_id=interaction.principal_id,
                    interaction_id=interaction.id,
                ),
            )
        except ExternalChannelParticipationError as error:
            view = _settings_notice_view(str(error))
        result = await self.slack_client.open_interaction_view(
            bot_token=self._slack_credentials(configuration).bot_token,
            trigger_id=handoff.trigger_id,
            view=view,
        )
        if result.status == "opened":
            return
        if result.status == "expired":
            raise SlackInteractionTriggerExpired
        raise RuntimeError("Slack conversation settings modal could not be opened.")

    async def _process_settings_submission(
        self,
        handoff: ExternalChannelInteractionHandoff,
        *,
        now: datetime.datetime,
    ) -> None:
        """Revalidate signed modal scope and commit one provider setting mutation."""
        if handoff.settings_metadata is None:
            raise ValueError("Slack settings submission metadata is unavailable.")
        metadata = _parse_settings_metadata(
            metadata=handoff.settings_metadata,
            secret=self.config.auth.jwt.secret_key,
        )
        interaction, configuration = await self._load_processing_interaction(
            handoff,
        )
        if (
            interaction.principal_id is None
            or interaction.principal_id != metadata.principal_id
            or configuration.id != metadata.connection_id
        ):
            raise ValueError("Slack settings submission scope is unavailable.")
        await self._validate_settings_submission_origin(
            metadata=metadata,
            interaction=interaction,
            configuration=configuration,
        )
        deadline = external_channel_replay_deadline(now=now)
        try:
            if metadata.target == "setup":
                if (
                    metadata.setup_claim_id is None
                    or metadata.claim_generation is None
                    or metadata.source_revision is None
                    or handoff.settings_location is None
                    or handoff.settings_response_mode is not None
                ):
                    raise ValueError("Slack setup selection is incomplete.")
                selection = await self.participation_service.select_location(
                    setup_claim_id=metadata.setup_claim_id,
                    expected_claim_generation=metadata.claim_generation,
                    expected_source_revision=metadata.source_revision,
                    location=handoff.settings_location,
                    configured_by_principal_id=interaction.principal_id,
                    now=now,
                    deadline=deadline,
                )
                settings = await self.participation_service.resolve_settings(
                    connection_id=configuration.id,
                    provider_parent_channel_id=metadata.provider_parent_channel_id,
                    provider_thread_resource_key=None,
                    principal_id=interaction.principal_id,
                )
                cleanup_plans = (
                    ()
                    if selection.replay_outcome is None
                    else selection.replay_outcome.control_plans
                )
            elif metadata.target == "parent":
                if (
                    metadata.setting_id is None
                    or metadata.settings_generation is None
                    or handoff.settings_location is None
                    or handoff.settings_response_mode is None
                ):
                    raise ValueError("Slack parent settings submission is incomplete.")
                mutation = await self.participation_service.mutate_parent_settings(
                    connection_id=configuration.id,
                    provider_parent_channel_id=metadata.provider_parent_channel_id,
                    principal_id=interaction.principal_id,
                    expected_setting_id=metadata.setting_id,
                    expected_settings_generation=metadata.settings_generation,
                    location=handoff.settings_location,
                    response_mode=handoff.settings_response_mode,
                    now=now,
                    deadline=deadline,
                )
                if mutation.settings.setting is None:
                    raise ExternalChannelParticipationError(
                        "External Channel parent settings changed."
                    )
                settings = mutation.settings
                cleanup_plans = mutation.cleanup_plans
            else:
                if (
                    metadata.resource_id is None
                    or metadata.binding_id is None
                    or metadata.binding_response_mode is None
                    or metadata.binding_updated_at is None
                    or handoff.settings_location is not None
                    or handoff.settings_response_mode is None
                ):
                    raise ValueError("Slack thread settings submission is incomplete.")
                mutation = await self.participation_service.mutate_thread_settings(
                    connection_id=configuration.id,
                    provider_parent_channel_id=(metadata.provider_parent_channel_id),
                    resource_id=metadata.resource_id,
                    binding_id=metadata.binding_id,
                    principal_id=interaction.principal_id,
                    expected_response_mode=metadata.binding_response_mode,
                    expected_binding_updated_at=metadata.binding_updated_at,
                    response_mode=handoff.settings_response_mode,
                    now=now,
                    deadline=deadline,
                )
                settings = mutation.settings
                cleanup_plans = mutation.cleanup_plans
            for plan in cleanup_plans:
                await self.provider_control.attempt(plan)
            view = _settings_confirmation_view(settings)
        except ExternalChannelParticipationError as error:
            view = _settings_notice_view(str(error))
        if handoff.trigger_id is None:
            return
        result = await self.slack_client.open_interaction_view(
            bot_token=self._slack_credentials(configuration).bot_token,
            trigger_id=handoff.trigger_id,
            view=view,
        )
        if result.status == "opened":
            return
        if result.status == "expired":
            raise SlackInteractionTriggerExpired
        raise RuntimeError("Slack settings confirmation could not be opened.")

    async def _validate_settings_submission_origin(
        self,
        *,
        metadata: _SettingsMetadata,
        interaction: ExternalChannelInteraction,
        configuration: ExternalChannelConnectionConfiguration,
    ) -> None:
        """Bind a new modal submission to its authenticated origin interaction."""
        async with self.session_manager() as session:
            origin = await self.repository.lock_interaction(
                session,
                interaction_id=metadata.interaction_id,
            )
        if (
            origin is None
            or origin.id == interaction.id
            or origin.connection_id != configuration.id
            or origin.principal_id != interaction.principal_id
            or origin.status
            not in {
                ExternalChannelInteractionStatus.PROCESSING,
                ExternalChannelInteractionStatus.COMPLETED,
            }
        ):
            raise ValueError("Slack settings submission scope is unavailable.")

    async def _process_scheduled_task_control(
        self,
        handoff: ExternalChannelInteractionHandoff,
        *,
        now: datetime.datetime,
    ) -> None:
        """Render or apply one reauthorized Scheduled Task registration control."""
        if handoff.scheduled_task_locator is None:
            raise ValueError("Slack Scheduled Task control is unavailable.")
        edit_metadata = (
            parse_scheduled_task_slack_edit_metadata(
                metadata=handoff.scheduled_task_locator,
                secret=self.config.auth.jwt.secret_key,
            )
            if handoff.handler == "scheduled_task_edit_submission"
            else None
        )
        locator = parse_scheduled_task_control_locator(
            locator=(
                edit_metadata.locator
                if edit_metadata is not None
                else handoff.scheduled_task_locator
            ),
            secret=self.config.auth.jwt.secret_key,
        )
        interaction, configuration = await self._load_processing_interaction(handoff)
        deleted_task: ScheduledTask | None = None
        try:
            if handoff.handler == "scheduled_task_edit_open":
                if locator.action != "edit":
                    raise ScheduledTaskProviderControlError(
                        "Scheduled Task control is unavailable."
                    )
                task = await self.scheduled_task_control.load_for_control(
                    interaction_id=interaction.id,
                    locator=locator,
                    provider_parent_channel_id=handoff.provider_parent_channel_id,
                    provider_thread_resource_key=_scheduled_task_slack_resource_key(
                        tenant_id=configuration.provider_tenant_id,
                        channel_id=handoff.provider_parent_channel_id,
                        thread_key=handoff.provider_thread_key,
                    ),
                )
                view = _scheduled_task_edit_view(
                    task,
                    build_scheduled_task_slack_edit_metadata(
                        secret=self.config.auth.jwt.secret_key,
                        locator=handoff.scheduled_task_locator,
                        origin_interaction_id=interaction.id,
                    ),
                )
            else:
                expected_edit = handoff.handler == "scheduled_task_edit_submission"
                if expected_edit != (locator.action == "edit"):
                    raise ScheduledTaskProviderControlError(
                        "Scheduled Task control is unavailable."
                    )
                result = await self.scheduled_task_control.mutate(
                    interaction_id=interaction.id,
                    locator=locator,
                    provider_parent_channel_id=handoff.provider_parent_channel_id,
                    provider_thread_resource_key=_scheduled_task_slack_resource_key(
                        tenant_id=configuration.provider_tenant_id,
                        channel_id=handoff.provider_parent_channel_id,
                        thread_key=handoff.provider_thread_key,
                    ),
                    origin_interaction_id=(
                        None
                        if edit_metadata is None
                        else edit_metadata.origin_interaction_id
                    ),
                    edit=handoff.scheduled_task_edit,
                    now=now,
                )
                if result.action == "delete":
                    deleted_task = result.task
                view = _scheduled_task_notice_view(
                    "Scheduled Task saved."
                    if result.action == "edit"
                    else "Scheduled Task cancelled."
                )
        except (ScheduledTaskProviderControlError, ValueError) as error:
            view = _scheduled_task_notice_view(str(error))
        if handoff.trigger_id is not None:
            result = await self.slack_client.open_interaction_view(
                bot_token=self._slack_credentials(configuration).bot_token,
                trigger_id=handoff.trigger_id,
                view=view,
            )
            if result.status == "expired":
                raise SlackInteractionTriggerExpired
            if result.status != "opened":
                raise RuntimeError(
                    "Slack Scheduled Task control could not be processed."
                )
        if deleted_task is not None:
            await self.scheduled_task_channel.execute_deletion(deleted_task)

    async def _load_processing_interaction(
        self,
        handoff: ExternalChannelInteractionHandoff,
    ) -> tuple[
        ExternalChannelInteraction,
        ExternalChannelConnectionConfiguration,
    ]:
        """Reload one authenticated processing interaction and its connection."""
        async with self.session_manager() as session:
            interaction = await self.repository.lock_interaction(
                session,
                interaction_id=handoff.interaction_id,
            )
            if (
                interaction is None
                or interaction.status is not ExternalChannelInteractionStatus.PROCESSING
                or interaction.principal_id is None
            ):
                raise ValueError("Slack interaction is unavailable.")
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=interaction.connection_id,
            )
            if configuration is None or configuration.status not in {
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            }:
                raise ValueError("Slack interaction connection is unavailable.")
            return interaction, configuration

    def _slack_credentials(
        self,
        configuration: ExternalChannelConnectionConfiguration,
    ) -> SlackConnectionCredentials:
        """Decrypt one already-authorized Slack interaction credential."""
        credentials = self.credentials_codec.decrypt(
            _required_ciphertext(configuration)
        )
        if not isinstance(credentials, SlackConnectionCredentials):
            raise RuntimeError("Slack interaction credentials are unavailable.")
        return credentials

    async def attempt_control_delivery(
        self,
        *,
        connection_id: str,
        plan: ProviderEffectPlan,
    ) -> None:
        """Attempt one post-commit access control through the provider adapter."""
        del connection_id
        await self.provider_control.attempt(plan)

    async def _load_scope(
        self,
        handoff: ExternalChannelInteractionHandoff,
        *,
        now: datetime.datetime,
    ) -> tuple[
        ExternalChannelInteraction,
        ExternalChannelConnectionConfiguration,
        ExternalChannelResource,
        ExternalChannelInteraction,
    ]:
        """Reload trusted interaction and selector owners before provider I/O."""
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
                    ExternalChannelInteractionType.SHORTCUT,
                    ExternalChannelInteractionType.BLOCK_ACTION,
                }
            ):
                raise ValueError("Slack selector interaction is unavailable.")
            selector_id = handoff.selector_interaction_id or interaction.id
            selector = await self.repository.lock_interaction(
                session,
                interaction_id=selector_id,
            )
            configuration, resource = await self._selector_owners(
                session,
                selector=selector,
                principal_id=interaction.principal_id,
                now=now,
            )
            assert selector is not None
            return interaction, configuration, resource, selector

    async def _load_submission_scope(
        self,
        handoff: ExternalChannelInteractionHandoff,
        *,
        now: datetime.datetime,
    ) -> tuple[
        ExternalChannelInteraction,
        ExternalChannelConnectionConfiguration,
        ExternalChannelResource,
        ExternalChannelInteraction,
        _SelectorMetadata,
    ]:
        """Join one transient submission to its signed selector interaction."""
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
                or interaction.principal_id != metadata.principal_id
                or interaction.interaction_type
                not in {
                    ExternalChannelInteractionType.BLOCK_ACTION,
                    ExternalChannelInteractionType.VIEW_SUBMISSION,
                }
            ):
                raise ValueError("Slack selector submission is unavailable.")
            selector = await self.repository.lock_interaction(
                session,
                interaction_id=metadata.selector_interaction_id,
            )
            configuration, resource = await self._selector_owners(
                session,
                selector=selector,
                principal_id=interaction.principal_id,
                now=now,
            )
            assert selector is not None
            opened = await self.repository.lock_interaction(
                session,
                interaction_id=metadata.interaction_id,
            )
            if (
                opened is None
                or opened.connection_id != configuration.id
                or opened.principal_id != interaction.principal_id
                or opened.status
                not in {
                    ExternalChannelInteractionStatus.PROCESSING,
                    ExternalChannelInteractionStatus.COMPLETED,
                }
            ):
                raise ValueError("Slack selector modal is unavailable.")
            verify_selector_metadata(
                metadata=handoff.selector_metadata,
                secret=self.config.auth.jwt.secret_key,
                connection_id=configuration.id,
                resource_id=resource.id,
                selector_interaction_id=selector.id,
                interaction_id=opened.id,
                principal_id=interaction.principal_id,
            )
            return interaction, configuration, resource, selector, metadata

    async def _selector_owners(
        self,
        session: AsyncSession,
        *,
        selector: ExternalChannelInteraction | None,
        principal_id: str,
        now: datetime.datetime,
    ) -> tuple[ExternalChannelConnectionConfiguration, ExternalChannelResource]:
        if (
            selector is None
            or selector.principal_id != principal_id
            or selector.expires_at <= now
            or selector.status
            in {
                ExternalChannelInteractionStatus.EXPIRED,
                ExternalChannelInteractionStatus.REJECTED,
                ExternalChannelInteractionStatus.FAILED,
            }
        ):
            raise ValueError("Slack selector interaction is unavailable.")
        state = selector_state_from_interaction(selector)
        if state.principal_id != principal_id:
            raise ValueError("Slack selector interaction is unavailable.")
        configuration = await self.repository.get_connection_configuration(
            session,
            connection_id=state.connection_id,
        )
        resource = await self.repository.get_resource(
            session,
            resource_id=state.resource_id,
        )
        if (
            configuration is None
            or configuration.status
            not in {
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            }
            or configuration.app_mode is not ExternalChannelAppMode.MULTI
            or resource is None
            or resource.connection_id != configuration.id
        ):
            raise ValueError("Slack selector interaction is unavailable.")
        return configuration, resource


def build_settings_metadata(
    *,
    secret: str,
    settings: ExternalChannelParticipationSettings,
    connection_id: str,
    provider_parent_channel_id: str,
    principal_id: str,
    interaction_id: str,
) -> str:
    """Build signed modal scope from current canonical settings generations."""
    payload: dict[str, object] = {
        "v": _SETTINGS_METADATA_VERSION,
        "k": settings.target,
        "c": connection_id,
        "h": provider_parent_channel_id,
        "p": principal_id,
        "i": interaction_id,
    }
    if settings.target == "setup":
        claim = settings.claim
        if claim is None:
            raise ValueError("Slack setup settings scope is incomplete.")
        payload.update(
            {
                "a": claim.id,
                "g": claim.claim_generation,
                "s": claim.source_revision,
            }
        )
    elif settings.target == "parent":
        setting = settings.setting
        if setting is None:
            raise ValueError("Slack parent settings scope is incomplete.")
        payload.update({"e": setting.id, "n": setting.settings_generation})
    else:
        resource = settings.resource
        binding = settings.binding
        if resource is None or binding is None:
            raise ValueError("Slack thread settings scope is incomplete.")
        payload.update(
            {
                "r": resource.id,
                "b": binding.id,
                "m": binding.response_mode.value,
                "u": binding.updated_at.isoformat(),
            }
        )
    encoded = _selector_metadata_payload(payload)
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(encoded).decode().rstrip("=")
        + "."
        + base64.urlsafe_b64encode(signature).decode().rstrip("=")
    )


def _parse_settings_metadata(
    *,
    metadata: str,
    secret: str,
) -> _SettingsMetadata:
    """Verify one settings modal envelope before reading its durable scope."""
    encoded_part, separator, signature_part = metadata.partition(".")
    if not separator or not encoded_part or not signature_part:
        raise ValueError("Slack settings metadata is invalid.")
    try:
        encoded = _base64url_decode(encoded_part)
        signature = _base64url_decode(signature_part)
        payload = json.loads(encoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Slack settings metadata is invalid.") from error
    if not isinstance(payload, dict):
        raise ValueError("Slack settings metadata is invalid.")
    expected_signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Slack settings metadata is invalid.")
    if payload.get("v") != _SETTINGS_METADATA_VERSION:
        raise ValueError("Slack settings metadata is invalid.")
    target = payload.get("k")
    if target not in {"setup", "parent", "thread"}:
        raise ValueError("Slack settings metadata is invalid.")
    common = {
        key: _settings_metadata_string(payload, field)
        for key, field in {
            "connection_id": "c",
            "provider_parent_channel_id": "h",
            "principal_id": "p",
            "interaction_id": "i",
        }.items()
    }
    if target == "setup":
        return _SettingsMetadata(
            target="setup",
            setup_claim_id=_settings_metadata_string(payload, "a"),
            claim_generation=_settings_metadata_positive_int(payload, "g"),
            source_revision=_settings_metadata_positive_int(payload, "s"),
            setting_id=None,
            settings_generation=None,
            resource_id=None,
            binding_id=None,
            binding_response_mode=None,
            binding_updated_at=None,
            **common,
        )
    if target == "parent":
        return _SettingsMetadata(
            target="parent",
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id=_settings_metadata_string(payload, "e"),
            settings_generation=_settings_metadata_positive_int(payload, "n"),
            resource_id=None,
            binding_id=None,
            binding_response_mode=None,
            binding_updated_at=None,
            **common,
        )
    mode_value = _settings_metadata_string(payload, "m")
    updated_value = _settings_metadata_string(payload, "u")
    try:
        mode = ExternalChannelResponseMode(mode_value)
        updated_at = datetime.datetime.fromisoformat(updated_value)
    except ValueError as error:
        raise ValueError("Slack settings metadata is invalid.") from error
    if updated_at.tzinfo is None:
        raise ValueError("Slack settings metadata is invalid.")
    return _SettingsMetadata(
        target="thread",
        setup_claim_id=None,
        claim_generation=None,
        source_revision=None,
        setting_id=None,
        settings_generation=None,
        resource_id=_settings_metadata_string(payload, "r"),
        binding_id=_settings_metadata_string(payload, "b"),
        binding_response_mode=mode,
        binding_updated_at=updated_at,
        **common,
    )


def _settings_metadata_string(
    payload: dict[str, object],
    key: str,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > 255:
        raise ValueError("Slack settings metadata is invalid.")
    return value


def _settings_metadata_positive_int(
    payload: dict[str, object],
    key: str,
) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Slack settings metadata is invalid.")
    return value


def _settings_view(
    *,
    settings: ExternalChannelParticipationSettings,
    metadata: str,
) -> SlackInteractionView:
    """Render one bounded canonical setup or settings modal."""
    blocks: list[dict[str, object]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Agent:* {_slack_literal(settings.agent_name)}",
            },
        }
    ]
    if settings.target in {"setup", "parent"}:
        selected_location = (
            None if settings.setting is None else settings.setting.location
        )
        blocks.append(
            _settings_select_block(
                block_id="azents_conversation_location",
                label="Conversation location",
                options=(
                    ("Channel", ExternalChannelConversationLocation.CHANNEL.value),
                    ("Threads", ExternalChannelConversationLocation.THREADS.value),
                ),
                selected_value=(
                    None if selected_location is None else selected_location.value
                ),
            )
        )
    selected_mode = (
        settings.setting.response_mode
        if settings.setting is not None
        else settings.binding.response_mode
        if settings.binding is not None
        else None
    )
    if settings.target != "setup":
        blocks.append(
            _settings_select_block(
                block_id="azents_conversation_response_mode",
                label="Response mode",
                options=(
                    ("Mentions only", ExternalChannelResponseMode.MENTION_ONLY.value),
                    ("All messages", ExternalChannelResponseMode.ALL_MESSAGES.value),
                ),
                selected_value=(None if selected_mode is None else selected_mode.value),
            )
        )
    if settings.target == "thread":
        guidance = "This change applies only to this connected thread."
    elif selected_mode is ExternalChannelResponseMode.ALL_MESSAGES:
        guidance = (
            "All messages allows the Agent to respond to every eligible message "
            "in the selected conversation location."
        )
    else:
        guidance = (
            "Mentions only requires an explicit App mention or provider-native "
            "invocation."
        )
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": guidance}],
        }
    )
    return SlackInteractionView(
        callback_id=(
            SLACK_SETUP_VIEW_CALLBACK_ID
            if settings.target == "setup"
            else SLACK_SETTINGS_VIEW_CALLBACK_ID
        ),
        title="Conversation settings",
        private_metadata=metadata,
        blocks=blocks,
        submit_title="Continue" if settings.target == "setup" else "Save",
        close_title="Cancel",
    )


def _settings_confirmation_view(
    settings: ExternalChannelParticipationSettings,
) -> SlackInteractionView:
    """Render a bounded confirmation from the committed canonical state."""
    if settings.target == "thread":
        assert settings.binding is not None
        summary = (
            "This thread now responds to "
            f"*{_response_mode_label(settings.binding.response_mode)}*."
        )
    else:
        assert settings.setting is not None
        summary = (
            "Conversation settings were saved: "
            f"*{settings.setting.location.value}*, "
            f"*{_response_mode_label(settings.setting.response_mode)}*."
        )
    return SlackInteractionView(
        callback_id=SLACK_SETTINGS_VIEW_CALLBACK_ID,
        title="Settings saved",
        private_metadata="completed",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": summary},
            }
        ],
        submit_title=None,
        close_title="Close",
    )


def _settings_notice_view(message: str) -> SlackInteractionView:
    """Render one bounded stale, unsupported, or unavailable settings result."""
    normalized = " ".join(message.split())[:500]
    return SlackInteractionView(
        callback_id=SLACK_SETTINGS_VIEW_CALLBACK_ID,
        title="Conversation settings",
        private_metadata="unavailable",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": _slack_literal(normalized or "Settings are unavailable."),
                },
            }
        ],
        submit_title=None,
        close_title="Close",
    )


def _scheduled_task_edit_view(
    task: ScheduledTask,
    locator: str,
) -> SlackInteractionView:
    """Render one provider-native edit modal from the current Task snapshot."""
    at = (
        ""
        if task.scheduled_at is None
        else task.scheduled_at.astimezone(datetime.UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return SlackInteractionView(
        callback_id=SLACK_SCHEDULED_TASK_EDIT_VIEW_CALLBACK_ID,
        title="Edit Scheduled Task",
        private_metadata=locator,
        blocks=[
            _scheduled_task_text_input(
                block_id="azents_scheduled_task_title",
                label="Title",
                initial_value=task.title,
                multiline=False,
                optional=False,
            ),
            _scheduled_task_text_input(
                block_id="azents_scheduled_task_objective",
                label="Objective",
                initial_value=task.objective,
                multiline=True,
                optional=False,
            ),
            _scheduled_task_text_input(
                block_id="azents_scheduled_task_at",
                label="Run once at (RFC3339 UTC)",
                initial_value=at,
                multiline=False,
                optional=True,
            ),
            _scheduled_task_text_input(
                block_id="azents_scheduled_task_cron",
                label="Cron expression",
                initial_value=task.cron_expression or "",
                multiline=False,
                optional=True,
            ),
            _scheduled_task_text_input(
                block_id="azents_scheduled_task_timezone",
                label="Cron timezone",
                initial_value=task.timezone or "",
                multiline=False,
                optional=True,
            ),
        ],
        submit_title="Save",
        close_title="Cancel",
    )


def _scheduled_task_text_input(
    *,
    block_id: str,
    label: str,
    initial_value: str,
    multiline: bool,
    optional: bool,
) -> dict[str, object]:
    return {
        "type": "input",
        "block_id": block_id,
        "label": {"type": "plain_text", "text": label},
        "optional": optional,
        "element": {
            "type": "plain_text_input",
            "action_id": block_id,
            "initial_value": initial_value,
            "multiline": multiline,
        },
    }


def _scheduled_task_notice_view(message: str) -> SlackInteractionView:
    """Render one provider-native Scheduled Task acknowledgement."""
    normalized = " ".join(message.split())[:500]
    return SlackInteractionView(
        callback_id=SLACK_SCHEDULED_TASK_EDIT_VIEW_CALLBACK_ID,
        title="Scheduled Task",
        private_metadata="completed",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": _slack_literal(
                        normalized or "Scheduled Task control is unavailable."
                    ),
                },
            }
        ],
        submit_title=None,
        close_title="Close",
    )


def _settings_select_block(
    *,
    block_id: str,
    label: str,
    options: tuple[tuple[str, str], ...],
    selected_value: str | None,
) -> dict[str, object]:
    rendered_options = [
        {
            "text": {"type": "plain_text", "text": option_label},
            "value": option_value,
        }
        for option_label, option_value in options
    ]
    element: dict[str, object] = {
        "type": "static_select",
        "action_id": block_id,
        "options": rendered_options,
    }
    if selected_value is not None:
        initial = next(
            (
                option
                for option in rendered_options
                if option["value"] == selected_value
            ),
            None,
        )
        if initial is not None:
            element["initial_option"] = initial
    return {
        "type": "input",
        "block_id": block_id,
        "label": {"type": "plain_text", "text": label},
        "element": element,
    }


def _response_mode_label(mode: ExternalChannelResponseMode) -> str:
    return (
        "mentions only"
        if mode is ExternalChannelResponseMode.MENTION_ONLY
        else ("all messages")
    )


def _slack_literal(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _slack_thread_resource_key(
    *,
    tenant_id: str | None,
    channel_id: str,
    thread_key: str,
) -> str:
    if tenant_id is None:
        raise ValueError("Slack interaction tenant is unavailable.")
    return f"slack:{tenant_id}:{channel_id}:{thread_key}"


def _scheduled_task_slack_resource_key(
    *,
    tenant_id: str | None,
    channel_id: str | None,
    thread_key: str | None,
) -> str | None:
    """Return a control resource key only when the callback proves its thread."""
    if channel_id is None or thread_key is None:
        return None
    return _slack_thread_resource_key(
        tenant_id=tenant_id,
        channel_id=channel_id,
        thread_key=thread_key,
    )


def build_selector_metadata(
    *,
    secret: str,
    connection_id: str,
    resource_id: str,
    selector_interaction_id: str,
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
        "a": selector_interaction_id,
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
    selector_interaction_id: str,
    interaction_id: str,
    principal_id: str,
) -> int:
    """Verify opaque metadata integrity and all durable scope bindings."""
    parsed = _parse_selector_metadata(metadata=metadata, secret=secret)
    expected = {
        "connection_id": connection_id,
        "resource_id": resource_id,
        "selector_interaction_id": selector_interaction_id,
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
        "a": "selector_interaction_id",
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
        callback_id=SLACK_SELECTOR_VIEW_CALLBACK_ID,
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
