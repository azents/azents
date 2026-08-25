"""Discord signed HTTP interaction admission boundary."""

import datetime
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated

from azcommon import di
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelInteractionAdmission,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.scheduled_task.data import ScheduledTask
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.discord_api import DiscordGuildCommandRole
from azents.services.external_channel.discord_interaction import (
    DiscordInteractionEnvelope,
    DiscordInteractionInvalidPayload,
    DiscordInteractionUnauthorized,
    discord_interaction_admission_inputs,
    discord_interaction_token,
    discord_message_command_source_event,
    parse_discord_interaction,
    validate_discord_command_capability,
    verify_discord_interaction_signature,
)
from azents.services.external_channel.discord_sdk import (
    DiscordInteractionResponseClient,
    get_discord_interaction_response_client,
)
from azents.services.external_channel.discord_selector import (
    DiscordSelectorResponseService,
)
from azents.services.external_channel.discord_settings import (
    DiscordSettingsContext,
    DiscordSettingsResponse,
    DiscordSettingsResponseService,
)
from azents.services.external_channel.discord_settings_scope import (
    DiscordSettingsScope,
    parse_discord_settings_custom_id,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
)
from azents.services.scheduled_task.channel import (
    ScheduledTaskChannelService,
    get_scheduled_task_channel_service,
)
from azents.services.scheduled_task.control import (
    ScheduledTaskProviderControlError,
    ScheduledTaskProviderControlService,
    build_scheduled_task_control_locator,
    parse_scheduled_task_control_locator,
)


@dataclass(frozen=True)
class DiscordSettingsComponentHandoff:
    """One admitted setup component completed after Discord acknowledgement."""

    interaction_id: str
    application_id: str
    interaction_token: str = field(repr=False)
    scope: DiscordSettingsScope = field(repr=False)
    context: DiscordSettingsContext = field(repr=False)
    received_at: datetime.datetime


@dataclass(frozen=True)
class DiscordHTTPAdmissionResult:
    """Verified Discord interaction result before provider acknowledgement."""

    envelope: DiscordInteractionEnvelope
    admission: ExternalChannelInteractionAdmission | None
    response: dict[str, object] | None = None
    control_plans: tuple[ProviderEffectPlan, ...] = ()
    control_delivery_connection_id: str | None = None
    settings_component_handoff: DiscordSettingsComponentHandoff | None = field(
        default=None,
        repr=False,
    )

    @property
    def ping(self) -> bool:
        """Return whether the interaction is Discord's endpoint verification PING."""
        return self.envelope.interaction_type == 1


@dataclass(frozen=True)
class DiscordAuthenticatedInteraction:
    """One authenticated and durably admitted Discord interaction."""

    configuration: ExternalChannelConnectionConfiguration
    envelope: DiscordInteractionEnvelope
    admission: ExternalChannelInteractionAdmission | None
    command_role: DiscordGuildCommandRole | None
    interaction_token: str | None = field(repr=False)


