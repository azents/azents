"""Discord-native rendering for durable External Channel Agent selection."""

import datetime
import hmac
from dataclasses import dataclass
from typing import Annotated, assert_never

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.services.external_channel.discord_selector_scope import (
    build_discord_selector_custom_id,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcomeKind,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
    external_channel_replay_deadline,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
    get_external_channel_provider_control_service,
)
from azents.services.external_channel.selector import (
    ExternalChannelSelectorCatalog,
    ExternalChannelSelectorService,
)

_DISCORD_SELECTOR_PREFIX = "azents-selector"
_DISCORD_SELECTOR_ACTION_OPEN = "open"
_DISCORD_SELECTOR_ACTION_SELECT = "select"
_DISCORD_SELECTOR_ACTION_PREVIOUS = "previous"
_DISCORD_SELECTOR_ACTION_NEXT = "next"
_DISCORD_SELECTOR_PAGE_SIZE = 20


@dataclass(frozen=True)
class DiscordSelectorScope:
    """A verified compact selector scope carried only in one component ID."""

    selector_interaction_id: str
    action: str
    offset: int


@dataclass(frozen=True)
class DiscordSelectorComponentResponse:
    """One transient component response plus an optional durable control delivery."""

    response: dict[str, object]
    control_delivery_attempt_id: str | None
    connection_id: str | None


