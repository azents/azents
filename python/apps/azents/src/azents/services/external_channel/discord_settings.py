"""Discord-native conversation settings responses and signed control mutations."""

import datetime
from dataclasses import dataclass, replace
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelInteractionStatus,
    ExternalChannelProvider,
    ExternalChannelResponseMode,
)
from azents.core.external_account_link import (
    ExternalAccountLinkError,
    ExternalAccountLinkState,
    ExternalAccountNativeLinkState,
    VerifiedExternalAccountActor,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.external_channel_session_presence import (
    build_external_channel_session_url,
)
from azents.core.external_model_settings import (
    ExternalModelActorContext,
    ExternalModelDraftSelection,
    ExternalModelEditorReady,
    ExternalModelTargetContext,
)
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelInteraction
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_account_link import ExternalAccountLinkService
from azents.services.external_channel.discord_account_link import (
    DiscordAccountLinkPresentation,
    discord_account_link_code_modal,
    discord_account_link_error_response,
    discord_account_link_presentation,
    discord_account_link_started_response,
    discord_account_link_state_unavailable,
    discord_account_link_verified_response,
)
from azents.services.external_channel.discord_model_settings import (
    DiscordModelSettingsPresentation,
    discord_model_apply_response,
    discord_model_cancel_response,
    discord_model_editor_result_response,
    discord_model_entry_presentation,
    discord_model_invalid_selection_response,
    model_page_size,
    parse_reasoning_effort,
)
from azents.services.external_channel.discord_settings_scope import (
    DiscordAccountLinkScope,
    DiscordModelSettingsScope,
    DiscordSettingsScope,
    build_discord_settings_custom_id,
    discord_binding_version,
    settings_selected_location,
    settings_selected_response_mode,
    settings_setup_location,
)
from azents.services.external_channel.ingestion_replay import (
    external_channel_replay_deadline,
)
from azents.services.external_channel.model_settings import ExternalModelSettingsService
from azents.services.external_channel.participation import (
    ExternalChannelParticipationError,
    ExternalChannelParticipationService,
    ExternalChannelParticipationSettings,
)


@dataclass(frozen=True)
class DiscordSettingsResponse:
    """One immediate Discord response and independent provider cleanup intents."""

    response: dict[str, object]
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclass(frozen=True)
class DiscordSettingsContext:
    """Authenticated provider scope needed to resolve current settings."""

    connection_id: str
    connection_configuration_generation: int
    guild_id: str
    guild_display_name: str | None
    provider_parent_channel_id: str
    provider_thread_id: str | None
    provider_thread_resource_key: str | None
    principal_id: str
    provider_user_id: str
    provider_display_name: str
    provider_interaction_id: str


@dataclass(frozen=True)
class DiscordPrivatePresentations:
    """Private personal sections appended independently from guest controls."""

    account: DiscordAccountLinkPresentation
    model: DiscordModelSettingsPresentation


@dataclass
class DiscordSettingsResponseService:
    """Render and mutate provider-native settings through canonical participation."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    participation_service: Annotated[
        ExternalChannelParticipationService,
        Depends(ExternalChannelParticipationService),
    ]
    account_link_service: Annotated[
        ExternalAccountLinkService,
        Depends(ExternalAccountLinkService),
    ]
    model_settings_service: Annotated[
        ExternalModelSettingsService,
        Depends(ExternalModelSettingsService),
    ]
    config: Annotated[Config, Depends(get_config)]

    async def initial_response(
        self,
        *,
        origin_interaction_id: str,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Render guest controls and actor-private personal settings."""
        account_state, account = await self._account_presentation(
            origin_interaction_id=origin_interaction_id,
            context=context,
            now=now,
        )
        try:
            settings = await self._resolve(context, expected_binding_id=None)
        except ExternalChannelParticipationError:
            return DiscordSettingsResponse(
                response=_link_only_response(account=account, response_type=4),
                cleanup_plans=(),
            )
        model = await self._model_presentation(
            settings=settings,
            account_state=account_state,
            context=context,
            now=now,
        )
        return DiscordSettingsResponse(
            response=_settings_response(
                settings=settings,
                origin_interaction_id=origin_interaction_id,
                secret=self.config.auth.jwt.secret_key,
                web_url=self.config.web_url,
                response_type=4,
                personal=DiscordPrivatePresentations(account=account, model=model),
            ),
            cleanup_plans=(),
        )

    async def component_response(
        self,
        *,
        interaction_id: str,
        scope: DiscordSettingsScope,
        selected_value: str | None,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Revalidate one signed component and commit its canonical mutation."""
        try:
            if scope.action == "open_binding":
                _require_button_interaction(selected_value)
                return await self._binding_open_response(
                    scope=scope,
                    context=context,
                    interaction_id=interaction_id,
                    now=now,
                )
            effective_context = (
                replace(
                    context,
                    provider_thread_id=None,
                    provider_thread_resource_key=None,
                )
                if scope.action in {"setup_channel", "setup_threads"}
                else context
            )
            settings = await self._resolve(
                effective_context,
                expected_binding_id=(
                    scope.binding_id if scope.action == "thread_response_mode" else None
                ),
            )
            if scope.action in {"setup_channel", "setup_threads"}:
                _require_button_interaction(selected_value)
                return await self._select_setup_location(
                    scope=scope,
                    settings=settings,
                    context=effective_context,
                    now=now,
                )
            await self._validate_origin(scope=scope, context=context)
            if scope.action == "open":
                _require_button_interaction(selected_value)
                return DiscordSettingsResponse(
                    response=_settings_response(
                        settings=settings,
                        origin_interaction_id=scope.origin_interaction_id,
                        secret=self.config.auth.jwt.secret_key,
                        web_url=self.config.web_url,
                        response_type=4,
                        personal=await self._private_presentations(
                            settings=settings,
                            origin_interaction_id=scope.origin_interaction_id,
                            context=context,
                            now=now,
                        ),
                    ),
                    cleanup_plans=(),
                )
            if scope.action in {"parent_location", "parent_response_mode"}:
                return await self._mutate_parent(
                    scope=scope,
                    selected_value=selected_value,
                    settings=settings,
                    context=context,
                    now=now,
                )
            if scope.action == "thread_response_mode":
                return await self._mutate_thread(
                    scope=scope,
                    selected_value=selected_value,
                    settings=settings,
                    context=context,
                    now=now,
                )
            raise AssertionError("Discord settings action is not exhaustive.")
        except ExternalChannelParticipationError:
            _, account = await self._account_presentation(
                origin_interaction_id=interaction_id,
                context=context,
                now=now,
            )
            return DiscordSettingsResponse(
                response=_link_only_response(account=account, response_type=4),
                cleanup_plans=(),
            )

    async def account_link_response(
        self,
        *,
        scope: DiscordAccountLinkScope,
        code: str | None,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Run an account-link control without conversation authority."""
        try:
            actor = _account_actor(context)
            if scope.action == "start":
                if code is not None or scope.origin_interaction_id is None:
                    raise ValueError("Discord account-link control is invalid.")
                await self._validate_origin_interaction(
                    origin_interaction_id=scope.origin_interaction_id,
                    context=context,
                )
                created = await self.account_link_service.create_origin(
                    actor=actor,
                    now=now,
                )
                response = discord_account_link_started_response(
                    created=created,
                    secret=self.config.auth.jwt.secret_key,
                    web_url=self.config.web_url,
                )
            elif scope.action == "enter_code":
                if scope.origin_id is None:
                    raise ValueError("Discord account-link control is invalid.")
                if code is None:
                    response = discord_account_link_code_modal(
                        origin_id=scope.origin_id,
                        secret=self.config.auth.jwt.secret_key,
                    )
                else:
                    proof = await self.account_link_service.verify_candidate_code(
                        actor=actor,
                        origin_id=scope.origin_id,
                        code=code,
                        now=now,
                    )
                    response = discord_account_link_verified_response(
                        result=proof,
                        origin_id=scope.origin_id,
                        web_url=self.config.web_url,
                    )
            else:
                raise AssertionError("Discord account-link action is not exhaustive.")
        except ExternalAccountLinkError as error:
            response = discord_account_link_error_response(error)
        except ExternalChannelParticipationError, ValueError:
            response = _private_control_unavailable_response()
        return DiscordSettingsResponse(response=response, cleanup_plans=())

    async def model_response(
        self,
        *,
        scope: DiscordModelSettingsScope,
        selected_values: tuple[str, ...],
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Run one actor-owned model draft independently from guest settings."""
        actor = _model_actor(context)
        limit = model_page_size()
        if scope.action in {"open", "previous_page", "next_page"}:
            result = await self.model_settings_service.page_options(
                actor=actor,
                draft_id=scope.draft_id,
                now=now,
                offset=scope.offset,
                limit=limit,
            )
            return DiscordSettingsResponse(
                response=discord_model_editor_result_response(
                    result=result,
                    secret=self.config.auth.jwt.secret_key,
                ),
                cleanup_plans=(),
            )
        if scope.action == "cancel":
            result = await self.model_settings_service.cancel_draft(
                actor=actor,
                draft_id=scope.draft_id,
                now=now,
            )
            return DiscordSettingsResponse(
                response=discord_model_cancel_response(result),
                cleanup_plans=(),
            )
        if scope.action == "apply":
            if scope.selection_fingerprint is None:
                return DiscordSettingsResponse(
                    response=discord_model_invalid_selection_response(),
                    cleanup_plans=(),
                )
            result = await self.model_settings_service.apply_draft(
                actor=actor,
                draft_id=scope.draft_id,
                expected_selection_fingerprint=scope.selection_fingerprint,
                apply_interaction_key=context.provider_interaction_id,
                now=now,
            )
            return DiscordSettingsResponse(
                response=discord_model_apply_response(
                    result=result,
                    secret=self.config.auth.jwt.secret_key,
                ),
                cleanup_plans=(),
            )
        current = await self.model_settings_service.page_options(
            actor=actor,
            draft_id=scope.draft_id,
            now=now,
            offset=scope.offset,
            limit=limit,
        )
        if not isinstance(current, ExternalModelEditorReady):
            return DiscordSettingsResponse(
                response=discord_model_editor_result_response(
                    result=current,
                    secret=self.config.auth.jwt.secret_key,
                ),
                cleanup_plans=(),
            )
        try:
            selection = _updated_model_selection(
                scope=scope,
                selected_values=selected_values,
                current=current,
            )
        except ValueError:
            return DiscordSettingsResponse(
                response=discord_model_invalid_selection_response(),
                cleanup_plans=(),
            )
        result = await self.model_settings_service.update_draft(
            actor=actor,
            draft_id=scope.draft_id,
            selection=selection,
            now=now,
            offset=scope.offset,
            limit=limit,
        )
        return DiscordSettingsResponse(
            response=discord_model_editor_result_response(
                result=result,
                secret=self.config.auth.jwt.secret_key,
            ),
            cleanup_plans=(),
        )

    async def _binding_open_response(
        self,
        *,
        scope: DiscordSettingsScope,
        context: DiscordSettingsContext,
        interaction_id: str,
        now: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Open settings from a shared joined-presence Binding control."""
        settings = await self._resolve(
            context,
            expected_binding_id=scope.origin_interaction_id,
        )
        if (
            settings.binding is None
            or settings.binding.id != scope.origin_interaction_id
        ):
            raise ExternalChannelParticipationError(
                "External Channel conversation settings changed."
            )
        return DiscordSettingsResponse(
            response=_settings_response(
                settings=settings,
                origin_interaction_id=interaction_id,
                secret=self.config.auth.jwt.secret_key,
                web_url=self.config.web_url,
                response_type=4,
                personal=await self._private_presentations(
                    settings=settings,
                    origin_interaction_id=interaction_id,
                    context=context,
                    now=now,
                ),
            ),
            cleanup_plans=(),
        )

    async def _select_setup_location(
        self,
        *,
        scope: DiscordSettingsScope,
        settings: ExternalChannelParticipationSettings,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Commit a setup choice and independently continue its canonical source."""
        claim = settings.claim
        location = settings_setup_location(scope.action)
        if (
            settings.target != "setup"
            or claim is None
            or scope.setup_claim_id != claim.id
            or scope.claim_generation != claim.claim_generation
            or scope.source_revision != claim.source_revision
            or location is None
        ):
            raise ExternalChannelParticipationError(
                "External Channel setup changed before submission."
            )
        selection = await self.participation_service.select_location(
            setup_claim_id=claim.id,
            expected_claim_generation=claim.claim_generation,
            expected_source_revision=claim.source_revision,
            location=location,
            configured_by_principal_id=context.principal_id,
            now=now,
            deadline=external_channel_replay_deadline(now=now),
        )
        committed = await self._resolve(context, expected_binding_id=None)
        return DiscordSettingsResponse(
            response=_confirmation_response(committed),
            cleanup_plans=(
                ()
                if selection.replay_outcome is None
                else selection.replay_outcome.control_plans
            ),
        )

    async def _mutate_parent(
        self,
        *,
        scope: DiscordSettingsScope,
        selected_value: str | None,
        settings: ExternalChannelParticipationSettings,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Apply one signed parent location or response-mode mutation."""
        setting = settings.setting
        if (
            settings.target != "parent"
            or setting is None
            or scope.setting_id != setting.id
            or scope.settings_generation != setting.settings_generation
        ):
            raise ExternalChannelParticipationError(
                "External Channel settings changed before submission."
            )
        if scope.action == "parent_location":
            location = settings_selected_location(selected_value)
            response_mode = setting.response_mode
        elif scope.action == "parent_response_mode":
            location = setting.location
            response_mode = settings_selected_response_mode(selected_value)
        else:
            raise AssertionError("Discord parent settings action is not exhaustive.")
        if location is None or response_mode is None:
            raise ExternalChannelParticipationError(
                "Discord conversation settings selection is invalid."
            )
        mutation = await self.participation_service.mutate_parent_settings(
            connection_id=context.connection_id,
            provider_parent_channel_id=context.provider_parent_channel_id,
            principal_id=context.principal_id,
            expected_setting_id=setting.id,
            expected_settings_generation=setting.settings_generation,
            location=location,
            response_mode=response_mode,
            now=now,
            deadline=external_channel_replay_deadline(now=now),
        )
        return DiscordSettingsResponse(
            response=_settings_response(
                settings=mutation.settings,
                origin_interaction_id=scope.origin_interaction_id,
                secret=self.config.auth.jwt.secret_key,
                web_url=self.config.web_url,
                response_type=7,
                personal=await self._private_presentations(
                    settings=mutation.settings,
                    origin_interaction_id=scope.origin_interaction_id,
                    context=context,
                    now=now,
                ),
            ),
            cleanup_plans=mutation.cleanup_plans,
        )

    async def _mutate_thread(
        self,
        *,
        scope: DiscordSettingsScope,
        selected_value: str | None,
        settings: ExternalChannelParticipationSettings,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Apply one signed connected-thread response-mode mutation."""
        resource = settings.resource
        binding = settings.binding
        response_mode = settings_selected_response_mode(selected_value)
        if (
            settings.target != "thread"
            or resource is None
            or binding is None
            or scope.binding_id != binding.id
            or scope.binding_version != discord_binding_version(binding.updated_at)
            or response_mode is None
        ):
            raise ExternalChannelParticipationError(
                "External Channel thread settings changed before submission."
            )
        mutation = await self.participation_service.mutate_thread_settings(
            connection_id=context.connection_id,
            provider_parent_channel_id=context.provider_parent_channel_id,
            resource_id=resource.id,
            binding_id=binding.id,
            principal_id=context.principal_id,
            expected_response_mode=binding.response_mode,
            expected_binding_updated_at=binding.updated_at,
            response_mode=response_mode,
            now=now,
            deadline=external_channel_replay_deadline(now=now),
        )
        return DiscordSettingsResponse(
            response=_settings_response(
                settings=mutation.settings,
                origin_interaction_id=scope.origin_interaction_id,
                secret=self.config.auth.jwt.secret_key,
                web_url=self.config.web_url,
                response_type=7,
                personal=await self._private_presentations(
                    settings=mutation.settings,
                    origin_interaction_id=scope.origin_interaction_id,
                    context=context,
                    now=now,
                ),
            ),
            cleanup_plans=mutation.cleanup_plans,
        )

    async def _resolve(
        self,
        context: DiscordSettingsContext,
        *,
        expected_binding_id: str | None,
    ) -> ExternalChannelParticipationSettings:
        settings = await self.participation_service.resolve_settings(
            connection_id=context.connection_id,
            provider_parent_channel_id=context.provider_parent_channel_id,
            provider_thread_resource_key=context.provider_thread_resource_key,
            expected_binding_id=expected_binding_id,
            principal_id=context.principal_id,
        )
        if (
            context.provider_thread_resource_key is not None
            and settings.target != "thread"
        ):
            raise ExternalChannelParticipationError(
                "External Channel thread settings are unavailable."
            )
        return settings

    async def _validate_origin(
        self,
        *,
        scope: DiscordSettingsScope,
        context: DiscordSettingsContext,
    ) -> None:
        """Bind controls to their original authenticated command actor and scope."""
        await self._validate_origin_interaction(
            origin_interaction_id=scope.origin_interaction_id,
            context=context,
        )

    async def _validate_origin_interaction(
        self,
        *,
        origin_interaction_id: str,
        context: DiscordSettingsContext,
    ) -> None:
        """Bind any signed private control to its original admitted actor."""
        async with self.session_manager() as session:
            origin = await self.repository.lock_interaction(
                session,
                interaction_id=origin_interaction_id,
            )
        if not _origin_matches(origin=origin, context=context):
            raise ExternalChannelParticipationError(
                "Discord conversation settings control is unavailable."
            )

    async def _account_presentation(
        self,
        *,
        origin_interaction_id: str,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> tuple[ExternalAccountNativeLinkState | None, DiscordAccountLinkPresentation]:
        try:
            state = await self.account_link_service.get_native_link_state(
                actor=_account_actor(context),
                now=now,
            )
        except ExternalAccountLinkError:
            return None, discord_account_link_state_unavailable()
        return state, discord_account_link_presentation(
            state=state,
            origin_interaction_id=origin_interaction_id,
            secret=self.config.auth.jwt.secret_key,
            web_url=self.config.web_url,
        )

    async def _private_presentations(
        self,
        *,
        settings: ExternalChannelParticipationSettings,
        origin_interaction_id: str,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordPrivatePresentations:
        account_state, account = await self._account_presentation(
            origin_interaction_id=origin_interaction_id,
            context=context,
            now=now,
        )
        model = await self._model_presentation(
            settings=settings,
            account_state=account_state,
            context=context,
            now=now,
        )
        return DiscordPrivatePresentations(account=account, model=model)

    async def _model_presentation(
        self,
        *,
        settings: ExternalChannelParticipationSettings,
        account_state: ExternalAccountNativeLinkState | None,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordModelSettingsPresentation:
        target = _model_target(settings)
        if (
            account_state is None
            or account_state.link is None
            or account_state.link.state is not ExternalAccountLinkState.ACTIVE
            or target is None
        ):
            return DiscordModelSettingsPresentation(summary=None, rows=[])
        result = await self.model_settings_service.open_editor(
            actor=_model_actor(context),
            target=target,
            owner_interaction_key=context.provider_interaction_id,
            now=now,
            offset=0,
            limit=model_page_size(),
        )
        return discord_model_entry_presentation(
            result=result,
            secret=self.config.auth.jwt.secret_key,
        )


def _origin_matches(
    *,
    origin: ExternalChannelInteraction | None,
    context: DiscordSettingsContext,
) -> bool:
    if (
        origin is None
        or origin.connection_id != context.connection_id
        or origin.principal_id != context.principal_id
        or origin.status
        not in {
            ExternalChannelInteractionStatus.ACCEPTED,
            ExternalChannelInteractionStatus.COMPLETED,
        }
    ):
        return False
    projection = origin.projection
    return (
        projection.get("guild_id") == context.guild_id
        and projection.get("provider_parent_channel_id")
        == context.provider_parent_channel_id
        and projection.get("provider_thread_resource_key")
        == context.provider_thread_resource_key
    )


def _require_button_interaction(selected_value: str | None) -> None:
    """Reject Select values attached to button-only settings actions."""
    if selected_value is not None:
        raise ExternalChannelParticipationError(
            "Discord conversation settings selection is invalid."
        )


def _settings_response(
    *,
    settings: ExternalChannelParticipationSettings,
    origin_interaction_id: str,
    secret: str,
    web_url: str,
    response_type: Literal[4, 7],
    personal: DiscordPrivatePresentations | None = None,
) -> dict[str, object]:
    title = (
        "Conversation setup" if settings.target == "setup" else "Conversation settings"
    )
    description_parts = [_settings_description(settings)]
    if personal is not None:
        description_parts.append(personal.account.summary)
        if personal.model.summary is not None:
            description_parts.append(personal.model.summary)
    description = "\n\n".join(description_parts)
    components = _settings_components(
        settings=settings,
        origin_interaction_id=origin_interaction_id,
        secret=secret,
        session_url=_settings_session_url(settings=settings, web_url=web_url),
    )
    if personal is not None:
        components.extend(personal.account.rows)
        components.extend(personal.model.rows)
    data: dict[str, object] = {
        "content": description,
        "embeds": [{"title": title, "description": description, "color": 0x5865F2}],
        "components": components,
        "allowed_mentions": {"parse": []},
    }
    if response_type == 4:
        data["flags"] = 64
    return {"type": response_type, "data": data}


def _settings_components(
    *,
    settings: ExternalChannelParticipationSettings,
    origin_interaction_id: str,
    secret: str,
    session_url: str | None,
) -> list[dict[str, object]]:
    if settings.target == "setup":
        claim = settings.claim
        if claim is None:
            raise AssertionError("Discord setup settings are incomplete.")
        return [
            _button_row(
                (
                    "Answer in this channel",
                    1,
                    build_discord_settings_custom_id(
                        secret=secret,
                        action="setup_channel",
                        origin_interaction_id=origin_interaction_id,
                        setup_claim_id=claim.id,
                        claim_generation=claim.claim_generation,
                        source_revision=claim.source_revision,
                    ),
                ),
                (
                    "Answer in threads",
                    2,
                    build_discord_settings_custom_id(
                        secret=secret,
                        action="setup_threads",
                        origin_interaction_id=origin_interaction_id,
                        setup_claim_id=claim.id,
                        claim_generation=claim.claim_generation,
                        source_revision=claim.source_revision,
                    ),
                ),
            )
        ]
    rows: list[dict[str, object]] = []
    if settings.target == "parent":
        setting = settings.setting
        if setting is None:
            raise AssertionError("Discord parent settings are incomplete.")
        rows.extend(
            (
                _select_row(
                    custom_id=build_discord_settings_custom_id(
                        secret=secret,
                        action="parent_location",
                        origin_interaction_id=origin_interaction_id,
                        setting_id=setting.id,
                        settings_generation=setting.settings_generation,
                    ),
                    placeholder="Where to respond",
                    options=(
                        (
                            "This channel",
                            "channel",
                            setting.location
                            is ExternalChannelConversationLocation.CHANNEL,
                        ),
                        (
                            "Threads",
                            "threads",
                            setting.location
                            is ExternalChannelConversationLocation.THREADS,
                        ),
                    ),
                ),
                _select_row(
                    custom_id=build_discord_settings_custom_id(
                        secret=secret,
                        action="parent_response_mode",
                        origin_interaction_id=origin_interaction_id,
                        setting_id=setting.id,
                        settings_generation=setting.settings_generation,
                    ),
                    placeholder="When to respond",
                    options=_response_mode_options(setting.response_mode),
                ),
            )
        )
    else:
        binding = settings.binding
        if binding is None:
            raise AssertionError("Discord thread settings are incomplete.")
        rows.append(
            _select_row(
                custom_id=build_discord_settings_custom_id(
                    secret=secret,
                    action="thread_response_mode",
                    origin_interaction_id=origin_interaction_id,
                    binding_id=binding.id,
                    binding_updated_at=binding.updated_at,
                ),
                placeholder="When to respond",
                options=_response_mode_options(binding.response_mode),
            )
        )
    if session_url is not None:
        rows.append(
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": "View session",
                        "url": session_url,
                    }
                ],
            }
        )
    return rows


def _select_row(
    *,
    custom_id: str,
    placeholder: str,
    options: tuple[tuple[str, str, bool], ...],
) -> dict[str, object]:
    return {
        "type": 1,
        "components": [
            {
                "type": 3,
                "custom_id": custom_id,
                "placeholder": placeholder,
                "min_values": 1,
                "max_values": 1,
                "options": [
                    {"label": label, "value": value, "default": default}
                    for label, value, default in options
                ],
            }
        ],
    }


def _response_mode_options(
    response_mode: ExternalChannelResponseMode,
) -> tuple[tuple[str, str, bool], ...]:
    return (
        (
            "When mentioned",
            "mention_only",
            response_mode is ExternalChannelResponseMode.MENTION_ONLY,
        ),
        (
            "Every message",
            "all_messages",
            response_mode is ExternalChannelResponseMode.ALL_MESSAGES,
        ),
    )


def _settings_session_url(
    *,
    settings: ExternalChannelParticipationSettings,
    web_url: str,
) -> str | None:
    navigation = settings.session_navigation
    if navigation is None:
        return None
    return build_external_channel_session_url(
        web_url,
        navigation.workspace_handle,
        navigation.agent_id,
        navigation.session_id,
    )


def _button_row(
    *buttons: tuple[str, int, str],
) -> dict[str, object]:
    return {
        "type": 1,
        "components": [
            {"type": 2, "style": style, "label": label, "custom_id": custom_id}
            for label, style, custom_id in buttons
        ],
    }


def _settings_description(settings: ExternalChannelParticipationSettings) -> str:
    if settings.target == "setup":
        return (
            f"Choose where **{settings.agent_name}** should continue "
            "this conversation. The original mention will continue after you choose."
        )
    if settings.target == "thread":
        binding = settings.binding
        if binding is None:
            raise AssertionError("Discord thread settings are incomplete.")
        return (
            f"**{settings.agent_name}** responds in this thread using "
            f"**{_response_mode_label(binding.response_mode)}**."
        )
    setting = settings.setting
    if setting is None:
        raise AssertionError("Discord parent settings are incomplete.")
    guidance = (
        " Use Mentions only if the Agent is too chatty."
        if setting.response_mode is ExternalChannelResponseMode.ALL_MESSAGES
        else ""
    )
    return (
        f"**{settings.agent_name}** uses **{_location_label(setting.location)}** "
        f"with **{_response_mode_label(setting.response_mode)}**.{guidance}"
    )


def _confirmation_response(
    settings: ExternalChannelParticipationSettings,
) -> dict[str, object]:
    if settings.target == "thread":
        binding = settings.binding
        if binding is None:
            raise AssertionError("Discord thread confirmation is incomplete.")
        description = (
            "This thread now responds to "
            f"**{_response_mode_label(binding.response_mode)}**."
        )
    else:
        setting = settings.setting
        if setting is None:
            raise AssertionError("Discord parent confirmation is incomplete.")
        description = (
            "Conversation settings saved: "
            f"**{_location_label(setting.location)}**, "
            f"**{_response_mode_label(setting.response_mode)}**."
        )
        if setting.response_mode is ExternalChannelResponseMode.ALL_MESSAGES:
            description += " Use Mentions only if the Agent is too chatty."
    return {
        "type": 7,
        "data": {
            "content": description,
            "embeds": [
                {
                    "title": "Settings saved",
                    "description": description,
                    "color": 0x57F287,
                }
            ],
            "components": [],
        },
    }


def _notice_response(message: str) -> dict[str, object]:
    description = (
        " ".join(message.split())[:500] or "Conversation settings are unavailable."
    )
    return {
        "type": 4,
        "data": {
            "flags": 64,
            "content": description,
            "embeds": [
                {
                    "title": "Conversation settings unavailable",
                    "description": description,
                    "color": 0x99AAB5,
                }
            ],
            "components": [],
        },
    }


def _link_only_response(
    *,
    account: DiscordAccountLinkPresentation,
    response_type: Literal[4, 7],
) -> dict[str, object]:
    description = (
        f"Conversation settings are unavailable for this account.\n\n{account.summary}"
    )
    data: dict[str, object] = {
        "content": description,
        "embeds": [
            {
                "title": "Personal settings",
                "description": description,
                "color": 0x99AAB5,
            }
        ],
        "components": account.rows,
        "allowed_mentions": {"parse": []},
    }
    if response_type == 4:
        data["flags"] = 64
    return {"type": response_type, "data": data}


def _private_control_unavailable_response() -> dict[str, object]:
    description = "This private settings control is unavailable. Reopen settings."
    return {
        "type": 7,
        "data": {
            "content": description,
            "embeds": [
                {
                    "title": "Private settings unavailable",
                    "description": description,
                    "color": 0x99AAB5,
                }
            ],
            "components": [],
            "allowed_mentions": {"parse": []},
        },
    }


def _account_actor(context: DiscordSettingsContext) -> VerifiedExternalAccountActor:
    return VerifiedExternalAccountActor(
        connection_id=context.connection_id,
        connection_configuration_generation=context.connection_configuration_generation,
        principal_id=context.principal_id,
        provider=ExternalChannelProvider.DISCORD,
        provider_tenant_id=context.guild_id,
        provider_tenant_display_label=context.guild_display_name,
        provider_user_id=context.provider_user_id,
        provider_display_label=context.provider_display_name,
        provider_interaction_id=context.provider_interaction_id,
        provider_channel_id=context.provider_parent_channel_id,
        provider_thread_id=context.provider_thread_id,
    )


def _model_actor(context: DiscordSettingsContext) -> ExternalModelActorContext:
    return ExternalModelActorContext(
        provider=ExternalChannelProvider.DISCORD,
        connection_id=context.connection_id,
        configuration_generation=context.connection_configuration_generation,
        principal_id=context.principal_id,
        provider_tenant_id=context.guild_id,
        provider_user_id=context.provider_user_id,
        provider_display_name=context.provider_display_name,
    )


def _model_target(
    settings: ExternalChannelParticipationSettings,
) -> ExternalModelTargetContext | None:
    binding = settings.binding
    navigation = settings.session_navigation
    if (
        settings.target == "setup"
        or binding is None
        or navigation is None
        or binding.agent_session_id != navigation.session_id
    ):
        return None
    return ExternalModelTargetContext(
        binding_id=binding.id,
        session_id=navigation.session_id,
        agent_id=navigation.agent_id,
    )


def _updated_model_selection(
    *,
    scope: DiscordModelSettingsScope,
    selected_values: tuple[str, ...],
    current: ExternalModelEditorReady,
) -> ExternalModelDraftSelection:
    existing = current.editor.draft.selection
    if scope.action == "select_model":
        if len(selected_values) != 1:
            raise ValueError("Discord model selection is invalid.")
        return ExternalModelDraftSelection(
            option_id=selected_values[0],
            reasoning_effort=None,
            enabled_execution_options=[],
        )
    if scope.action == "select_reasoning":
        if len(selected_values) != 1:
            raise ValueError("Discord model selection is invalid.")
        return ExternalModelDraftSelection(
            option_id=existing.option_id,
            reasoning_effort=parse_reasoning_effort(selected_values[0]),
            enabled_execution_options=existing.enabled_execution_options,
        )
    if scope.action == "select_execution":
        try:
            execution_options = [
                ModelExecutionOptionId(value) for value in selected_values
            ]
        except ValueError as error:
            raise ValueError("Discord model selection is invalid.") from error
        return ExternalModelDraftSelection(
            option_id=existing.option_id,
            reasoning_effort=existing.reasoning_effort,
            enabled_execution_options=execution_options,
        )
    raise AssertionError("Discord model selection action is not exhaustive.")


def _location_label(location: ExternalChannelConversationLocation) -> str:
    return (
        "this channel"
        if location is ExternalChannelConversationLocation.CHANNEL
        else "threads"
    )


def _response_mode_label(mode: ExternalChannelResponseMode) -> str:
    return (
        "mentions only"
        if mode is ExternalChannelResponseMode.MENTION_ONLY
        else "all messages"
    )