@dataclass
class DiscordHTTPAdmissionService:
    """Select, authenticate, and exactly dispatch a Discord interaction."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    admission_service: Annotated[
        ExternalChannelAdmissionService,
        Depends(ExternalChannelAdmissionService),
    ]
    shortcut_source_service: Annotated[
        ExternalChannelShortcutSourceService,
        Depends(ExternalChannelShortcutSourceService),
    ]
    selector_response_service: Annotated[
        DiscordSelectorResponseService,
        Depends(DiscordSelectorResponseService),
    ]
    settings_response_service: Annotated[
        DiscordSettingsResponseService,
        Depends(DiscordSettingsResponseService),
    ]
    scheduled_task_control: Annotated[
        ScheduledTaskProviderControlService,
        Depends(ScheduledTaskProviderControlService),
    ]
    scheduled_task_channel: Annotated[
        ScheduledTaskChannelService,
        Depends(get_scheduled_task_channel_service),
    ]
    interaction_response_client: Annotated[
        DiscordInteractionResponseClient,
        Depends(get_discord_interaction_response_client),
    ]

    async def handle(
        self,
        *,
        selector: str,
        raw_body: bytes,
        timestamp: str | None,
        signature: str | None,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        """Verify and dispatch one selector-scoped Discord interaction."""
        authenticated = await _authenticate_discord_interaction(
            selector=selector,
            raw_body=raw_body,
            timestamp=timestamp,
            signature=signature,
            received_at=received_at,
            session_manager=self.session_manager,
            repository=self.repository,
            admission_service=self.admission_service,
        )
        if authenticated.admission is None:
            return DiscordHTTPAdmissionResult(
                envelope=authenticated.envelope,
                admission=None,
            )
        return await self.dispatch_authenticated(
            authenticated=authenticated,
            received_at=received_at,
        )

    async def dispatch_authenticated(
        self,
        *,
        authenticated: DiscordAuthenticatedInteraction,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        """Dispatch one interaction after authentication and durable admission."""
        configuration = authenticated.configuration
        envelope = authenticated.envelope
        admission = authenticated.admission
        command_role = authenticated.command_role
        if admission is None:
            raise AssertionError("Discord authenticated dispatch requires admission.")
        principal_id = admission.interaction.principal_id
        if not isinstance(principal_id, str) or not principal_id:
            raise RuntimeError("Discord interaction principal is unavailable.")
        context = _settings_context(
            envelope=envelope,
            connection_id=configuration.id,
            principal_id=principal_id,
        )
        if envelope.component_custom_id is not None:
            return await self._component_result(
                envelope=envelope,
                admission=admission,
                context=context,
                received_at=received_at,
            )
        if envelope.modal_custom_id is not None:
            return await self._modal_result(
                envelope=envelope,
                admission=admission,
                context=context,
                received_at=received_at,
            )
        if envelope.interaction_type == 4:
            return await self._autocomplete_result(
                envelope=envelope,
                admission=admission,
                command_role=command_role,
                received_at=received_at,
            )
        if command_role is DiscordGuildCommandRole.MESSAGE_ACTION:
            return await self._message_action_result(
                envelope=envelope,
                admission=admission,
                configuration_id=configuration.id,
                app_mode=configuration.app_mode,
                received_at=received_at,
            )
        if command_role in {
            DiscordGuildCommandRole.AZENTS_SETTINGS,
            DiscordGuildCommandRole.CONVERSATION_SETTINGS,
        }:
            return await self._settings_open_result(
                envelope=envelope,
                admission=admission,
                context=context,
                received_at=received_at,
            )
        raise DiscordInteractionInvalidPayload("Discord interaction has no handler.")

    async def _component_result(
        self,
        *,
        envelope: DiscordInteractionEnvelope,
        admission: ExternalChannelInteractionAdmission,
        context: DiscordSettingsContext,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        custom_id = envelope.component_custom_id
        if custom_id is None:
            raise AssertionError("Discord component dispatch is incomplete.")
        if custom_id.startswith("azents-selector:"):
            return await self._selector_component_result(
                envelope=envelope,
                admission=admission,
                received_at=received_at,
            )
        if custom_id.startswith("st1:"):
            return await self._scheduled_task_component_result(
                envelope=envelope,
                admission=admission,
                context=context,
                received_at=received_at,
            )
        if not custom_id.startswith("a:"):
            return await self._unsupported_result(
                envelope=envelope,
                admission=admission,
                response={
                    "type": 7,
                    "data": {
                        "content": "This control is unavailable.",
                        "components": [],
                    },
                },
            )
        claim = await self.admission_service.begin_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            now=received_at,
        )
        if claim is None or not claim.claimed:
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=admission)
        try:
            scope = parse_discord_settings_custom_id(
                custom_id=custom_id,
                secret=self.settings_response_service.config.auth.jwt.secret_key,
            )
        except ValueError:
            await self.admission_service.finish_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                status=ExternalChannelInteractionStatus.REJECTED,
                error_kind="settings_scope_invalid",
                error_summary="Discord settings scope is invalid.",
            )
            return DiscordHTTPAdmissionResult(
                envelope=envelope,
                admission=admission,
                response={
                    "type": 7,
                    "data": {
                        "content": "This settings control is unavailable.",
                        "components": [],
                    },
                },
            )
        response = await self._complete_settings_component(
            interaction_id=admission.interaction.id,
            scope=scope,
            context=context,
            received_at=received_at,
        )
        return DiscordHTTPAdmissionResult(
            envelope=envelope,
            admission=admission,
            response=response.response,
            control_plans=response.cleanup_plans,
            control_delivery_connection_id=(
                context.connection_id if response.cleanup_plans else None
            ),
        )

    async def run_settings_component_handoff(
        self,
        handoff: DiscordSettingsComponentHandoff,
    ) -> None:
        """Complete one setup mutation after its deferred provider response."""
        response = await self._complete_settings_component(
            interaction_id=handoff.interaction_id,
            scope=handoff.scope,
            context=handoff.context,
            received_at=handoff.received_at,
        )
        try:
            await self.interaction_response_client.edit_original(
                application_id=handoff.application_id,
                interaction_token=handoff.interaction_token,
                response=response.response,
            )
        finally:
            for plan in response.cleanup_plans:
                await self.attempt_control_delivery(
                    connection_id=handoff.context.connection_id,
                    plan=plan,
                )

    async def _complete_settings_component(
        self,
        *,
        interaction_id: str,
        scope: DiscordSettingsScope,
        context: DiscordSettingsContext,
        received_at: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Run one claimed settings mutation and terminalize its admission."""
        try:
            response = await self.settings_response_service.component_response(
                interaction_id=interaction_id,
                scope=scope,
                context=context,
                now=received_at,
            )
        except Exception:
            await self.admission_service.finish_interaction_provider_mutation(
                interaction_id=interaction_id,
                status=ExternalChannelInteractionStatus.FAILED,
                error_kind="settings_component_failed",
                error_summary="Discord settings component could not be processed.",
            )
            raise
        await self.admission_service.finish_interaction_provider_mutation(
            interaction_id=interaction_id,
            status=ExternalChannelInteractionStatus.COMPLETED,
            error_kind=None,
            error_summary=None,
        )
        return response

    async def _selector_component_result(
        self,
        *,
        envelope: DiscordInteractionEnvelope,
        admission: ExternalChannelInteractionAdmission,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        claim = await self.admission_service.begin_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            now=received_at,
        )
        principal_id = admission.interaction.principal_id
        if (
            claim is None
            or not claim.claimed
            or not isinstance(principal_id, str)
            or not principal_id
        ):
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=admission)
        try:
            component_response = (
                await self.selector_response_service.component_response(
                    custom_id=envelope.component_custom_id or "",
                    selected_route_id=envelope.selected_value,
                    principal_id=principal_id,
                    guild_id=envelope.guild_id,
                    channel_id=envelope.channel_id,
                    now=received_at,
                )
            )
        except Exception:
            await self.admission_service.finish_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                status=ExternalChannelInteractionStatus.FAILED,
                error_kind="selector_component_failed",
                error_summary="Discord selector component could not be processed.",
            )
            raise
        await self.admission_service.finish_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            status=ExternalChannelInteractionStatus.COMPLETED,
            error_kind=None,
            error_summary=None,
        )
        return DiscordHTTPAdmissionResult(
            envelope=envelope,
            admission=admission,
            response=component_response.response,
            control_plans=(
                ()
                if component_response.control_plan is None
                else (component_response.control_plan,)
            ),
            control_delivery_connection_id=component_response.connection_id,
        )

    async def _scheduled_task_component_result(
        self,
        *,
        envelope: DiscordInteractionEnvelope,
        admission: ExternalChannelInteractionAdmission,
        context: DiscordSettingsContext,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        """Render or apply one idempotently claimed Scheduled Task component."""
        response: dict[str, object]
        deletion_plan: ProviderEffectPlan | None = None
        claim = await self.admission_service.begin_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            now=received_at,
        )
        if claim is None or not claim.claimed:
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=admission)
        try:
            locator = parse_scheduled_task_control_locator(
                locator=envelope.component_custom_id or "",
                secret=self.scheduled_task_control.config.auth.jwt.secret_key,
            )
            if locator.action == "delete":
                task = await self.scheduled_task_control.load_for_control(
                    interaction_id=admission.interaction.id,
                    locator=locator,
                    provider_parent_channel_id=context.provider_parent_channel_id,
                    provider_thread_resource_key=context.provider_thread_resource_key,
                )
                response = _scheduled_task_cancel_confirmation_response(
                    task=task,
                    confirm_locator=build_scheduled_task_control_locator(
                        secret=self.scheduled_task_control.config.auth.jwt.secret_key,
                        action="confirm_delete",
                        task_id=locator.task_id,
                        binding_id=locator.binding_id,
                    ),
                )
            elif locator.action == "confirm_delete":
                result = await self.scheduled_task_control.mutate(
                    interaction_id=admission.interaction.id,
                    locator=locator,
                    provider_parent_channel_id=context.provider_parent_channel_id,
                    provider_thread_resource_key=context.provider_thread_resource_key,
                    origin_interaction_id=None,
                    edit=None,
                    now=received_at,
                )
                deletion_plan = await self.scheduled_task_channel.prepare_deletion(
                    result.task
                )
                response = {
                    "type": 7,
                    "data": {
                        "content": "Scheduled Task cancelled.",
                        "components": [],
                    },
                }
            else:
                raise ScheduledTaskProviderControlError(
                    "Scheduled Task control is unavailable."
                )
        except ScheduledTaskProviderControlError, ValueError:
            response = _scheduled_task_unavailable_component_response()
        except Exception:
            await self.admission_service.finish_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                status=ExternalChannelInteractionStatus.FAILED,
                error_kind="scheduled_task_component_failed",
                error_summary=(
                    "Discord Scheduled Task component could not be processed."
                ),
            )
            raise
        await self.admission_service.finish_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            status=ExternalChannelInteractionStatus.COMPLETED,
            error_kind=None,
            error_summary=None,
        )
        return DiscordHTTPAdmissionResult(
            envelope=envelope,
            admission=admission,
            response=response,
            control_plans=(() if deletion_plan is None else (deletion_plan,)),
            control_delivery_connection_id=(
                None if deletion_plan is None else context.connection_id
            ),
        )

    async def _modal_result(
        self,
        *,
        envelope: DiscordInteractionEnvelope,
        admission: ExternalChannelInteractionAdmission,
        context: DiscordSettingsContext,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        custom_id = envelope.modal_custom_id
        if custom_id is None or not custom_id.startswith("a:"):
            return await self._unsupported_result(
                envelope=envelope,
                admission=admission,
                response={"type": 5},
            )
        return await self._component_result(
            envelope=DiscordInteractionEnvelope(
                interaction_id=envelope.interaction_id,
                interaction_type=3,
                application_id=envelope.application_id,
                guild_id=envelope.guild_id,
                channel_id=envelope.channel_id,
                provider_parent_channel_id=envelope.provider_parent_channel_id,
                provider_thread_id=envelope.provider_thread_id,
                actor_user_id=envelope.actor_user_id,
                command=None,
                message_command_source=None,
                component_custom_id=custom_id,
                selected_value=None,
                modal_custom_id=None,
                scheduled_task_edit=None,
            ),
            admission=admission,
            context=context,
            received_at=received_at,
        )

    async def _autocomplete_result(
        self,
        *,
        envelope: DiscordInteractionEnvelope,
        admission: ExternalChannelInteractionAdmission,
        command_role: DiscordGuildCommandRole | None,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        if command_role is not DiscordGuildCommandRole.AZENTS_SETTINGS:
            raise DiscordInteractionInvalidPayload(
                "Discord autocomplete is not supported."
            )
        claim = await self.admission_service.begin_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            now=received_at,
        )
        if claim is None or not claim.claimed:
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=admission)
        await self.admission_service.finish_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            status=ExternalChannelInteractionStatus.COMPLETED,
            error_kind=None,
            error_summary=None,
        )
        return DiscordHTTPAdmissionResult(
            envelope=envelope,
            admission=admission,
            response={"type": 8, "data": {"choices": []}},
        )

    async def _message_action_result(
        self,
        *,
        envelope: DiscordInteractionEnvelope,
        admission: ExternalChannelInteractionAdmission,
        configuration_id: str,
        app_mode: ExternalChannelAppMode,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        source_event = discord_message_command_source_event(
            connection_id=configuration_id,
            envelope=envelope,
            command_role=DiscordGuildCommandRole.MESSAGE_ACTION,
            received_at=received_at,
        )
        if source_event is None:
            raise DiscordInteractionInvalidPayload(
                "Discord Message Command source is unavailable."
            )
        if app_mode is not ExternalChannelAppMode.MULTI:
            return await self._unsupported_result(
                envelope=envelope,
                admission=admission,
                response=None,
            )
        materialization = await self.shortcut_source_service.ensure(
            shortcut_source_event=source_event,
            interaction_id=admission.interaction.id,
            now=received_at,
        )
        claim = await self.admission_service.begin_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            now=received_at,
        )
        if claim is None or not claim.claimed:
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=admission)
        principal_id = admission.interaction.principal_id
        if not isinstance(principal_id, str) or not principal_id:
            raise RuntimeError("Discord selector principal is unavailable.")
        try:
            if materialization.selector_interaction is None:
                response = _already_linked_response()
            else:
                response = await self.selector_response_service.initial_response(
                    selector_interaction_id=materialization.selector_interaction.id,
                    principal_id=principal_id,
                    now=received_at,
                )
        except Exception:
            await self.admission_service.finish_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                status=ExternalChannelInteractionStatus.FAILED,
                error_kind="selector_response_failed",
                error_summary="Discord selector response could not be created.",
            )
            raise
        await self.admission_service.finish_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            status=ExternalChannelInteractionStatus.COMPLETED,
            error_kind=None,
            error_summary=None,
        )
        return DiscordHTTPAdmissionResult(
            envelope=envelope,
            admission=admission,
            response=response,
        )

    async def _settings_open_result(
        self,
        *,
        envelope: DiscordInteractionEnvelope,
        admission: ExternalChannelInteractionAdmission,
        context: DiscordSettingsContext,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        claim = await self.admission_service.begin_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            now=received_at,
        )
        if claim is None or not claim.claimed:
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=admission)
        try:
            response = await self.settings_response_service.initial_response(
                origin_interaction_id=admission.interaction.id,
                context=context,
            )
        except Exception:
            await self.admission_service.finish_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                status=ExternalChannelInteractionStatus.FAILED,
                error_kind="settings_response_failed",
                error_summary="Discord settings response could not be created.",
            )
            raise
        await self.admission_service.finish_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            status=ExternalChannelInteractionStatus.COMPLETED,
            error_kind=None,
            error_summary=None,
        )
        return DiscordHTTPAdmissionResult(
            envelope=envelope,
            admission=admission,
            response=response.response,
        )

    async def _unsupported_result(
        self,
        *,
        envelope: DiscordInteractionEnvelope,
        admission: ExternalChannelInteractionAdmission,
        response: dict[str, object] | None,
    ) -> DiscordHTTPAdmissionResult:
        """Terminalize one authenticated callback with no supported processor."""
        await self.admission_service.finish_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            status=ExternalChannelInteractionStatus.REJECTED,
            error_kind="interaction_unsupported",
            error_summary="Discord interaction is not supported.",
        )
        return DiscordHTTPAdmissionResult(
            envelope=envelope,
            admission=admission,
            response=response,
        )

    async def attempt_control_delivery(
        self,
        *,
        connection_id: str,
        plan: ProviderEffectPlan,
    ) -> None:
        """Attempt one control only after the provider acknowledgement."""
        if plan.target.request_payload.get("control_kind") == (
            "scheduled_task_deletion"
        ):
            await self.scheduled_task_channel.execute_deletion_plan(plan)
            return
        await self.selector_response_service.attempt_control_delivery(
            connection_id=connection_id,
            plan=plan,
        )