@dataclass
class DiscordSelectorResponseService:
    """Render bounded Discord components from one durable selector admission."""

    selector_service: Annotated[
        ExternalChannelSelectorService,
        Depends(ExternalChannelSelectorService),
    ]
    config: Annotated[Config, Depends(get_config)]
    provider_control: Annotated[
        ExternalChannelProviderControlService,
        Depends(get_external_channel_provider_control_service),
    ]
    ingestion_replay_service: Annotated[
        ExternalChannelIngestionReplayService,
        Depends(ExternalChannelIngestionReplayService),
    ]

    async def initial_response(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        now: datetime.datetime,
    ) -> dict[str, object]:
        """Render the initial ephemeral selector after its durable claim commits."""
        catalog = await self.selector_service.project_catalog(
            selector_interaction_id=selector_interaction_id,
            principal_id=principal_id,
            search=None,
            offset=0,
            now=now,
        )
        return {
            "type": 4,
            "data": {
                "flags": 64,
                "content": "Select an Agent for this conversation.",
                "embeds": _selector_embeds(
                    title="Select an Agent",
                    description=(
                        "Choose the Agent that should continue this conversation."
                    ),
                    color=0x5865F2,
                ),
                "components": _selector_components(
                    catalog=catalog,
                    selector_interaction_id=selector_interaction_id,
                    secret=self.config.auth.jwt.secret_key,
                    offset=0,
                ),
            },
        }

    async def component_response(
        self,
        *,
        custom_id: str,
        selected_route_id: str | None,
        principal_id: str,
        guild_id: str | None,
        channel_id: str | None,
        now: datetime.datetime,
    ) -> DiscordSelectorComponentResponse:
        """Revalidate one component action against its current durable admission."""
        scope = parse_discord_selector_custom_id(
            custom_id=custom_id,
            secret=self.config.auth.jwt.secret_key,
        )
        await self.selector_service.validate_discord_component_scope(
            selector_interaction_id=scope.selector_interaction_id,
            principal_id=principal_id,
            guild_id=guild_id,
            channel_id=channel_id,
            now=now,
        )
        if scope.action == _DISCORD_SELECTOR_ACTION_OPEN:
            return DiscordSelectorComponentResponse(
                response=await self.initial_response(
                    selector_interaction_id=scope.selector_interaction_id,
                    principal_id=principal_id,
                    now=now,
                ),
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        if scope.action in {
            _DISCORD_SELECTOR_ACTION_PREVIOUS,
            _DISCORD_SELECTOR_ACTION_NEXT,
        }:
            catalog = await self.selector_service.project_catalog(
                selector_interaction_id=scope.selector_interaction_id,
                principal_id=principal_id,
                search=None,
                offset=scope.offset,
                now=now,
            )
            return DiscordSelectorComponentResponse(
                response={
                    "type": 7,
                    "data": {
                        "content": "Select an Agent for this conversation.",
                        "embeds": _selector_embeds(
                            title="Select an Agent",
                            description=(
                                "Choose the Agent that should continue this "
                                "conversation."
                            ),
                            color=0x5865F2,
                        ),
                        "components": _selector_components(
                            catalog=catalog,
                            selector_interaction_id=scope.selector_interaction_id,
                            secret=self.config.auth.jwt.secret_key,
                            offset=scope.offset,
                        ),
                    },
                },
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        if scope.action != _DISCORD_SELECTOR_ACTION_SELECT or selected_route_id is None:
            raise ValueError("Discord selector submission is invalid.")
        selection = await self.selector_service.select_route(
            selector_interaction_id=scope.selector_interaction_id,
            principal_id=principal_id,
            route_id=selected_route_id,
            now=now,
        )
        if selection.status == "expired":
            content = "This Agent selection has expired. Start a new conversation."
            title = "Agent selection expired"
            color = 0x99AAB5
            control_delivery_attempt_id = None
            connection_id = None
        elif selection.status == "already_bound":
            content = "This conversation is already linked to an Agent."
            title = "Conversation already linked"
            color = 0xFEE75C
            control_delivery_attempt_id = None
            connection_id = None
        else:
            outcome = await self.ingestion_replay_service.replay_selected_interaction(
                selector_interaction_id=selection.selector_interaction.id,
                principal_id=principal_id,
                deadline=external_channel_replay_deadline(now=now),
            )
            match outcome.kind:
                case (
                    ExternalChannelIngestionOutcomeKind.ACCEPTED
                    | ExternalChannelIngestionOutcomeKind.DUPLICATE
                ):
                    awaiting_access = False
                    control_delivery_attempt_id = None
                    connection_id = None
                case ExternalChannelIngestionOutcomeKind.AWAITING_ACCESS:
                    awaiting_access = True
                    control_delivery_attempt_id = outcome.control_delivery_attempt_id
                    connection_id = outcome.connection_id
                case (
                    ExternalChannelIngestionOutcomeKind.AWAITING_SELECTION
                    | ExternalChannelIngestionOutcomeKind.IGNORED
                    | ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
                    | ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION
                ):
                    raise RuntimeError(
                        "Discord selector ingestion could not be completed."
                    )
                case _ as unreachable:
                    assert_never(unreachable)
            content = (
                "Access approval is required before this Agent can continue."
                if awaiting_access
                else "Agent selected. Continuing this conversation."
            )
            title = "Access approval required" if awaiting_access else "Agent selected"
            color = 0xFEE75C if awaiting_access else 0x57F287
        return DiscordSelectorComponentResponse(
            response={
                "type": 7,
                "data": {
                    "content": content,
                    "embeds": _selector_embeds(
                        title=title,
                        description=content,
                        color=color,
                    ),
                    "components": [],
                },
            },
            control_delivery_attempt_id=control_delivery_attempt_id,
            connection_id=connection_id,
        )

    async def attempt_control_delivery(
        self,
        *,
        connection_id: str,
        delivery_attempt_id: str,
    ) -> None:
        """Attempt one committed access control only after the interaction response."""
        del connection_id
        await self.provider_control.attempt_delivery(delivery_attempt_id)


def parse_discord_selector_custom_id(
    *,
    custom_id: str,
    secret: str,
) -> DiscordSelectorScope:
    """Verify one compact component scope before loading durable selector owners."""
    try:
        (
            prefix,
            action,
            selector_interaction_id,
            raw_offset,
            signature,
        ) = custom_id.split(":", 4)
    except ValueError as error:
        raise ValueError("Discord selector scope is invalid.") from error
    if prefix != _DISCORD_SELECTOR_PREFIX:
        raise ValueError("Discord selector scope is invalid.")
    if action not in {
        _DISCORD_SELECTOR_ACTION_OPEN,
        _DISCORD_SELECTOR_ACTION_SELECT,
        _DISCORD_SELECTOR_ACTION_PREVIOUS,
        _DISCORD_SELECTOR_ACTION_NEXT,
    }:
        raise ValueError("Discord selector scope is invalid.")
    if not selector_interaction_id or len(selector_interaction_id) > 64:
        raise ValueError("Discord selector scope is invalid.")
    try:
        offset = int(raw_offset)
    except ValueError as error:
        raise ValueError("Discord selector scope is invalid.") from error
    if offset < 0:
        raise ValueError("Discord selector scope is invalid.")
    expected = build_discord_selector_custom_id(
        secret=secret,
        selector_interaction_id=selector_interaction_id,
        action=action,
        offset=offset,
    ).rsplit(":", 1)[-1]
    if not signature or not hmac.compare_digest(signature, expected):
        raise ValueError("Discord selector scope is invalid.")
    return DiscordSelectorScope(
        selector_interaction_id=selector_interaction_id,
        action=action,
        offset=offset,
    )


def _selector_components(
    *,
    catalog: ExternalChannelSelectorCatalog,
    selector_interaction_id: str,
    secret: str,
    offset: int,
) -> list[dict[str, object]]:
    """Render a bounded page without embedding provider tokens or source content."""
    components: list[dict[str, object]] = []
    if catalog.candidates:
        components.append(
            {
                "type": 1,
                "components": [
                    {
                        "type": 3,
                        "custom_id": build_discord_selector_custom_id(
                            secret=secret,
                            selector_interaction_id=selector_interaction_id,
                            action=_DISCORD_SELECTOR_ACTION_SELECT,
                            offset=offset,
                        ),
                        "placeholder": "Choose an Agent",
                        "min_values": 1,
                        "max_values": 1,
                        "options": [
                            {
                                "label": _candidate_label(
                                    candidate.agent_name,
                                    candidate.access,
                                ),
                                "description": (
                                    "Available immediately"
                                    if candidate.access == "available"
                                    else "Access approval required"
                                ),
                                "value": candidate.route_id,
                            }
                            for candidate in catalog.candidates
                        ],
                    }
                ],
            }
        )
    else:
        components.append(
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 2,
                        "label": "No Agents available",
                        "custom_id": "azents-selector-unavailable",
                        "disabled": True,
                    }
                ],
            }
        )
    navigation: list[dict[str, object]] = []
    if offset > 0:
        navigation.append(
            {
                "type": 2,
                "style": 2,
                "label": "Previous",
                "custom_id": build_discord_selector_custom_id(
                    secret=secret,
                    selector_interaction_id=selector_interaction_id,
                    action=_DISCORD_SELECTOR_ACTION_PREVIOUS,
                    offset=max(0, offset - _DISCORD_SELECTOR_PAGE_SIZE),
                ),
            }
        )
    if catalog.next_offset is not None:
        navigation.append(
            {
                "type": 2,
                "style": 2,
                "label": "Next",
                "custom_id": build_discord_selector_custom_id(
                    secret=secret,
                    selector_interaction_id=selector_interaction_id,
                    action=_DISCORD_SELECTOR_ACTION_NEXT,
                    offset=catalog.next_offset,
                ),
            }
        )
    if navigation:
        components.append({"type": 1, "components": navigation})
    return components


def _candidate_label(agent_name: str, access: str) -> str:
    suffix = "" if access == "available" else " — Access required"
    return (agent_name + suffix)[:100]


def _selector_embeds(
    *,
    title: str,
    description: str,
    color: int,
) -> list[dict[str, object]]:
    """Return one fixed-size Discord Embed for selector interaction feedback."""
    return [{"title": title, "description": description, "color": color}]
