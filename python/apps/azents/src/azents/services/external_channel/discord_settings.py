"""Discord-native conversation settings responses and signed control mutations."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelInteractionStatus,
    ExternalChannelResponseMode,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelInteraction
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.discord_settings_scope import (
    DiscordSettingsScope,
    build_discord_settings_custom_id,
    discord_binding_version,
    settings_action_location,
    settings_action_response_mode,
)
from azents.services.external_channel.ingestion_replay import (
    external_channel_replay_deadline,
)
from azents.services.external_channel.participation import (
    ExternalChannelParticipationError,
    ExternalChannelParticipationService,
    ExternalChannelParticipationSettings,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan


@dataclass(frozen=True)
class DiscordSettingsResponse:
    """One immediate Discord response and independent provider cleanup intents."""

    response: dict[str, object]
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclass(frozen=True)
class DiscordSettingsContext:
    """Authenticated provider scope needed to resolve current settings."""

    connection_id: str
    guild_id: str
    provider_parent_channel_id: str
    provider_thread_resource_key: str | None
    principal_id: str


@dataclass
class DiscordSettingsResponseService:
    """Render and mutate provider-native settings through canonical participation."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    participation_service: Annotated[
        ExternalChannelParticipationService,
        Depends(ExternalChannelParticipationService),
    ]
    config: Annotated[Config, Depends(get_config)]

    async def initial_response(
        self,
        *,
        origin_interaction_id: str,
        context: DiscordSettingsContext,
    ) -> DiscordSettingsResponse:
        """Render current setup, parent, or thread settings for a command actor."""
        try:
            settings = await self._resolve(context)
        except ExternalChannelParticipationError as error:
            return DiscordSettingsResponse(
                response=_notice_response(str(error)),
                cleanup_plans=(),
            )
        return DiscordSettingsResponse(
            response=_settings_response(
                settings=settings,
                origin_interaction_id=origin_interaction_id,
                secret=self.config.auth.jwt.secret_key,
            ),
            cleanup_plans=(),
        )

    async def component_response(
        self,
        *,
        interaction_id: str,
        scope: DiscordSettingsScope,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Revalidate one signed component and commit its canonical mutation."""
        try:
            if scope.action == "open_binding":
                return await self._binding_open_response(
                    scope=scope,
                    context=context,
                    interaction_id=interaction_id,
                )
            effective_context = (
                DiscordSettingsContext(
                    connection_id=context.connection_id,
                    guild_id=context.guild_id,
                    provider_parent_channel_id=context.provider_parent_channel_id,
                    provider_thread_resource_key=None,
                    principal_id=context.principal_id,
                )
                if scope.action in {"setup_channel", "setup_threads"}
                else context
            )
            settings = await self._resolve(effective_context)
            if scope.action in {"setup_channel", "setup_threads"}:
                return await self._select_setup_location(
                    scope=scope,
                    settings=settings,
                    context=effective_context,
                    now=now,
                )
            await self._validate_origin(scope=scope, context=context)
            if scope.action == "open":
                return DiscordSettingsResponse(
                    response=_settings_response(
                        settings=settings,
                        origin_interaction_id=scope.origin_interaction_id,
                        secret=self.config.auth.jwt.secret_key,
                    ),
                    cleanup_plans=(),
                )
            if scope.action in {
                "parent_channel",
                "parent_threads",
                "parent_mention_only",
                "parent_all_messages",
            }:
                return await self._mutate_parent(
                    scope=scope,
                    settings=settings,
                    context=context,
                    now=now,
                )
            if scope.action in {"thread_mention_only", "thread_all_messages"}:
                return await self._mutate_thread(
                    scope=scope,
                    settings=settings,
                    context=context,
                    now=now,
                )
            raise AssertionError("Discord settings action is not exhaustive.")
        except ExternalChannelParticipationError as error:
            return DiscordSettingsResponse(
                response=_notice_response(str(error)),
                cleanup_plans=(),
            )

    async def _binding_open_response(
        self,
        *,
        scope: DiscordSettingsScope,
        context: DiscordSettingsContext,
        interaction_id: str,
    ) -> DiscordSettingsResponse:
        """Open settings from a shared joined-presence Binding control."""
        settings = await self._resolve(context)
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
        location = settings_action_location(scope.action)
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
        await self.participation_service.select_location(
            setup_claim_id=claim.id,
            expected_claim_generation=claim.claim_generation,
            expected_source_revision=claim.source_revision,
            location=location,
            configured_by_principal_id=context.principal_id,
            now=now,
            deadline=external_channel_replay_deadline(now=now),
        )
        committed = await self._resolve(context)
        return DiscordSettingsResponse(
            response=_confirmation_response(committed),
            cleanup_plans=(),
        )

    async def _mutate_parent(
        self,
        *,
        scope: DiscordSettingsScope,
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
        location = settings_action_location(scope.action) or setting.location
        response_mode = (
            settings_action_response_mode(scope.action) or setting.response_mode
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
            response=_confirmation_response(mutation.settings),
            cleanup_plans=mutation.cleanup_plans,
        )

    async def _mutate_thread(
        self,
        *,
        scope: DiscordSettingsScope,
        settings: ExternalChannelParticipationSettings,
        context: DiscordSettingsContext,
        now: datetime.datetime,
    ) -> DiscordSettingsResponse:
        """Apply one signed connected-thread response-mode mutation."""
        resource = settings.resource
        binding = settings.binding
        response_mode = settings_action_response_mode(scope.action)
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
            response=_confirmation_response(mutation.settings),
            cleanup_plans=mutation.cleanup_plans,
        )

    async def _resolve(
        self,
        context: DiscordSettingsContext,
    ) -> ExternalChannelParticipationSettings:
        settings = await self.participation_service.resolve_settings(
            connection_id=context.connection_id,
            provider_parent_channel_id=context.provider_parent_channel_id,
            provider_thread_resource_key=context.provider_thread_resource_key,
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
        async with self.session_manager() as session:
            origin = await self.repository.lock_interaction(
                session,
                interaction_id=scope.origin_interaction_id,
            )
        if not _origin_matches(origin=origin, context=context):
            raise ExternalChannelParticipationError(
                "Discord conversation settings control is unavailable."
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


def _settings_response(
    *,
    settings: ExternalChannelParticipationSettings,
    origin_interaction_id: str,
    secret: str,
) -> dict[str, object]:
    title = (
        "Conversation setup" if settings.target == "setup" else "Conversation settings"
    )
    description = _settings_description(settings)
    return {
        "type": 4,
        "data": {
            "flags": 64,
            "content": description,
            "embeds": [{"title": title, "description": description, "color": 0x5865F2}],
            "components": _settings_components(
                settings=settings,
                origin_interaction_id=origin_interaction_id,
                secret=secret,
            ),
        },
    }


def _settings_components(
    *,
    settings: ExternalChannelParticipationSettings,
    origin_interaction_id: str,
    secret: str,
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
    if settings.target == "parent":
        setting = settings.setting
        if setting is None:
            raise AssertionError("Discord parent settings are incomplete.")
        return [
            _button_row(
                (
                    "Use channel",
                    1,
                    build_discord_settings_custom_id(
                        secret=secret,
                        action="parent_channel",
                        origin_interaction_id=origin_interaction_id,
                        setting_id=setting.id,
                        settings_generation=setting.settings_generation,
                    ),
                ),
                (
                    "Use threads",
                    2,
                    build_discord_settings_custom_id(
                        secret=secret,
                        action="parent_threads",
                        origin_interaction_id=origin_interaction_id,
                        setting_id=setting.id,
                        settings_generation=setting.settings_generation,
                    ),
                ),
            ),
            _button_row(
                (
                    "Mentions only",
                    2,
                    build_discord_settings_custom_id(
                        secret=secret,
                        action="parent_mention_only",
                        origin_interaction_id=origin_interaction_id,
                        setting_id=setting.id,
                        settings_generation=setting.settings_generation,
                    ),
                ),
                (
                    "All messages",
                    4,
                    build_discord_settings_custom_id(
                        secret=secret,
                        action="parent_all_messages",
                        origin_interaction_id=origin_interaction_id,
                        setting_id=setting.id,
                        settings_generation=setting.settings_generation,
                    ),
                ),
            ),
        ]
    binding = settings.binding
    if binding is None:
        raise AssertionError("Discord thread settings are incomplete.")
    return [
        _button_row(
            (
                "Mentions only",
                2,
                build_discord_settings_custom_id(
                    secret=secret,
                    action="thread_mention_only",
                    origin_interaction_id=origin_interaction_id,
                    binding_id=binding.id,
                    binding_updated_at=binding.updated_at,
                ),
            ),
            (
                "All messages",
                4,
                build_discord_settings_custom_id(
                    secret=secret,
                    action="thread_all_messages",
                    origin_interaction_id=origin_interaction_id,
                    binding_id=binding.id,
                    binding_updated_at=binding.updated_at,
                ),
            ),
        )
    ]


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