@dataclass(frozen=True)
class DiscordHTTPDispatcherResolver:
    """Resolve the heavy interaction dispatcher after callback classification."""

    container: Annotated[di.Container, Depends(di.get_container)]

    @asynccontextmanager
    async def open(self) -> AsyncIterator[DiscordHTTPAdmissionService]:
        """Open one isolated dispatcher dependency graph."""
        async with self.container.copy() as container:
            yield await container.solve(DiscordHTTPAdmissionService)


@dataclass
class DiscordHTTPIngressService:
    """Acknowledge setup controls before resolving the heavy replay graph."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    admission_service: Annotated[
        ExternalChannelAdmissionService,
        Depends(ExternalChannelAdmissionService),
    ]
    config: Annotated[Config, Depends(get_config)]
    dispatcher_resolver: Annotated[
        DiscordHTTPDispatcherResolver,
        Depends(DiscordHTTPDispatcherResolver),
    ]

    async def handle(
        self,
        *,
        selector: str,
        raw_body: bytes,
        timestamp: str | None,
        signature: str | None,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        """Authenticate once and defer only slow setup component processing."""
        authenticated = await _authenticate_discord_interaction(
            selector=selector,
            raw_body=raw_body,
            timestamp=timestamp,
            signature=signature,
            received_at=received_at,
            session_manager=self.session_manager,
            repository=self.repository,
            admission_service=self.admission_service,
        )
        envelope = authenticated.envelope
        admission = authenticated.admission
        if admission is None:
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=None)
        custom_id = envelope.component_custom_id
        scope = (
            None
            if custom_id is None or not custom_id.startswith("a:")
            else _optional_discord_settings_scope(
                custom_id=custom_id,
                secret=self.config.auth.jwt.secret_key,
            )
        )
        if scope is not None and scope.action in {"setup_channel", "setup_threads"}:
            principal_id = admission.interaction.principal_id
            if not isinstance(principal_id, str) or not principal_id:
                raise RuntimeError("Discord interaction principal is unavailable.")
            if authenticated.interaction_token is None:
                raise DiscordInteractionInvalidPayload(
                    "Discord setup interaction token is unavailable."
                )
            context = _settings_context(
                envelope=envelope,
                connection_id=authenticated.configuration.id,
                principal_id=principal_id,
            )
            claim = await self.admission_service.begin_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                now=received_at,
            )
            if claim is None or not claim.claimed:
                return DiscordHTTPAdmissionResult(
                    envelope=envelope,
                    admission=admission,
                )
            return DiscordHTTPAdmissionResult(
                envelope=envelope,
                admission=admission,
                response={"type": 6},
                settings_component_handoff=DiscordSettingsComponentHandoff(
                    interaction_id=admission.interaction.id,
                    application_id=envelope.application_id,
                    interaction_token=authenticated.interaction_token,
                    scope=scope,
                    context=context,
                    received_at=received_at,
                ),
            )
        async with self.dispatcher_resolver.open() as dispatcher:
            return await dispatcher.dispatch_authenticated(
                authenticated=authenticated,
                received_at=received_at,
            )

    async def run_settings_component_handoff(
        self,
        handoff: DiscordSettingsComponentHandoff,
    ) -> None:
        """Resolve and run the replay graph after Discord acknowledgement."""
        async with self.dispatcher_resolver.open() as dispatcher:
            await dispatcher.run_settings_component_handoff(handoff)

    async def attempt_control_delivery(
        self,
        *,
        connection_id: str,
        plan: ProviderEffectPlan,
    ) -> None:
        """Resolve provider delivery dependencies only after acknowledgement."""
        async with self.dispatcher_resolver.open() as dispatcher:
            await dispatcher.attempt_control_delivery(
                connection_id=connection_id,
                plan=plan,
            )


async def _authenticate_discord_interaction(
    *,
    selector: str,
    raw_body: bytes,
    timestamp: str | None,
    signature: str | None,
    received_at: datetime.datetime,
    session_manager: SessionManager[AsyncSession],
    repository: ExternalChannelRepository,
    admission_service: ExternalChannelAdmissionService,
) -> DiscordAuthenticatedInteraction:
    """Authenticate and durably admit one Discord callback without dispatch work."""
    selector_hash = hashlib.sha256(selector.encode()).hexdigest()
    async with session_manager() as session:
        configuration = (
            await repository.get_discord_http_configuration_by_selector_hash(
                session,
                selector_hash=selector_hash,
            )
        )
    if configuration is None or configuration.capabilities is None:
        raise DiscordInteractionUnauthorized(
            "Discord interaction could not be authenticated.",
            failure_code="discord_callback_configuration_missing",
        )
    public_key = configuration.capabilities.get("interaction_public_key")
    if not isinstance(public_key, str):
        raise DiscordInteractionUnauthorized(
            "Discord interaction could not be authenticated.",
            failure_code="discord_callback_public_key_missing",
        )
    verify_discord_interaction_signature(
        raw_body=raw_body,
        timestamp=timestamp,
        signature=signature,
        public_key=public_key,
    )
    envelope = parse_discord_interaction(raw_body)
    interaction_token = discord_interaction_token(raw_body)
    if envelope.application_id != configuration.provider_app_id:
        raise DiscordInteractionUnauthorized(
            "Discord interaction could not be authenticated.",
            failure_code="discord_interaction_application_mismatch",
        )
    if envelope.interaction_type == 1:
        return DiscordAuthenticatedInteraction(
            configuration=configuration,
            envelope=envelope,
            admission=None,
            command_role=None,
            interaction_token=None,
        )
    if configuration.status not in {
        ExternalChannelConnectionStatus.ACTIVE,
        ExternalChannelConnectionStatus.DEGRADED,
    }:
        raise DiscordInteractionUnauthorized(
            "Discord interaction callback is not active.",
            failure_code="discord_interaction_not_active",
        )
    if envelope.guild_id != configuration.provider_tenant_id:
        raise DiscordInteractionUnauthorized(
            "Discord interaction could not be authenticated.",
            failure_code="discord_interaction_guild_mismatch",
        )
    command_role = validate_discord_command_capability(
        capabilities=configuration.capabilities,
        envelope=envelope,
    )
    inputs = discord_interaction_admission_inputs(
        connection_id=configuration.id,
        envelope=envelope,
        command_role=command_role,
        received_at=received_at,
    )
    admission = await admission_service.admit_interaction(
        create=inputs.create,
        principal=inputs.principal,
    )
    return DiscordAuthenticatedInteraction(
        configuration=configuration,
        envelope=envelope,
        admission=admission,
        command_role=command_role,
        interaction_token=interaction_token,
    )


def _optional_discord_settings_scope(
    *,
    custom_id: str,
    secret: str,
) -> DiscordSettingsScope | None:
    """Return a valid signed settings scope or defer rejection to the dispatcher."""
    try:
        return parse_discord_settings_custom_id(
            custom_id=custom_id,
            secret=secret,
        )
    except ValueError:
        return None


def _settings_context(
    *,
    envelope: DiscordInteractionEnvelope,
    connection_id: str,
    principal_id: str,
) -> DiscordSettingsContext:
    if envelope.guild_id is None or envelope.provider_parent_channel_id is None:
        raise DiscordInteractionInvalidPayload("Discord settings scope is unavailable.")
    return DiscordSettingsContext(
        connection_id=connection_id,
        guild_id=envelope.guild_id,
        provider_parent_channel_id=envelope.provider_parent_channel_id,
        provider_thread_resource_key=(
            None
            if envelope.provider_thread_id is None
            else f"discord:{envelope.guild_id}:{envelope.provider_thread_id}"
        ),
        principal_id=principal_id,
    )


def _already_linked_response() -> dict[str, object]:
    content = "This conversation is already linked to an Agent."
    return {
        "type": 4,
        "data": {
            "flags": 64,
            "content": content,
            "embeds": [
                {
                    "title": "Conversation already linked",
                    "description": content,
                    "color": 0xFEE75C,
                }
            ],
        },
    }


def _scheduled_task_cancel_confirmation_response(
    *,
    task: ScheduledTask,
    confirm_locator: str,
) -> dict[str, object]:
    """Render an ephemeral second step before cancelling future runs."""
    return {
        "type": 4,
        "data": {
            "flags": 64,
            "content": (
                f'Cancel Scheduled Task "{task.title}"? '
                "Future runs will stop. Work that has already started continues."
            ),
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 2,
                            "style": 4,
                            "label": "Confirm cancel",
                            "custom_id": confirm_locator,
                        }
                    ],
                }
            ],
        },
    }


def _scheduled_task_unavailable_component_response() -> dict[str, object]:
    return {
        "type": 7,
        "data": {
            "content": "This Scheduled Task control is unavailable.",
            "components": [],
        },
    }
