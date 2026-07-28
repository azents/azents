"""Discord-native rendering for durable External Channel Agent selection."""

import base64
import datetime
import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.services.external_channel.event_processor import (
    ExternalChannelEventProcessorService,
)
from azents.services.external_channel.selector import (
    ExternalChannelSelectorCatalog,
    ExternalChannelSelectorService,
)

_DISCORD_SELECTOR_PREFIX = "azents-selector"
_DISCORD_SELECTOR_ACTION_SELECT = "select"
_DISCORD_SELECTOR_ACTION_PREVIOUS = "previous"
_DISCORD_SELECTOR_ACTION_NEXT = "next"
_DISCORD_SELECTOR_TOKEN_SIGNATURE_BYTES = 16
_DISCORD_SELECTOR_PAGE_SIZE = 20


@dataclass(frozen=True)
class DiscordSelectorScope:
    """A verified compact selector scope carried only in one component ID."""

    admission_id: str
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
    event_processor: Annotated[
        ExternalChannelEventProcessorService,
        Depends(ExternalChannelEventProcessorService),
    ]

    async def initial_response(
        self,
        *,
        admission_id: str,
        principal_id: str,
        now: datetime.datetime,
    ) -> dict[str, object]:
        """Render the initial ephemeral selector after its durable claim commits."""
        catalog = await self.selector_service.project_catalog(
            admission_id=admission_id,
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
                "components": _selector_components(
                    catalog=catalog,
                    admission_id=admission_id,
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
        now: datetime.datetime,
    ) -> DiscordSelectorComponentResponse:
        """Revalidate one component action against its current durable admission."""
        scope = parse_discord_selector_custom_id(
            custom_id=custom_id,
            secret=self.config.auth.jwt.secret_key,
        )
        if scope.action in {
            _DISCORD_SELECTOR_ACTION_PREVIOUS,
            _DISCORD_SELECTOR_ACTION_NEXT,
        }:
            catalog = await self.selector_service.project_catalog(
                admission_id=scope.admission_id,
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
                        "components": _selector_components(
                            catalog=catalog,
                            admission_id=scope.admission_id,
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
            admission_id=scope.admission_id,
            principal_id=principal_id,
            route_id=selected_route_id,
            now=now,
        )
        if selection.status == "expired":
            content = "This Agent selection has expired. Start a new conversation."
            control_delivery_attempt_id = None
            connection_id = None
        elif selection.status == "already_bound":
            content = "This conversation is already linked to an Agent."
            control_delivery_attempt_id = None
            connection_id = None
        else:
            continuation = await self.event_processor.continue_selected_admission(
                admission_id=selection.admission.id,
                principal_id=principal_id,
                now=now,
            )
            content = (
                "Access approval is required before this Agent can continue."
                if continuation.status == "awaiting_access"
                else "Agent selected. Continuing this conversation."
            )
            control_delivery_attempt_id = continuation.control_delivery_attempt_id
            connection_id = (
                selection.admission.connection_id
                if control_delivery_attempt_id is not None
                else None
            )
        return DiscordSelectorComponentResponse(
            response={
                "type": 7,
                "data": {
                    "content": content,
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
        await self.event_processor.attempt_selected_admission_control_delivery(
            connection_id=connection_id,
            delivery_attempt_id=delivery_attempt_id,
        )


def build_discord_selector_custom_id(
    *,
    secret: str,
    admission_id: str,
    action: str,
    offset: int = 0,
) -> str:
    """Sign the compact admission scope that fits Discord's custom-ID bound."""
    if action not in {
        _DISCORD_SELECTOR_ACTION_SELECT,
        _DISCORD_SELECTOR_ACTION_PREVIOUS,
        _DISCORD_SELECTOR_ACTION_NEXT,
    }:
        raise ValueError("Discord selector action is invalid.")
    if not admission_id or len(admission_id) > 64:
        raise ValueError("Discord selector admission is invalid.")
    if offset < 0:
        raise ValueError("Discord selector offset is invalid.")
    payload = f"{action}:{admission_id}:{offset}".encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()[
        :_DISCORD_SELECTOR_TOKEN_SIGNATURE_BYTES
    ]
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return (
        f"{_DISCORD_SELECTOR_PREFIX}:{action}:{admission_id}:{offset}:"
        f"{encoded_signature}"
    )


def parse_discord_selector_custom_id(
    *,
    custom_id: str,
    secret: str,
) -> DiscordSelectorScope:
    """Verify one compact component scope before loading durable selector owners."""
    try:
        prefix, action, admission_id, raw_offset, signature = custom_id.split(":", 4)
    except ValueError as error:
        raise ValueError("Discord selector scope is invalid.") from error
    if prefix != _DISCORD_SELECTOR_PREFIX:
        raise ValueError("Discord selector scope is invalid.")
    if action not in {
        _DISCORD_SELECTOR_ACTION_SELECT,
        _DISCORD_SELECTOR_ACTION_PREVIOUS,
        _DISCORD_SELECTOR_ACTION_NEXT,
    }:
        raise ValueError("Discord selector scope is invalid.")
    if not admission_id or len(admission_id) > 64:
        raise ValueError("Discord selector scope is invalid.")
    try:
        offset = int(raw_offset)
    except ValueError as error:
        raise ValueError("Discord selector scope is invalid.") from error
    if offset < 0:
        raise ValueError("Discord selector scope is invalid.")
    payload = f"{action}:{admission_id}:{offset}".encode()
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()[
        :_DISCORD_SELECTOR_TOKEN_SIGNATURE_BYTES
    ]
    try:
        supplied = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    except ValueError as error:
        raise ValueError("Discord selector scope is invalid.") from error
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("Discord selector scope is invalid.")
    return DiscordSelectorScope(
        admission_id=admission_id,
        action=action,
        offset=offset,
    )


def _selector_components(
    *,
    catalog: ExternalChannelSelectorCatalog,
    admission_id: str,
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
                            admission_id=admission_id,
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
                    admission_id=admission_id,
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
                    admission_id=admission_id,
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
