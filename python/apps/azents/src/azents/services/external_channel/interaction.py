"""Transient, scoped Slack selector-modal interaction processing."""

import base64
import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Annotated, Literal, assert_never

from fastapi import Depends
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelInteractionType,
    ExternalChannelResponseMode,
)
from azents.core.external_account_link import VerifiedExternalAccountActor
from azents.core.external_channel_ingestion import ExternalChannelIngestionOutcomeKind
from azents.core.external_channel_interaction import (
    InteractionSelectorMetadata,
    ProcessingInteractionScope,
    SelectorScope,
    SelectorSubmissionScope,
)
from azents.core.external_channel_participation import (
    ExternalChannelParticipationError,
    ExternalChannelParticipationSettings,
)
from azents.core.external_channel_provider import SlackConnectionCredentials
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.external_channel_selection import ExternalChannelSelectorCatalog
from azents.core.external_model_settings import ExternalModelActorContext
from azents.core.scheduled_task_control import (
    ScheduledTaskEditInput,
    ScheduledTaskProviderControlError,
)
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelInteraction,
)
from azents.repos.external_channel.interaction_operations import (
    ExternalChannelInteractionOperations,
)
from azents.repos.scheduled_task.data import ScheduledTask
from azents.services.external_channel.channel_action import get_slack_delivery_client
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
    external_channel_replay_deadline,
)
from azents.services.external_channel.participation import (
    ExternalChannelParticipationService,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
    get_external_channel_provider_control_service,
)
from azents.services.external_channel.selector import ExternalChannelSelectorService
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
from azents.services.external_channel.slack_native_protocol import (
    SlackNativeControl,
    parse_native_scope,
)
from azents.services.external_channel.slack_native_settings import (
    SlackNativeSettingsService,
)
from azents.services.external_channel.slack_native_views import private_notice
from azents.services.external_channel.slack_settings import parse_slack_settings_locator
from azents.services.scheduled_task.channel import (
    ScheduledTaskChannelService,
    get_scheduled_task_channel_service,
)
from azents.services.scheduled_task.control import (
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
        "native_control",
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
    native_control: SlackNativeControl | None = field(repr=False)
    verified_actor: ExternalModelActorContext | None = field(repr=False)
    trigger_id: str | None = field(default=None, repr=False)
    selector_interaction_id: str | None = field(default=None, repr=False)
    selector_metadata: str | None = field(default=None, repr=False)
    selected_route_id: str | None = field(default=None, repr=False)
    selector_navigation: str | None = field(default=None, repr=False)
    selector_search: str | None = field(default=None, repr=False)
    selector_view_id: str | None = field(default=None, repr=False)
    selector_view_hash: str | None = field(default=None, repr=False)
    scheduled_task_locator: str | None = field(default=None, repr=False)
    scheduled_task_edit: ScheduledTaskEditInput | None = field(default=None, repr=False)


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


type _SettingsID = Annotated[str, Field(min_length=1, max_length=255)]
type _SelectorID = Annotated[str, Field(min_length=1, max_length=64)]
type _PositiveGeneration = Annotated[int, Field(gt=0)]


class _SettingsWire(BaseModel):
    """Closed compact settings scope shared by all signed target variants."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: int = Field(
        alias="v", ge=_SETTINGS_METADATA_VERSION, le=_SETTINGS_METADATA_VERSION
    )
    connection_id: _SettingsID = Field(alias="c")
    provider_parent_channel_id: _SettingsID = Field(alias="h")
    principal_id: _SettingsID = Field(alias="p")
    interaction_id: _SettingsID = Field(alias="i")


class _SetupSettingsWire(_SettingsWire):
    target: Literal["setup"] = Field(alias="k")
    setup_claim_id: _SettingsID = Field(alias="a")
    claim_generation: _PositiveGeneration = Field(alias="g")
    source_revision: _PositiveGeneration = Field(alias="s")


class _ParentSettingsWire(_SettingsWire):
    target: Literal["parent"] = Field(alias="k")
    setting_id: _SettingsID = Field(alias="e")
    settings_generation: _PositiveGeneration = Field(alias="n")


class _ThreadSettingsWire(_SettingsWire):
    target: Literal["thread"] = Field(alias="k")
    resource_id: _SettingsID = Field(alias="r")
    binding_id: _SettingsID = Field(alias="b")
    binding_response_mode: ExternalChannelResponseMode = Field(alias="m")
    binding_updated_at: AwareDatetime = Field(alias="u")


type _SettingsWirePayload = Annotated[
    _SetupSettingsWire | _ParentSettingsWire | _ThreadSettingsWire,
    Field(discriminator="target"),
]
_SETTINGS_WIRE_ADAPTER: TypeAdapter[_SettingsWirePayload] = TypeAdapter(
    _SettingsWirePayload
)


class _SelectorWire(BaseModel):
    """Closed compact signed selector scope."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: int = Field(
        alias="v", ge=_SELECTOR_METADATA_VERSION, le=_SELECTOR_METADATA_VERSION
    )
    connection_id: _SelectorID = Field(alias="c")
    resource_id: _SelectorID = Field(alias="r")
    selector_interaction_id: _SelectorID = Field(alias="a")
    interaction_id: _SelectorID = Field(alias="i")
    principal_id: _SelectorID = Field(alias="p")
    offset: int = Field(alias="o", ge=0)


