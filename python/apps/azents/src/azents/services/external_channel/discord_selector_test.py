"""Discord-native selector response tests."""

import datetime
from types import SimpleNamespace
from typing import cast

import pytest

from azents.core.config import Config
from azents.repos.external_channel.data import ExternalChannelConversationAdmission
from azents.services.external_channel.discord_selector import (
    DiscordSelectorResponseService,
    build_discord_selector_custom_id,
    parse_discord_selector_custom_id,
)
from azents.services.external_channel.event_processor import (
    ExternalChannelEventProcessorService,
)
from azents.services.external_channel.selector import (
    ExternalChannelSelectorCandidate,
    ExternalChannelSelectorCatalog,
    ExternalChannelSelectorSelection,
    ExternalChannelSelectorService,
)

_NOW = datetime.datetime(2026, 7, 28, tzinfo=datetime.UTC)
_SECRET = "selector-test-secret"


class _SelectorDouble:
    """Record trusted catalog and selection calls only."""

    def __init__(self) -> None:
        self.catalog_calls: list[tuple[str, str, str | None, int]] = []
        self.selection_calls: list[tuple[str, str, str]] = []
        self.catalog = ExternalChannelSelectorCatalog(
            candidates=(
                ExternalChannelSelectorCandidate(
                    route_id="route-1",
                    agent_name="Agent One",
                    access="available",
                ),
            ),
            next_offset=20,
        )
        self.selection = ExternalChannelSelectorSelection(
            status="selected",
            admission=ExternalChannelConversationAdmission.model_construct(
                id="admission-1"
            ),
            binding=None,
        )

    async def project_catalog(
        self,
        *,
        admission_id: str,
        principal_id: str,
        search: str | None,
        offset: int,
        now: datetime.datetime,
    ) -> ExternalChannelSelectorCatalog:
        assert now == _NOW
        self.catalog_calls.append((admission_id, principal_id, search, offset))
        return self.catalog

    async def validate_discord_component_scope(
        self,
        *,
        admission_id: str,
        principal_id: str,
        guild_id: str | None,
        channel_id: str | None,
        now: datetime.datetime,
    ) -> None:
        assert (admission_id, principal_id, guild_id, channel_id, now) == (
            "admission-1",
            "principal-1",
            "guild-1",
            "channel-1",
            _NOW,
        )

    async def select_route(
        self,
        *,
        admission_id: str,
        principal_id: str,
        route_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelSelectorSelection:
        assert now == _NOW
        self.selection_calls.append((admission_id, principal_id, route_id))
        return self.selection


class _EventProcessorDouble:
    """Record only the durable post-selection continuation call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, datetime.datetime]] = []

    async def continue_selected_admission(
        self,
        *,
        admission_id: str,
        principal_id: str,
        now: datetime.datetime,
    ) -> object:
        self.calls.append((admission_id, principal_id, now))
        return SimpleNamespace(status="bound", control_delivery_attempt_id=None)


def _service(
    selector: _SelectorDouble,
    event_processor: _EventProcessorDouble,
) -> DiscordSelectorResponseService:
    """Build the response service with only redacted local selector state."""
    config = SimpleNamespace(
        auth=SimpleNamespace(
            jwt=SimpleNamespace(secret_key=_SECRET),
        )
    )
    return DiscordSelectorResponseService(
        selector_service=cast(ExternalChannelSelectorService, selector),
        config=cast(Config, config),
        event_processor=cast(ExternalChannelEventProcessorService, event_processor),
    )


def test_signed_component_scope_round_trips_and_rejects_tampering() -> None:
    """Compact Discord IDs fit the provider bound and fail closed when altered."""
    custom_id = build_discord_selector_custom_id(
        secret=_SECRET,
        admission_id="admission-1",
        action="next",
        offset=20,
    )

    scope = parse_discord_selector_custom_id(custom_id=custom_id, secret=_SECRET)

    assert len(custom_id) <= 100
    assert scope.admission_id == "admission-1"
    assert scope.action == "next"
    assert scope.offset == 20
    with pytest.raises(ValueError, match="scope is invalid"):
        parse_discord_selector_custom_id(
            custom_id=custom_id.replace("20", "21", 1),
            secret=_SECRET,
        )


@pytest.mark.asyncio
async def test_initial_response_renders_bounded_selector_and_next_scope() -> None:
    """The initial ephemeral response exposes only route IDs and policy labels."""
    selector = _SelectorDouble()
    event_processor = _EventProcessorDouble()

    response = await _service(selector, event_processor).initial_response(
        admission_id="admission-1",
        principal_id="principal-1",
        now=_NOW,
    )

    assert selector.catalog_calls == [("admission-1", "principal-1", None, 0)]
    assert response["type"] == 4
    data = cast(dict[str, object], response["data"])
    assert data["flags"] == 64
    rows = cast(list[dict[str, object]], data["components"])
    select = cast(dict[str, object], cast(list[object], rows[0]["components"])[0])
    option = cast(dict[str, object], cast(list[object], select["options"])[0])
    assert option == {
        "label": "Agent One",
        "description": "Available immediately",
        "value": "route-1",
    }
    next_button = cast(dict[str, object], cast(list[object], rows[1]["components"])[0])
    next_scope = parse_discord_selector_custom_id(
        custom_id=cast(str, next_button["custom_id"]),
        secret=_SECRET,
    )
    assert next_scope.action == "next"
    assert next_scope.offset == 20


@pytest.mark.asyncio
async def test_component_next_requeries_signed_offset() -> None:
    """Pagination uses the HMAC-bound offset rather than provider-supplied state."""
    selector = _SelectorDouble()
    selector.catalog = ExternalChannelSelectorCatalog(candidates=(), next_offset=None)
    event_processor = _EventProcessorDouble()
    custom_id = build_discord_selector_custom_id(
        secret=_SECRET,
        admission_id="admission-1",
        action="next",
        offset=20,
    )

    response = await _service(selector, event_processor).component_response(
        custom_id=custom_id,
        selected_route_id=None,
        principal_id="principal-1",
        guild_id="guild-1",
        channel_id="channel-1",
        now=_NOW,
    )

    assert selector.catalog_calls == [("admission-1", "principal-1", None, 20)]
    assert response.response["type"] == 7
    assert response.control_delivery_attempt_id is None
    assert response.connection_id is None
    assert event_processor.calls == []


@pytest.mark.asyncio
async def test_component_selection_continues_durable_admission_once() -> None:
    """A signed route choice delegates immutable selection and continuation once."""
    selector = _SelectorDouble()
    event_processor = _EventProcessorDouble()
    custom_id = build_discord_selector_custom_id(
        secret=_SECRET,
        admission_id="admission-1",
        action="select",
    )

    response = await _service(selector, event_processor).component_response(
        custom_id=custom_id,
        selected_route_id="route-1",
        principal_id="principal-1",
        guild_id="guild-1",
        channel_id="channel-1",
        now=_NOW,
    )

    assert selector.selection_calls == [("admission-1", "principal-1", "route-1")]
    assert event_processor.calls == [("admission-1", "principal-1", _NOW)]
    assert response.response == {
        "type": 7,
        "data": {
            "content": "Agent selected. Continuing this conversation.",
            "embeds": [
                {
                    "title": "Agent selected",
                    "description": "Agent selected. Continuing this conversation.",
                    "color": 0x57F287,
                }
            ],
            "components": [],
        },
    }
    assert response.control_delivery_attempt_id is None
    assert response.connection_id is None
