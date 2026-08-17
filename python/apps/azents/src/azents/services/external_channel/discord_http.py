"""Discord signed HTTP interaction admission boundary."""

import datetime
import hashlib
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelInteractionAdmission
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.scheduled_task.data import (
    MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH,
    ScheduledTask,
)
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.discord_api import DiscordGuildCommandRole
from azents.services.external_channel.discord_interaction import (
    DiscordInteractionEnvelope,
    DiscordInteractionInvalidPayload,
    DiscordInteractionUnauthorized,
    discord_interaction_admission_inputs,
    discord_message_command_source_event,
    parse_discord_interaction,
    validate_discord_command_capability,
    verify_discord_interaction_signature,
)
from azents.services.external_channel.discord_selector import (
    DiscordSelectorResponseService,
)
from azents.services.external_channel.discord_settings import (
    DiscordSettingsContext,
    DiscordSettingsResponseService,
)
from azents.services.external_channel.discord_settings_scope import (
    parse_discord_settings_custom_id,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
)
from azents.services.scheduled_task.control import (
    ScheduledTaskProviderControlError,
    ScheduledTaskProviderControlService,
    parse_scheduled_task_control_locator,
)


@dataclass(frozen=True)
class DiscordHTTPAdmissionResult:
    """Verified Discord interaction result before provider acknowledgement."""

    envelope: DiscordInteractionEnvelope
    admission: ExternalChannelInteractionAdmission | None
    response: dict[str, object] | None = None
    control_plans: tuple[ProviderEffectPlan, ...] = ()
    control_delivery_connection_id: str | None = None

    @property
    def ping(self) -> bool:
        """Return whether the interaction is Discord's endpoint verification PING."""
        return self.envelope.interaction_type == 1


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
        selector_hash = hashlib.sha256(selector.encode()).hexdigest()
        async with self.session_manager() as session:
            configuration = (
                await self.repository.get_discord_http_configuration_by_selector_hash(
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
        if envelope.application_id != configuration.provider_app_id:
            raise DiscordInteractionUnauthorized(
                "Discord interaction could not be authenticated.",
                failure_code="discord_interaction_application_mismatch",
            )
        if envelope.interaction_type == 1:
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=None)
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
        admission = await self.admission_service.admit_interaction(
            create=inputs.create,
            principal=inputs.principal,
        )
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
            response = await self.settings_response_service.component_response(
                interaction_id=admission.interaction.id,
                scope=parse_discord_settings_custom_id(
                    custom_id=custom_id,
                    secret=self.settings_response_service.config.auth.jwt.secret_key,
                ),
                context=context,
                now=received_at,
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
        except Exception:
            await self.admission_service.finish_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                status=ExternalChannelInteractionStatus.FAILED,
                error_kind="settings_component_failed",
                error_summary="Discord settings component could not be processed.",
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
            control_plans=response.cleanup_plans,
            control_delivery_connection_id=(
                context.connection_id if response.cleanup_plans else None
            ),
        )

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
            if locator.action == "edit":
                task = await self.scheduled_task_control.load_for_edit(
                    interaction_id=admission.interaction.id,
                    locator=locator,
                    provider_parent_channel_id=context.provider_parent_channel_id,
                    provider_thread_resource_key=context.provider_thread_resource_key,
                )
                response = _scheduled_task_edit_modal(
                    locator=envelope.component_custom_id or "",
                    task=task,
                )
            else:
                await self.scheduled_task_control.mutate(
                    interaction_id=admission.interaction.id,
                    locator=locator,
                    provider_parent_channel_id=context.provider_parent_channel_id,
                    provider_thread_resource_key=context.provider_thread_resource_key,
                    origin_interaction_id=None,
                    edit=None,
                    now=received_at,
                )
                response = {
                    "type": 7,
                    "data": {
                        "content": "Scheduled Task deleted.",
                        "components": [],
                    },
                }
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
        )

    async def _scheduled_task_modal_result(
        self,
        *,
        envelope: DiscordInteractionEnvelope,
        admission: ExternalChannelInteractionAdmission,
        context: DiscordSettingsContext,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        """Apply one idempotently claimed Scheduled Task edit modal."""
        response: dict[str, object]
        claim = await self.admission_service.begin_interaction_provider_mutation(
            interaction_id=admission.interaction.id,
            now=received_at,
        )
        if claim is None or not claim.claimed:
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=admission)
        try:
            locator = parse_scheduled_task_control_locator(
                locator=envelope.modal_custom_id or "",
                secret=self.scheduled_task_control.config.auth.jwt.secret_key,
            )
            if locator.action != "edit" or envelope.scheduled_task_edit is None:
                raise ScheduledTaskProviderControlError(
                    "Scheduled Task control is unavailable."
                )
            await self.scheduled_task_control.mutate(
                interaction_id=admission.interaction.id,
                locator=locator,
                provider_parent_channel_id=context.provider_parent_channel_id,
                provider_thread_resource_key=context.provider_thread_resource_key,
                origin_interaction_id=None,
                edit=envelope.scheduled_task_edit,
                now=received_at,
            )
            response = {
                "type": 4,
                "data": {"flags": 64, "content": "Scheduled Task saved."},
            }
        except ScheduledTaskProviderControlError, ValueError:
            response = {
                "type": 4,
                "data": {
                    "flags": 64,
                    "content": "This Scheduled Task control is unavailable.",
                },
            }
        except Exception:
            await self.admission_service.finish_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                status=ExternalChannelInteractionStatus.FAILED,
                error_kind="scheduled_task_modal_failed",
                error_summary="Discord Scheduled Task modal could not be processed.",
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

    async def _modal_result(
        self,
        *,
        envelope: DiscordInteractionEnvelope,
        admission: ExternalChannelInteractionAdmission,
        context: DiscordSettingsContext,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        custom_id = envelope.modal_custom_id
        if custom_id is not None and custom_id.startswith("st1:"):
            return await self._scheduled_task_modal_result(
                envelope=envelope,
                admission=admission,
                context=context,
                received_at=received_at,
            )
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
        await self.selector_response_service.attempt_control_delivery(
            connection_id=connection_id,
            plan=plan,
        )


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


def _scheduled_task_edit_modal(
    *,
    locator: str,
    task: ScheduledTask,
) -> dict[str, object]:
    """Render a Discord modal from the current exact Scheduled Task snapshot."""
    at = (
        ""
        if task.scheduled_at is None
        else task.scheduled_at.astimezone(datetime.UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {
        "type": 9,
        "data": {
            "custom_id": locator,
            "title": "Edit Scheduled Task",
            "components": [
                _scheduled_task_modal_input(
                    custom_id="azents_scheduled_task_title",
                    label="Title",
                    value=task.title,
                    style=1,
                    required=True,
                    max_length=120,
                ),
                _scheduled_task_modal_input(
                    custom_id="azents_scheduled_task_objective",
                    label="Objective",
                    value=task.objective,
                    style=2,
                    required=True,
                    max_length=MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH,
                ),
                _scheduled_task_modal_input(
                    custom_id="azents_scheduled_task_at",
                    label="Run once at (RFC3339 UTC)",
                    value=at,
                    style=1,
                    required=False,
                    max_length=128,
                ),
                _scheduled_task_modal_input(
                    custom_id="azents_scheduled_task_cron",
                    label="Cron expression",
                    value=task.cron_expression or "",
                    style=1,
                    required=False,
                    max_length=256,
                ),
                _scheduled_task_modal_input(
                    custom_id="azents_scheduled_task_timezone",
                    label="Cron timezone",
                    value=task.timezone or "",
                    style=1,
                    required=False,
                    max_length=128,
                ),
            ],
        },
    }


def _scheduled_task_modal_input(
    *,
    custom_id: str,
    label: str,
    value: str,
    style: int,
    required: bool,
    max_length: int,
) -> dict[str, object]:
    return {
        "type": 1,
        "components": [
            {
                "type": 4,
                "custom_id": custom_id,
                "label": label,
                "value": value,
                "style": style,
                "required": required,
                "max_length": max_length,
            }
        ],
    }


def _scheduled_task_unavailable_component_response() -> dict[str, object]:
    return {
        "type": 7,
        "data": {
            "content": "This Scheduled Task control is unavailable.",
            "components": [],
        },
    }