@dataclass
class ExternalChannelInteractionProcessor:
    """Open or submit one selector interaction after durable scope checks."""

    operations: Annotated[
        ExternalChannelInteractionOperations,
        Depends(ExternalChannelInteractionOperations),
    ]
    selector_service: Annotated[
        ExternalChannelSelectorService, Depends(ExternalChannelSelectorService)
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec, Depends(get_external_channel_credentials_codec)
    ]
    slack_client: Annotated[SlackConversationClient, Depends(get_slack_delivery_client)]
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
    native_settings: Annotated[
        SlackNativeSettingsService, Depends(SlackNativeSettingsService)
    ]
    scheduled_task_control: Annotated[
        ScheduledTaskProviderControlService,
        Depends(ScheduledTaskProviderControlService),
    ]
    scheduled_task_channel: Annotated[
        ScheduledTaskChannelService, Depends(get_scheduled_task_channel_service)
    ]
    config: Annotated[Config, Depends(get_config)]

    async def process(self, handoff: ExternalChannelInteractionHandoff) -> None:
        """Dispatch one explicitly identified selector or settings interaction."""
        now = datetime.datetime.now(datetime.UTC)
        if handoff.handler == "native_control":
            await self._process_native_control(handoff, now=now)
            return
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
        scope = await self._load_scope(handoff, now=now)
        interaction = scope.interaction
        configuration = scope.configuration
        resource = scope.resource
        selector = scope.selector
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
            bot_token=credentials.bot_token, trigger_id=handoff.trigger_id, view=view
        )
        if result.status == "opened":
            return
        if result.status == "expired":
            raise SlackInteractionTriggerExpired
        raise RuntimeError("Slack selector modal could not be opened.")

    async def _process_selector_navigation(
        self, handoff: ExternalChannelInteractionHandoff, *, now: datetime.datetime
    ) -> None:
        """Requery one bounded catalog page and update the current modal."""
        if (
            handoff.selector_metadata is None
            or handoff.selector_view_id is None
            or handoff.selector_navigation not in {"search", "previous", "next"}
        ):
            raise ValueError("Slack selector navigation is unavailable.")
        scope = await self._load_submission_scope(handoff, now=now)
        interaction = scope.interaction
        configuration = scope.configuration
        selector = scope.selector
        metadata = scope.metadata
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
        self, handoff: ExternalChannelInteractionHandoff, *, now: datetime.datetime
    ) -> None:
        """Revalidate a signed modal submission before applying one selection."""
        scope = await self._load_submission_scope(handoff, now=now)
        interaction = scope.interaction
        configuration = scope.configuration
        selector = scope.selector
        metadata = scope.metadata
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
            claim = await self.operations.read_setup_claim(setup_claim_id)
            if claim is None:
                raise ValueError("Slack setup location interaction is unavailable.")
            settings = await self.participation_service.resolve_settings(
                connection_id=configuration.id,
                provider_parent_channel_id=claim.provider_parent_channel_id,
                provider_thread_resource_key=None,
                expected_binding_id=None,
                principal_id=interaction.principal_id,
            )
            setup_view = _settings_view(
                settings=settings,
                metadata=build_settings_metadata(
                    secret=self.config.auth.jwt.secret_key,
                    settings=settings,
                    connection_id=configuration.id,
                    provider_parent_channel_id=claim.provider_parent_channel_id,
                    principal_id=interaction.principal_id,
                    interaction_id=interaction.id,
                ),
            )
            actor = self._native_actor(
                handoff=handoff,
                scope=ProcessingInteractionScope(
                    interaction=interaction, configuration=configuration
                ),
                channel_id=claim.provider_parent_channel_id,
                thread_id=None,
            )
            setup_view = await self.native_settings.decorate(
                view=setup_view, actor=actor, settings=settings, now=now
            )
            result = await self.slack_client.open_interaction_view(
                bot_token=self._slack_credentials(configuration).bot_token,
                trigger_id=handoff.trigger_id,
                view=setup_view,
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
                            connection_id=outcome.connection_id, plan=plan
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
        self, handoff: ExternalChannelInteractionHandoff, *, now: datetime.datetime
    ) -> None:
        """Open one current setup, parent, or connected-thread settings modal."""
        if handoff.trigger_id is None:
            raise SlackInteractionTriggerExpired
        scope = await self._load_processing_interaction(handoff)
        interaction = scope.interaction
        configuration = scope.configuration
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
            if handoff.provider_thread_key is None
            or (locator is not None and locator.resource_id is None)
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
                expected_binding_id=None,
                principal_id=interaction.principal_id,
            )
            if (
                locator is not None
                and locator.resource_id is not None
                and (
                    settings.resource is None
                    or settings.binding is None
                    or settings.resource.id != locator.resource_id
                    or (settings.binding.id != locator.binding_id)
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
        except ExternalChannelParticipationError:
            settings = None
            view = private_notice(
                "Conversation settings are unavailable to you. "
                "You can still manage your account connection."
            )
        actor = self._native_actor(
            handoff=handoff,
            scope=scope,
            channel_id=provider_parent_channel_id,
            thread_id=handoff.provider_thread_key,
        )
        view = await self.native_settings.decorate(
            view=view, actor=actor, settings=settings, now=now
        )
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

    def _native_actor(
        self,
        *,
        handoff: ExternalChannelInteractionHandoff,
        scope: ProcessingInteractionScope,
        channel_id: str,
        thread_id: str | None,
    ) -> VerifiedExternalAccountActor:
        """Keep signed ingress generation rather than elevating stale callbacks."""
        actor = handoff.verified_actor
        if (
            actor is None
            or actor.connection_id != scope.configuration.id
            or actor.principal_id != scope.interaction.principal_id
            or (
                actor.configuration_generation
                != scope.configuration.configuration_generation
            )
            or (actor.provider_tenant_id != scope.configuration.provider_tenant_id)
        ):
            raise ValueError("Slack private actor is unavailable.")
        return VerifiedExternalAccountActor(
            connection_id=actor.connection_id,
            connection_configuration_generation=actor.configuration_generation,
            principal_id=actor.principal_id,
            provider=actor.provider,
            provider_tenant_id=actor.provider_tenant_id,
            provider_tenant_display_label=None,
            provider_user_id=actor.provider_user_id,
            provider_display_label=actor.provider_display_name,
            provider_interaction_id=scope.interaction.id,
            provider_channel_id=channel_id,
            provider_thread_id=thread_id,
        )

    async def _process_native_control(
        self, handoff: ExternalChannelInteractionHandoff, *, now: datetime.datetime
    ) -> None:
        """Render private native operations with no public delivery fallback."""
        control = handoff.native_control
        if control is None:
            raise ValueError("Slack private control is unavailable.")
        scope = await self._load_processing_interaction(handoff)
        try:
            native_scope = parse_native_scope(
                control.metadata, secret=self.config.auth.jwt.secret_key, now=now
            )
        except ValueError:
            view = private_notice(
                "This private control expired or is unavailable. Reopen settings."
            )
        else:
            actor = self._native_actor(
                handoff=handoff,
                scope=scope,
                channel_id=native_scope.channel_id,
                thread_id=native_scope.thread_id,
            )
            view = await self.native_settings.process(
                actor=actor, scope=native_scope, control=control, now=now
            )
        credentials = self._slack_credentials(scope.configuration)
        if (
            scope.interaction.interaction_type
            is ExternalChannelInteractionType.BLOCK_ACTION
            and control.view_id is not None
        ):
            result = await self.slack_client.update_interaction_view(
                bot_token=credentials.bot_token,
                view_id=control.view_id,
                view_hash=control.view_hash,
                view=view,
            )
            if result.status in {"updated", "conflict"}:
                return
        else:
            if handoff.trigger_id is None:
                raise SlackInteractionTriggerExpired
            result = await self.slack_client.open_interaction_view(
                bot_token=credentials.bot_token,
                trigger_id=handoff.trigger_id,
                view=view,
            )
            if result.status == "opened":
                return
        if result.status == "expired":
            raise SlackInteractionTriggerExpired
        raise RuntimeError("Slack private view could not be delivered.")

    async def _process_settings_submission(
        self, handoff: ExternalChannelInteractionHandoff, *, now: datetime.datetime
    ) -> None:
        """Revalidate signed modal scope and commit one provider setting mutation."""
        if handoff.settings_metadata is None:
            raise ValueError("Slack settings submission metadata is unavailable.")
        metadata = _parse_settings_metadata(
            metadata=handoff.settings_metadata, secret=self.config.auth.jwt.secret_key
        )
        scope = await self._load_processing_interaction(handoff)
        interaction = scope.interaction
        configuration = scope.configuration
        if (
            interaction.principal_id is None
            or interaction.principal_id != metadata.principal_id
            or configuration.id != metadata.connection_id
        ):
            raise ValueError("Slack settings submission scope is unavailable.")
        await self._validate_settings_submission_origin(
            metadata=metadata, interaction=interaction, configuration=configuration
        )
        deadline = external_channel_replay_deadline(now=now)
        try:
            if metadata.target == "setup":
                if (
                    metadata.setup_claim_id is None
                    or metadata.claim_generation is None
                    or metadata.source_revision is None
                    or (handoff.settings_location is None)
                    or (handoff.settings_response_mode is not None)
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
                    expected_binding_id=None,
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
                    or (handoff.settings_response_mode is None)
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
                    or (metadata.binding_updated_at is None)
                    or (handoff.settings_location is not None)
                    or (handoff.settings_response_mode is None)
                ):
                    raise ValueError("Slack thread settings submission is incomplete.")
                mutation = await self.participation_service.mutate_thread_settings(
                    connection_id=configuration.id,
                    provider_parent_channel_id=metadata.provider_parent_channel_id,
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
        await self.operations.validate_settings_origin(
            origin_interaction_id=metadata.interaction_id,
            interaction=interaction,
            configuration=configuration,
        )

    async def _process_scheduled_task_control(
        self, handoff: ExternalChannelInteractionHandoff, *, now: datetime.datetime
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
            locator=edit_metadata.locator
            if edit_metadata is not None
            else handoff.scheduled_task_locator,
            secret=self.config.auth.jwt.secret_key,
        )
        scope = await self._load_processing_interaction(handoff)
        interaction = scope.interaction
        configuration = scope.configuration
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
                    origin_interaction_id=None
                    if edit_metadata is None
                    else edit_metadata.origin_interaction_id,
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
        self, handoff: ExternalChannelInteractionHandoff
    ) -> ProcessingInteractionScope:
        """Reload one authenticated processing interaction and its connection."""
        return await self.operations.load_processing_interaction(
            interaction_id=handoff.interaction_id
        )

    def _slack_credentials(
        self, configuration: ExternalChannelConnectionConfiguration
    ) -> SlackConnectionCredentials:
        """Decrypt one already-authorized Slack interaction credential."""
        credentials = self.credentials_codec.decrypt(
            _required_ciphertext(configuration)
        )
        if not isinstance(credentials, SlackConnectionCredentials):
            raise RuntimeError("Slack interaction credentials are unavailable.")
        return credentials

    async def attempt_control_delivery(
        self, *, connection_id: str, plan: ProviderEffectPlan
    ) -> None:
        """Attempt one post-commit access control through the provider adapter."""
        del connection_id
        await self.provider_control.attempt(plan)

    async def _load_scope(
        self, handoff: ExternalChannelInteractionHandoff, *, now: datetime.datetime
    ) -> SelectorScope:
        """Reload trusted interaction and selector owners before provider I/O."""
        return await self.operations.load_scope(
            interaction_id=handoff.interaction_id,
            selector_interaction_id=handoff.selector_interaction_id,
            now=now,
        )

    async def _load_submission_scope(
        self, handoff: ExternalChannelInteractionHandoff, *, now: datetime.datetime
    ) -> SelectorSubmissionScope:
        """Join one transient submission to its signed selector interaction."""
        assert handoff.selector_metadata is not None
        metadata = _parse_selector_metadata(
            metadata=handoff.selector_metadata, secret=self.config.auth.jwt.secret_key
        )
        scope = await self.operations.load_submission_scope(
            interaction_id=handoff.interaction_id, metadata=metadata, now=now
        )
        assert scope.interaction.principal_id is not None
        verify_selector_metadata(
            metadata=handoff.selector_metadata,
            secret=self.config.auth.jwt.secret_key,
            connection_id=scope.configuration.id,
            resource_id=scope.resource.id,
            selector_interaction_id=scope.selector.id,
            interaction_id=metadata.interaction_id,
            principal_id=scope.interaction.principal_id,
        )
        return scope


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
            {"a": claim.id, "g": claim.claim_generation, "s": claim.source_revision}
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


def _parse_settings_metadata(*, metadata: str, secret: str) -> _SettingsMetadata:
    """Verify one settings modal envelope before reading its durable scope."""
    message = "Slack settings metadata is invalid."
    encoded = _signed_metadata_bytes(
        metadata=metadata, secret=secret, error_message=message
    )
    try:
        payload = _SETTINGS_WIRE_ADAPTER.validate_json(encoded)
    except ValidationError as error:
        raise ValueError(message) from error
    common = {
        "connection_id": payload.connection_id,
        "provider_parent_channel_id": payload.provider_parent_channel_id,
        "principal_id": payload.principal_id,
        "interaction_id": payload.interaction_id,
    }
    match payload:
        case _SetupSettingsWire():
            return _SettingsMetadata(
                target="setup",
                setup_claim_id=payload.setup_claim_id,
                claim_generation=payload.claim_generation,
                source_revision=payload.source_revision,
                setting_id=None,
                settings_generation=None,
                resource_id=None,
                binding_id=None,
                binding_response_mode=None,
                binding_updated_at=None,
                **common,
            )
        case _ParentSettingsWire():
            return _SettingsMetadata(
                target="parent",
                setup_claim_id=None,
                claim_generation=None,
                source_revision=None,
                setting_id=payload.setting_id,
                settings_generation=payload.settings_generation,
                resource_id=None,
                binding_id=None,
                binding_response_mode=None,
                binding_updated_at=None,
                **common,
            )
        case _ThreadSettingsWire():
            return _SettingsMetadata(
                target="thread",
                setup_claim_id=None,
                claim_generation=None,
                source_revision=None,
                setting_id=None,
                settings_generation=None,
                resource_id=payload.resource_id,
                binding_id=payload.binding_id,
                binding_response_mode=payload.binding_response_mode,
                binding_updated_at=payload.binding_updated_at,
                **common,
            )
        case _ as unreachable:
            assert_never(unreachable)


def _settings_view(
    *, settings: ExternalChannelParticipationSettings, metadata: str
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
                selected_value=None
                if selected_location is None
                else selected_location.value,
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
                selected_value=None if selected_mode is None else selected_mode.value,
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
            "Mentions only requires an explicit App mention or "
            "provider-native invocation."
        )
    blocks.append(
        {"type": "context", "elements": [{"type": "mrkdwn", "text": guidance}]}
    )
    return SlackInteractionView(
        callback_id=SLACK_SETUP_VIEW_CALLBACK_ID
        if settings.target == "setup"
        else SLACK_SETTINGS_VIEW_CALLBACK_ID,
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
        mode_label = _response_mode_label(settings.binding.response_mode)
        summary = f"This thread now responds to *{mode_label}*."
    else:
        assert settings.setting is not None
        mode_label = _response_mode_label(settings.setting.response_mode)
        summary = (
            f"Conversation settings were saved: *{settings.setting.location.value}*, "
            f"*{mode_label}*."
        )
    return SlackInteractionView(
        callback_id=SLACK_SETTINGS_VIEW_CALLBACK_ID,
        title="Settings saved",
        private_metadata="completed",
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": summary}}],
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
    task: ScheduledTask, locator: str
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
    *, block_id: str, label: str, initial_value: str, multiline: bool, optional: bool
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
        {"text": {"type": "plain_text", "text": option_label}, "value": option_value}
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
        else "all messages"
    )


def _slack_literal(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _slack_thread_resource_key(
    *, tenant_id: str | None, channel_id: str, thread_key: str
) -> str:
    if tenant_id is None:
        raise ValueError("Slack interaction tenant is unavailable.")
    return f"slack:{tenant_id}:{channel_id}:{thread_key}"


def _scheduled_task_slack_resource_key(
    *, tenant_id: str | None, channel_id: str | None, thread_key: str | None
) -> str | None:
    """Return a control resource key only when the callback proves its thread."""
    if channel_id is None or thread_key is None:
        return None
    return _slack_thread_resource_key(
        tenant_id=tenant_id, channel_id=channel_id, thread_key=thread_key
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
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
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
    if (
        parsed.connection_id != connection_id
        or parsed.resource_id != resource_id
        or parsed.selector_interaction_id != selector_interaction_id
        or (parsed.interaction_id != interaction_id)
        or (parsed.principal_id != principal_id)
    ):
        raise ValueError("Slack selector metadata scope is invalid.")
    return parsed.offset


def _parse_selector_metadata(
    *, metadata: str, secret: str
) -> InteractionSelectorMetadata:
    """Verify one signed metadata envelope before reading opaque identifiers."""
    message = "Slack selector metadata is invalid."
    encoded = _signed_metadata_bytes(
        metadata=metadata, secret=secret, error_message=message
    )
    try:
        payload = _SelectorWire.model_validate_json(encoded)
    except ValidationError as error:
        raise ValueError(message) from error
    return InteractionSelectorMetadata(
        connection_id=payload.connection_id,
        resource_id=payload.resource_id,
        selector_interaction_id=payload.selector_interaction_id,
        interaction_id=payload.interaction_id,
        principal_id=payload.principal_id,
        offset=payload.offset,
    )


def _signed_metadata_bytes(*, metadata: str, secret: str, error_message: str) -> bytes:
    """Authenticate the exact wire bytes before interpreting protocol fields."""
    encoded_part, separator, signature_part = metadata.partition(".")
    if not separator or not encoded_part or (not signature_part):
        raise ValueError(error_message)
    try:
        encoded = _base64url_decode(encoded_part)
        signature = _base64url_decode(signature_part)
    except ValueError as error:
        raise ValueError(error_message) from error
    expected = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError(error_message)
    return encoded


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
                "placeholder": {"type": "plain_text", "text": "Search Agents"},
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
                    "placeholder": {"type": "plain_text", "text": "Choose an Agent"},
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


def _required_ciphertext(configuration: ExternalChannelConnectionConfiguration) -> str:
    if configuration.encrypted_credentials is None:
        raise RuntimeError("Slack interaction credentials are unavailable.")
    return configuration.encrypted_credentials
