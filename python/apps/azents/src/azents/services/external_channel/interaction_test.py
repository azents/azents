"""Slack selector modal-open interaction tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelInteraction,
    ExternalChannelParticipationSetting,
    ExternalChannelResource,
    ExternalChannelSetupClaim,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.scheduled_task.data import ScheduledTask
from azents.services.external_channel.credentials import (
    ExternalChannelCredentialsCodec,
)
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
)
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
    ExternalChannelInteractionProcessor,
    SlackInteractionTriggerExpired,
    build_selector_metadata,
    build_settings_metadata,
    verify_selector_metadata,
)
from azents.services.external_channel.participation import (
    ExternalChannelParticipationService,
    ExternalChannelParticipationSettings,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan
from azents.services.external_channel.selector import (
    ExternalChannelSelectorCandidate,
    ExternalChannelSelectorCatalog,
    ExternalChannelSelectorSelection,
    ExternalChannelSelectorService,
)
from azents.services.external_channel.selector_state import (
    ExternalChannelSelectorState,
    projection_with_selector_state,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackInteractionView,
    SlackInteractionViewResult,
)
from azents.services.scheduled_task.channel import ScheduledTaskChannelService
from azents.services.scheduled_task.control import (
    ScheduledTaskProviderControlResult,
    ScheduledTaskProviderControlService,
    build_scheduled_task_control_locator,
)
from azents.testing.external_channel import make_provider_effect_plan

_VALID_EXPIRY = datetime.datetime.max.replace(tzinfo=datetime.UTC)
_EXPIRED_AT = datetime.datetime.min.replace(tzinfo=datetime.UTC)
_SECRET = "selector-metadata-test-secret"


class _Session:
    async def commit(self) -> None:
        pass


class _Repository:
    def __init__(self) -> None:
        selector_state = ExternalChannelSelectorState(
            connection_id="connection-1",
            resource_id="resource-1",
            principal_id="principal-1",
            conversation_position_id="position-1",
            trigger_provider_message_key="slack:T-1:C-1:100.0001",
            range_start_position=None,
            trigger_position="100.0001",
            selected_route_id=None,
        )
        self.interaction = ExternalChannelInteraction.model_construct(
            id="interaction-1",
            connection_id="connection-1",
            principal_id="principal-1",
            resource_correlation_key="C-1:100.0001",
            interaction_type=ExternalChannelInteractionType.SHORTCUT,
            projection=projection_with_selector_state({}, selector_state),
            status=ExternalChannelInteractionStatus.PROCESSING,
            expires_at=_VALID_EXPIRY,
        )
        self.configuration = ExternalChannelConnectionConfiguration.model_construct(
            id="connection-1",
            status=ExternalChannelConnectionStatus.ACTIVE,
            app_mode=ExternalChannelAppMode.MULTI,
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="T-1",
            encrypted_credentials="ciphertext",
        )
        self.resource = ExternalChannelResource.model_construct(
            id="resource-1",
            connection_id="connection-1",
            provider_resource_key="slack:T-1:C-1:100.0001",
            status=ExternalChannelResourceStatus.ACTIVE,
        )
        self.selector = ExternalChannelInteraction.model_construct(
            id="admission-1",
            connection_id="connection-1",
            principal_id="principal-1",
            interaction_type=ExternalChannelInteractionType.MANAGEMENT_ACTION,
            projection=projection_with_selector_state({}, selector_state),
            status=ExternalChannelInteractionStatus.ACCEPTED,
            expires_at=_VALID_EXPIRY,
        )
        self.interactions = {
            self.interaction.id: self.interaction,
            self.selector.id: self.selector,
        }

    async def lock_interaction(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
    ) -> ExternalChannelInteraction | None:
        del session
        return self.interactions.get(interaction_id)

    async def get_connection_configuration(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        del session
        return self.configuration if connection_id == self.configuration.id else None

    async def get_resource_by_provider_key(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        resource_type: ExternalChannelResourceType,
        provider_resource_key: str,
    ) -> ExternalChannelResource | None:
        del session
        return (
            self.resource
            if (
                connection_id == self.resource.connection_id
                and resource_type is self.resource.resource_type
                and provider_resource_key == self.resource.provider_resource_key
            )
            else None
        )

    async def get_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelResource | None:
        del session
        return self.resource if resource_id == self.resource.id else None


class _Selector:
    def __init__(self, catalog: ExternalChannelSelectorCatalog) -> None:
        self.catalog = catalog
        self.calls: list[dict[str, object]] = []
        self.selection_calls: list[dict[str, object]] = []
        self.selection: ExternalChannelSelectorSelection | None = None

    async def project_catalog(self, **kwargs: object) -> ExternalChannelSelectorCatalog:
        self.calls.append(kwargs)
        return self.catalog

    async def select_route(
        self,
        **kwargs: object,
    ) -> ExternalChannelSelectorSelection:
        self.selection_calls.append(kwargs)
        assert self.selection is not None
        return self.selection


class _Credentials:
    def decrypt(self, value: str) -> SlackConnectionCredentials:
        assert value == "ciphertext"
        return SlackConnectionCredentials(
            bot_token="xoxb-secret",
            signing_secret="signing-secret",
            app_token=None,
        )


class _Slack:
    def __init__(self, result: SlackInteractionViewResult) -> None:
        self.result = result
        self.views: list[SlackInteractionView] = []
        self.triggers: list[str] = []
        self.update_calls: list[dict[str, object]] = []

    async def open_interaction_view(
        self,
        *,
        bot_token: str,
        trigger_id: str,
        view: SlackInteractionView,
    ) -> SlackInteractionViewResult:
        assert bot_token == "xoxb-secret"
        self.views.append(view)
        self.triggers.append(trigger_id)
        return self.result

    async def update_interaction_view(
        self,
        *,
        bot_token: str,
        view_id: str,
        view_hash: str | None,
        view: SlackInteractionView,
    ) -> SlackInteractionViewResult:
        assert bot_token == "xoxb-secret"
        self.views.append(view)
        self.update_calls.append(
            {
                "view_id": view_id,
                "view_hash": view_hash,
            }
        )
        return self.result


class _ProviderControl:
    def __init__(self) -> None:
        self.calls: list[ProviderEffectPlan] = []

    async def attempt(self, plan: ProviderEffectPlan) -> None:
        self.calls.append(plan)


class _Replay:
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
        self.calls: list[dict[str, object]] = []

    async def replay_selected_interaction(
        self,
        **kwargs: object,
    ) -> ExternalChannelIngestionOutcome:
        self.calls.append(kwargs)
        return self.outcome


def _processor(
    repository: _Repository,
    selector: _Selector,
    slack: _Slack,
    replay: _Replay | None = None,
    provider_control: _ProviderControl | None = None,
    participation: object | None = None,
    scheduled_task_control: object | None = None,
    scheduled_task_channel: object | None = None,
) -> ExternalChannelInteractionProcessor:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, _Session())

    return ExternalChannelInteractionProcessor(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
        selector_service=cast(ExternalChannelSelectorService, selector),
        credentials_codec=cast(ExternalChannelCredentialsCodec, _Credentials()),
        slack_client=cast(SlackConversationClient, slack),
        provider_control=cast(
            ExternalChannelProviderControlService,
            provider_control or _ProviderControl(),
        ),
        ingestion_replay_service=cast(
            ExternalChannelIngestionReplayService,
            replay or _Replay(),
        ),
        participation_service=cast(
            ExternalChannelParticipationService,
            participation or SimpleNamespace(),
        ),
        scheduled_task_control=cast(
            ScheduledTaskProviderControlService,
            scheduled_task_control or SimpleNamespace(),
        ),
        scheduled_task_channel=cast(
            ScheduledTaskChannelService,
            scheduled_task_channel or SimpleNamespace(),
        ),
        config=cast(
            Config,
            SimpleNamespace(
                auth=SimpleNamespace(jwt=SimpleNamespace(secret_key=_SECRET))
            ),
        ),
    )


def _catalog(*, empty: bool = False) -> ExternalChannelSelectorCatalog:
    return ExternalChannelSelectorCatalog(
        candidates=(
            ()
            if empty
            else (
                ExternalChannelSelectorCandidate(
                    route_id="route-alpha",
                    agent_name="Alpha",
                    access="available",
                ),
                ExternalChannelSelectorCandidate(
                    route_id="route-zed",
                    agent_name="Zed",
                    access="access_required",
                ),
            )
        ),
        next_offset=20 if not empty else None,
    )


def _handoff(
    *, selector_interaction_id: str | None = None
) -> ExternalChannelInteractionHandoff:
    return ExternalChannelInteractionHandoff(
        interaction_id="interaction-1",
        handler="selector_open",
        provider_parent_channel_id=None,
        provider_thread_key=None,
        settings_metadata=None,
        settings_location=None,
        settings_response_mode=None,
        trigger_id="trigger-secret-must-not-persist",
        selector_interaction_id=selector_interaction_id,
    )


@pytest.mark.asyncio
async def test_scheduled_task_delete_notifies_bound_slack_channel() -> None:
    """Slack provider cancellation publishes the committed deleted Task snapshot."""
    repository = _Repository()
    slack = _Slack(
        SlackInteractionViewResult(
            status="opened",
            error_kind=None,
            error_summary=None,
        )
    )
    task = cast(ScheduledTask, SimpleNamespace(id="task-1", binding_id="binding-1"))
    scheduled_task_control = SimpleNamespace(
        mutate=AsyncMock(
            return_value=ScheduledTaskProviderControlResult(
                action="delete",
                task=task,
            )
        )
    )
    scheduled_task_channel = SimpleNamespace(execute_deletion=AsyncMock())
    handoff = ExternalChannelInteractionHandoff(
        interaction_id="interaction-1",
        handler="scheduled_task_delete",
        provider_parent_channel_id="C-1",
        provider_thread_key="100.0001",
        settings_metadata=None,
        settings_location=None,
        settings_response_mode=None,
        trigger_id="trigger-secret-must-not-persist",
        scheduled_task_locator=build_scheduled_task_control_locator(
            secret=_SECRET,
            action="delete",
            task_id="task-1",
            binding_id="binding-1",
        ),
    )

    await _processor(
        repository,
        _Selector(_catalog()),
        slack,
        scheduled_task_control=scheduled_task_control,
        scheduled_task_channel=scheduled_task_channel,
    ).process(handoff)

    scheduled_task_channel.execute_deletion.assert_awaited_once_with(task)
    assert len(slack.views) == 1
    assert "Scheduled Task cancelled." in str(slack.views[0])


@pytest.mark.asyncio
async def test_settings_submission_revalidates_distinct_origin_interaction() -> None:
    """Accept a view submission only through its signed settings-open origin."""
    repository = _Repository()
    origin = repository.interaction.model_copy(
        update={"status": ExternalChannelInteractionStatus.COMPLETED}
    )
    submission = repository.interaction.model_copy(
        update={
            "id": "submission-1",
            "interaction_type": ExternalChannelInteractionType.VIEW_SUBMISSION,
        }
    )
    repository.interactions = {
        origin.id: origin,
        submission.id: submission,
    }
    claim = ExternalChannelSetupClaim.model_construct(
        id="claim-1",
        claim_generation=1,
        source_revision=1,
    )
    setup_settings = ExternalChannelParticipationSettings(
        target="setup",
        agent_name="Research Agent",
        setting=None,
        claim=claim,
        resource=None,
        binding=None,
    )
    committed_settings = ExternalChannelParticipationSettings(
        target="parent",
        agent_name="Research Agent",
        setting=ExternalChannelParticipationSetting.model_construct(
            id="setting-1",
            location=ExternalChannelConversationLocation.THREADS,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
        ),
        claim=None,
        resource=None,
        binding=None,
    )
    participation = SimpleNamespace(
        select_location=AsyncMock(),
        resolve_settings=AsyncMock(return_value=committed_settings),
    )
    metadata = build_settings_metadata(
        secret=_SECRET,
        settings=setup_settings,
        connection_id="connection-1",
        provider_parent_channel_id="C-1",
        principal_id="principal-1",
        interaction_id=origin.id,
    )

    await _processor(
        repository,
        _Selector(_catalog()),
        _Slack(
            SlackInteractionViewResult(
                status="opened",
                error_kind=None,
                error_summary=None,
            )
        ),
        participation=participation,
    ).process(
        ExternalChannelInteractionHandoff(
            interaction_id=submission.id,
            handler="settings_submission",
            provider_parent_channel_id=None,
            provider_thread_key=None,
            settings_metadata=metadata,
            settings_location=ExternalChannelConversationLocation.THREADS,
            settings_response_mode=None,
            trigger_id=None,
        )
    )

    participation.select_location.assert_awaited_once()
    assert (
        participation.select_location.await_args.kwargs["configured_by_principal_id"]
        == "principal-1"
    )


@pytest.mark.asyncio
async def test_shortcut_modal_is_deterministic_and_secret_free() -> None:
    repository = _Repository()
    selector = _Selector(_catalog())
    slack = _Slack(
        SlackInteractionViewResult(
            status="opened",
            error_kind=None,
            error_summary=None,
        )
    )
    handoff = _handoff()

    await _processor(repository, selector, slack).process(handoff)

    assert len(selector.calls) == 1
    assert selector.calls[0]["selector_interaction_id"] == "interaction-1"
    assert selector.calls[0]["principal_id"] == "principal-1"
    assert selector.calls[0]["search"] is None
    assert selector.calls[0]["offset"] == 0
    assert isinstance(selector.calls[0]["now"], datetime.datetime)
    view = slack.views[0]
    route_block = view.blocks[1]
    element = cast(dict[str, object], route_block["element"])
    assert element["options"] == [
        {
            "text": {"type": "plain_text", "text": "Alpha"},
            "value": "route-alpha",
        },
        {
            "text": {
                "type": "plain_text",
                "text": "Zed — Access required",
            },
            "value": "route-zed",
        },
    ]
    assert "trigger-secret" not in repr(handoff)
    assert "trigger-secret" not in repr(view)
    assert "xoxb-secret" not in repr(view)
    assert "azents_agent_selector_next" in repr(view.blocks)


@pytest.mark.asyncio
async def test_block_action_rejects_cross_scope_admission_before_provider_io() -> None:
    repository = _Repository()
    selector = _Selector(_catalog())
    slack = _Slack(
        SlackInteractionViewResult(
            status="opened",
            error_kind=None,
            error_summary=None,
        )
    )
    foreign_state = ExternalChannelSelectorState(
        connection_id="connection-1",
        resource_id="foreign-resource",
        principal_id="principal-1",
        conversation_position_id="position-1",
        trigger_provider_message_key="slack:T-1:C-1:100.0001",
        range_start_position=None,
        trigger_position="100.0001",
        selected_route_id=None,
    )
    repository.selector = repository.selector.model_copy(
        update={"projection": projection_with_selector_state({}, foreign_state)}
    )
    repository.interactions[repository.selector.id] = repository.selector

    with pytest.raises(ValueError, match="interaction is unavailable"):
        await _processor(repository, selector, slack).process(
            _handoff(selector_interaction_id="admission-1")
        )

    assert selector.calls == []
    assert slack.views == []


@pytest.mark.asyncio
async def test_empty_catalog_opens_explicit_safe_state() -> None:
    repository = _Repository()
    selector = _Selector(_catalog(empty=True))
    slack = _Slack(
        SlackInteractionViewResult(
            status="opened",
            error_kind=None,
            error_summary=None,
        )
    )

    await _processor(repository, selector, slack).process(_handoff())

    view = slack.views[0]
    assert view.submit_title is None
    assert view.blocks[0]["block_id"] == "azents_agent_selector_search"
    assert view.blocks[1] == {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "No eligible Agents are available on this page.",
        },
    }
    assert view.blocks[2]["type"] == "actions"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "exception"),
    [
        ("expired", SlackInteractionTriggerExpired),
        ("rejected", RuntimeError),
        ("unknown", RuntimeError),
    ],
)
async def test_provider_modal_outcomes_are_safe(
    status: str,
    exception: type[Exception],
) -> None:
    repository = _Repository()
    selector = _Selector(_catalog())
    slack = _Slack(
        SlackInteractionViewResult(
            status=cast(
                Literal[
                    "opened",
                    "updated",
                    "expired",
                    "conflict",
                    "rejected",
                    "unknown",
                ],
                status,
            ),
            error_kind="provider_result",
            error_summary="provider detail must not escape",
        )
    )

    with pytest.raises(exception):
        await _processor(repository, selector, slack).process(_handoff())

    assert slack.triggers == ["trigger-secret-must-not-persist"]


def test_selector_metadata_rejects_tampering_and_cross_scope() -> None:
    metadata = build_selector_metadata(
        secret=_SECRET,
        connection_id="connection-1",
        resource_id="resource-1",
        selector_interaction_id="admission-1",
        interaction_id="interaction-1",
        principal_id="principal-1",
        offset=20,
    )

    assert (
        verify_selector_metadata(
            metadata=metadata,
            secret=_SECRET,
            connection_id="connection-1",
            resource_id="resource-1",
            selector_interaction_id="admission-1",
            interaction_id="interaction-1",
            principal_id="principal-1",
        )
        == 20
    )
    with pytest.raises(ValueError):
        verify_selector_metadata(
            metadata=metadata[:-1] + ("A" if metadata[-1] != "A" else "B"),
            secret=_SECRET,
            connection_id="connection-1",
            resource_id="resource-1",
            selector_interaction_id="admission-1",
            interaction_id="interaction-1",
            principal_id="principal-1",
        )
    with pytest.raises(ValueError, match="scope"):
        verify_selector_metadata(
            metadata=metadata,
            secret=_SECRET,
            connection_id="connection-1",
            resource_id="foreign-resource",
            selector_interaction_id="admission-1",
            interaction_id="interaction-1",
            principal_id="principal-1",
        )


@pytest.mark.asyncio
async def test_navigation_requeries_search_page_and_updates_current_modal() -> None:
    repository = _Repository()
    repository.interactions["interaction-2"] = (
        ExternalChannelInteraction.model_construct(
            id="interaction-2",
            connection_id="connection-1",
            principal_id="principal-1",
            resource_correlation_key=None,
            interaction_type=ExternalChannelInteractionType.BLOCK_ACTION,
            status=ExternalChannelInteractionStatus.PROCESSING,
        )
    )
    selector = _Selector(_catalog())
    slack = _Slack(
        SlackInteractionViewResult(
            status="updated",
            error_kind=None,
            error_summary=None,
        )
    )
    metadata = build_selector_metadata(
        secret=_SECRET,
        connection_id="connection-1",
        resource_id="resource-1",
        selector_interaction_id="admission-1",
        interaction_id="interaction-1",
        principal_id="principal-1",
        offset=0,
    )

    await _processor(repository, selector, slack).process(
        ExternalChannelInteractionHandoff(
            interaction_id="interaction-2",
            handler="selector_navigation",
            provider_parent_channel_id=None,
            provider_thread_key=None,
            settings_metadata=None,
            settings_location=None,
            settings_response_mode=None,
            selector_metadata=metadata,
            selector_navigation="next",
            selector_search="ops",
            selector_view_id="V-1",
            selector_view_hash="hash-1",
        )
    )

    assert len(selector.calls) == 1
    assert selector.calls[0]["selector_interaction_id"] == "admission-1"
    assert selector.calls[0]["principal_id"] == "principal-1"
    assert selector.calls[0]["search"] == "ops"
    assert selector.calls[0]["offset"] == 20
    assert isinstance(selector.calls[0]["now"], datetime.datetime)
    assert slack.update_calls == [{"view_id": "V-1", "view_hash": "hash-1"}]
    assert slack.views[0].blocks[0]["element"] == {
        "type": "plain_text_input",
        "action_id": "azents_agent_selector_search",
        "initial_value": "ops",
        "placeholder": {"type": "plain_text", "text": "Search Agents"},
    }
    assert "azents_agent_selector_previous" in repr(slack.views[0].blocks)


@pytest.mark.asyncio
async def test_submission_revalidates_signed_modal_scope_before_selection() -> None:
    repository = _Repository()
    repository.interactions["interaction-2"] = (
        ExternalChannelInteraction.model_construct(
            id="interaction-2",
            connection_id="connection-1",
            principal_id="principal-1",
            resource_correlation_key=None,
            interaction_type=ExternalChannelInteractionType.VIEW_SUBMISSION,
            status=ExternalChannelInteractionStatus.PROCESSING,
        )
    )
    selector = _Selector(_catalog())
    selector.selection = ExternalChannelSelectorSelection(
        status="selected",
        selector_interaction=ExternalChannelInteraction.model_construct(
            id="admission-1",
        ),
        binding=None,
    )
    slack = _Slack(
        SlackInteractionViewResult(
            status="opened",
            error_kind=None,
            error_summary=None,
        )
    )
    metadata = build_selector_metadata(
        secret=_SECRET,
        connection_id="connection-1",
        resource_id="resource-1",
        selector_interaction_id="admission-1",
        interaction_id="interaction-1",
        principal_id="principal-1",
        offset=0,
    )

    replay = _Replay()
    await _processor(repository, selector, slack, replay).process(
        ExternalChannelInteractionHandoff(
            interaction_id="interaction-2",
            handler="selector_submission",
            provider_parent_channel_id=None,
            provider_thread_key=None,
            settings_metadata=None,
            settings_location=None,
            settings_response_mode=None,
            selector_metadata=metadata,
            selected_route_id="route-alpha",
        )
    )

    assert len(selector.selection_calls) == 1
    call = selector.selection_calls[0]
    assert call["selector_interaction_id"] == "admission-1"
    assert call["principal_id"] == "principal-1"
    assert call["route_id"] == "route-alpha"
    assert isinstance(call["now"], datetime.datetime)
    assert len(replay.calls) == 1
    assert replay.calls[0]["selector_interaction_id"] == "admission-1"
    assert replay.calls[0]["principal_id"] == "principal-1"
    assert slack.views == []


@pytest.mark.asyncio
async def test_typed_submission_replays_and_delivers_committed_control() -> None:
    """A typed selector boundary uses shared ingestion and its control intent."""
    repository = _Repository()
    repository.interactions["interaction-2"] = (
        ExternalChannelInteraction.model_construct(
            id="interaction-2",
            connection_id="connection-1",
            principal_id="principal-1",
            resource_correlation_key=None,
            interaction_type=ExternalChannelInteractionType.VIEW_SUBMISSION,
            status=ExternalChannelInteractionStatus.PROCESSING,
        )
    )
    selector = _Selector(_catalog())
    selector.selection = ExternalChannelSelectorSelection(
        status="selected",
        selector_interaction=ExternalChannelInteraction.model_construct(
            id="admission-1",
        ),
        binding=None,
    )
    slack = _Slack(
        SlackInteractionViewResult(
            status="opened",
            error_kind=None,
            error_summary=None,
        )
    )
    metadata = build_selector_metadata(
        secret=_SECRET,
        connection_id="connection-1",
        resource_id="resource-1",
        selector_interaction_id="admission-1",
        interaction_id="interaction-1",
        principal_id="principal-1",
        offset=0,
    )
    provider_control = _ProviderControl()
    plan = make_provider_effect_plan("selector-replay")
    replay = _Replay(
        ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.AWAITING_ACCESS,
            reason=ExternalChannelIngestionReason.ACCESS_REQUIRED,
            mailbox_item_id=None,
            control_plans=(plan,),
            connection_id="connection-1",
        )
    )

    await _processor(
        repository,
        selector,
        slack,
        replay,
        provider_control,
    ).process(
        ExternalChannelInteractionHandoff(
            interaction_id="interaction-2",
            handler="selector_submission",
            provider_parent_channel_id=None,
            provider_thread_key=None,
            settings_metadata=None,
            settings_location=None,
            settings_response_mode=None,
            selector_metadata=metadata,
            selected_route_id="route-alpha",
        )
    )

    assert len(replay.calls) == 1
    assert replay.calls[0]["selector_interaction_id"] == "admission-1"
    assert provider_control.calls == [plan]


@pytest.mark.asyncio
async def test_submission_rejects_tampered_metadata_before_selection() -> None:
    repository = _Repository()
    repository.interactions["interaction-2"] = (
        ExternalChannelInteraction.model_construct(
            id="interaction-2",
            connection_id="connection-1",
            principal_id="principal-1",
            resource_correlation_key=None,
            interaction_type=ExternalChannelInteractionType.VIEW_SUBMISSION,
            status=ExternalChannelInteractionStatus.PROCESSING,
        )
    )
    selector = _Selector(_catalog())
    slack = _Slack(
        SlackInteractionViewResult(
            status="opened",
            error_kind=None,
            error_summary=None,
        )
    )
    metadata = build_selector_metadata(
        secret=_SECRET,
        connection_id="connection-1",
        resource_id="resource-1",
        selector_interaction_id="admission-1",
        interaction_id="interaction-1",
        principal_id="principal-1",
        offset=0,
    )

    with pytest.raises(ValueError, match="metadata"):
        await _processor(repository, selector, slack).process(
            ExternalChannelInteractionHandoff(
                interaction_id="interaction-2",
                handler="selector_submission",
                provider_parent_channel_id=None,
                provider_thread_key=None,
                settings_metadata=None,
                settings_location=None,
                settings_response_mode=None,
                selector_metadata=metadata[:-1] + ("A" if metadata[-1] != "A" else "B"),
                selected_route_id="route-alpha",
            )
        )

    assert selector.selection_calls == []


@pytest.mark.asyncio
async def test_expired_selector_interaction_blocks_modal_before_provider_io() -> None:
    """Expired selector scope cannot open or update a Slack modal."""
    repository = _Repository()
    repository.interaction = repository.interaction.model_copy(
        update={"expires_at": _EXPIRED_AT}
    )
    repository.interactions[repository.interaction.id] = repository.interaction
    selector = _Selector(_catalog())
    slack = _Slack(
        SlackInteractionViewResult(
            status="opened",
            error_kind=None,
            error_summary=None,
        )
    )

    with pytest.raises(ValueError, match="interaction is unavailable"):
        await _processor(repository, selector, slack).process(_handoff())

    assert selector.calls == []
    assert slack.views == []
