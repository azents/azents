"""Discord-native selector response tests."""

import datetime
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from azents.core.config import Config, Settings
from azents.core.enums import (
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelTransport,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.external_channel_selection import (
    ExternalChannelSelectorCandidate,
    ExternalChannelSelectorCatalog,
    ExternalChannelSelectorSelection,
)
from azents.repos.external_channel.data import ExternalChannelInteraction
from azents.services.external_channel.discord_selector import (
    DiscordSelectorResponseService,
    build_discord_selector_custom_id,
    parse_discord_selector_custom_id,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
)
from azents.services.external_channel.selector import ExternalChannelSelectorService
from azents.testing.external_channel import make_provider_effect_plan

_NOW = datetime.datetime(2026, 7, 28, tzinfo=datetime.UTC)
_SECRET = "selector-test-secret"


def _interaction() -> ExternalChannelInteraction:
    """Create the complete admitted selector record used by the typed fake."""
    return ExternalChannelInteraction(
        id="admission-1",
        connection_id="connection-1",
        transport=ExternalChannelTransport.HTTP,
        provider_interaction_key="discord:interaction-1",
        interaction_type=ExternalChannelInteractionType.BLOCK_ACTION,
        callback_id=None,
        action_id=None,
        principal_id="principal-1",
        setup_claim_id=None,
        resource_correlation_key=None,
        projection={},
        status=ExternalChannelInteractionStatus.PROCESSING,
        expires_at=_NOW + datetime.timedelta(minutes=20),
        error_kind=None,
        error_summary=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _SelectorOption(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str
    description: str
    value: str


class _SelectorMenu(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal[3]
    custom_id: str
    placeholder: str
    min_values: int
    max_values: int
    options: list[_SelectorOption]


class _SelectorButton(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal[2]
    custom_id: str
    label: str
    style: int


class _SelectorRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal[1]
    components: list[
        Annotated[_SelectorMenu | _SelectorButton, Field(discriminator="type")]
    ]


class _InitialSelectorData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    flags: int
    content: str
    embeds: list[dict[str, object]]
    components: list[_SelectorRow]


class _InitialSelectorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal[4]
    data: _InitialSelectorData


class _SelectorDouble(ExternalChannelSelectorService):
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
            selector_interaction=_interaction(),
            binding=None,
        )

    async def project_catalog(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        search: str | None,
        offset: int,
        now: datetime.datetime,
    ) -> ExternalChannelSelectorCatalog:
        assert now == _NOW
        self.catalog_calls.append(
            (selector_interaction_id, principal_id, search, offset)
        )
        return self.catalog

    async def validate_discord_component_scope(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        guild_id: str | None,
        channel_id: str | None,
        now: datetime.datetime,
    ) -> None:
        assert (selector_interaction_id, principal_id, guild_id, channel_id, now) == (
            "admission-1",
            "principal-1",
            "guild-1",
            "channel-1",
            _NOW,
        )

    async def select_route(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        route_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelSelectorSelection:
        assert now == _NOW
        self.selection_calls.append((selector_interaction_id, principal_id, route_id))
        return self.selection


class _ProviderControlDouble(ExternalChannelProviderControlService):
    def __init__(self) -> None:
        self.calls: list[ProviderEffectPlan] = []

    async def attempt(self, plan: ProviderEffectPlan) -> None:
        self.calls.append(plan)


class _ReplayDouble(ExternalChannelIngestionReplayService):
    def __init__(
        self,
        outcome: ExternalChannelIngestionOutcome | None = None,
    ) -> None:
        self.outcome = outcome or ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
            reason=ExternalChannelIngestionReason.ACCEPTED,
            mailbox_item_id=None,
            control_plans=(),
            connection_id=None,
        )
        self.calls: list[tuple[str, str]] = []

    async def replay_selected_interaction(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        deadline: object,
    ) -> ExternalChannelIngestionOutcome:
        del deadline
        self.calls.append((selector_interaction_id, principal_id))
        return self.outcome


def _service(
    selector: _SelectorDouble,
    replay: _ReplayDouble | None = None,
    provider_control: _ProviderControlDouble | None = None,
) -> DiscordSelectorResponseService:
    """Build the response service with only redacted local selector state."""
    config = Config.from_settings(
        Settings(
            _env_file=None,
            rdb_host="unused",
            rdb_user="unused",
            rdb_db_name="unused",
            auth_jwt_secret_key=_SECRET,
            credential_encryption_key="unused",
        )
    )
    return DiscordSelectorResponseService(
        selector_service=selector,
        config=config,
        provider_control=provider_control or _ProviderControlDouble(),
        ingestion_replay_service=replay or _ReplayDouble(),
    )


def test_signed_component_scope_round_trips_and_rejects_tampering() -> None:
    """Compact Discord IDs fit the provider bound and fail closed when altered."""
    custom_id = build_discord_selector_custom_id(
        secret=_SECRET,
        selector_interaction_id="admission-1",
        action="next",
        offset=20,
    )

    scope = parse_discord_selector_custom_id(custom_id=custom_id, secret=_SECRET)

    assert len(custom_id) <= 100
    assert scope.selector_interaction_id == "admission-1"
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

    response = await _service(selector).initial_response(
        selector_interaction_id="admission-1",
        principal_id="principal-1",
        now=_NOW,
    )

    assert selector.catalog_calls == [("admission-1", "principal-1", None, 0)]
    assert response["type"] == 4
    data = _InitialSelectorResponse.model_validate(response).data
    assert data.flags == 64
    rows = data.components
    select = rows[0].components[0]
    assert isinstance(select, _SelectorMenu)
    option = select.options[0]
    assert option.model_dump() == {
        "label": "Agent One",
        "description": "Available immediately",
        "value": "route-1",
    }
    next_button = rows[1].components[0]
    assert isinstance(next_button, _SelectorButton)
    next_scope = parse_discord_selector_custom_id(
        custom_id=next_button.custom_id,
        secret=_SECRET,
    )
    assert next_scope.action == "next"
    assert next_scope.offset == 20


@pytest.mark.asyncio
async def test_component_next_requeries_signed_offset() -> None:
    """Pagination uses the HMAC-bound offset rather than provider-supplied state."""
    selector = _SelectorDouble()
    selector.catalog = ExternalChannelSelectorCatalog(candidates=(), next_offset=None)
    custom_id = build_discord_selector_custom_id(
        secret=_SECRET,
        selector_interaction_id="admission-1",
        action="next",
        offset=20,
    )

    response = await _service(selector).component_response(
        custom_id=custom_id,
        selected_route_id=None,
        principal_id="principal-1",
        guild_id="guild-1",
        channel_id="channel-1",
        now=_NOW,
    )

    assert selector.catalog_calls == [("admission-1", "principal-1", None, 20)]
    assert response.response["type"] == 7
    assert response.control_plan is None
    assert response.connection_id is None


@pytest.mark.asyncio
async def test_typed_component_selection_replays_shared_ingestion() -> None:
    """A typed Discord selection returns the shared access-control identity."""
    plan = make_provider_effect_plan("discord-selector")
    selector = _SelectorDouble()
    selector.selection = ExternalChannelSelectorSelection(
        status="selected",
        selector_interaction=_interaction(),
        binding=None,
    )
    replay = _ReplayDouble(
        ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.AWAITING_ACCESS,
            reason=ExternalChannelIngestionReason.ACCESS_REQUIRED,
            mailbox_item_id=None,
            control_plans=(plan,),
            connection_id="connection-1",
        )
    )
    custom_id = build_discord_selector_custom_id(
        secret=_SECRET,
        selector_interaction_id="admission-1",
        action="select",
    )

    response = await _service(
        selector,
        replay,
    ).component_response(
        custom_id=custom_id,
        selected_route_id="route-1",
        principal_id="principal-1",
        guild_id="guild-1",
        channel_id="channel-1",
        now=_NOW,
    )

    assert replay.calls == [("admission-1", "principal-1")]
    assert response.control_plan == plan
    assert response.connection_id == "connection-1"
    assert response.response["type"] == 7


@pytest.mark.asyncio
async def test_component_selection_replays_durable_admission_once() -> None:
    """A signed route choice replays the immutable selected admission once."""
    selector = _SelectorDouble()
    replay = _ReplayDouble()
    custom_id = build_discord_selector_custom_id(
        secret=_SECRET,
        selector_interaction_id="admission-1",
        action="select",
    )

    response = await _service(selector, replay).component_response(
        custom_id=custom_id,
        selected_route_id="route-1",
        principal_id="principal-1",
        guild_id="guild-1",
        channel_id="channel-1",
        now=_NOW,
    )

    assert selector.selection_calls == [("admission-1", "principal-1", "route-1")]
    assert replay.calls == [("admission-1", "principal-1")]
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
    assert response.control_plan is None
    assert response.connection_id is None
