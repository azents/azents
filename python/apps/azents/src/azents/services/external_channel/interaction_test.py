"""Slack selector modal-open interaction tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Literal, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelConversationAdmission,
    ExternalChannelInteraction,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.credentials import (
    ExternalChannelCredentialsCodec,
)
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.event_processor import (
    ExternalChannelEventProcessorService,
    ExternalChannelSelectedAdmissionContinuation,
)
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
    ExternalChannelInteractionProcessor,
    SlackInteractionTriggerExpired,
    build_selector_metadata,
    verify_selector_metadata,
)
from azents.services.external_channel.selector import (
    ExternalChannelSelectorCandidate,
    ExternalChannelSelectorCatalog,
    ExternalChannelSelectorSelection,
    ExternalChannelSelectorService,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackInteractionView,
    SlackInteractionViewResult,
)

_NOW = datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC)
_SECRET = "selector-metadata-test-secret"


class _Session:
    async def commit(self) -> None:
        pass


class _Repository:
    def __init__(self) -> None:
        self.interaction = ExternalChannelInteraction.model_construct(
            id="interaction-1",
            connection_id="connection-1",
            principal_id="principal-1",
            resource_correlation_key="C-1:100.0001",
            interaction_type=ExternalChannelInteractionType.SHORTCUT,
            status=ExternalChannelInteractionStatus.PROCESSING,
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
        self.admission = ExternalChannelConversationAdmission.model_construct(
            id="admission-1",
            connection_id="connection-1",
            resource_id="resource-1",
            initiating_principal_id="principal-1",
            status=ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
            expires_at=_NOW + datetime.timedelta(days=1),
        )
        self.interactions = {self.interaction.id: self.interaction}

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
        provider_resource_key: str,
    ) -> ExternalChannelResource | None:
        del session
        return (
            self.resource
            if (
                connection_id == self.resource.connection_id
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

    async def get_open_conversation_admission(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelConversationAdmission | None:
        del session
        return self.admission if resource_id == self.resource.id else None

    async def get_conversation_admission(
        self,
        session: AsyncSession,
        *,
        admission_id: str,
    ) -> ExternalChannelConversationAdmission | None:
        del session
        return self.admission if admission_id == self.admission.id else None


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


class _Continuation:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.delivery_calls: list[dict[str, object]] = []

    async def continue_selected_admission(
        self,
        **kwargs: object,
    ) -> ExternalChannelSelectedAdmissionContinuation:
        self.calls.append(kwargs)
        return ExternalChannelSelectedAdmissionContinuation(
            status="awaiting_access",
            control_delivery_attempt_id=None,
        )

    async def attempt_selected_admission_control_delivery(
        self,
        **kwargs: object,
    ) -> None:
        self.delivery_calls.append(kwargs)


def _processor(
    repository: _Repository,
    selector: _Selector,
    slack: _Slack,
    continuation: _Continuation | None = None,
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
        event_processor=cast(
            ExternalChannelEventProcessorService,
            continuation or _Continuation(),
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


def _handoff(*, admission_id: str | None = None) -> ExternalChannelInteractionHandoff:
    return ExternalChannelInteractionHandoff(
        interaction_id="interaction-1",
        trigger_id="trigger-secret-must-not-persist",
        selector_admission_id=admission_id,
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
    assert selector.calls[0]["admission_id"] == "admission-1"
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
    repository.admission = repository.admission.model_copy(
        update={"resource_id": "foreign-resource"}
    )

    with pytest.raises(ValueError, match="admission is unavailable"):
        await _processor(repository, selector, slack).process(
            _handoff(admission_id="admission-1")
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
        admission_id="admission-1",
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
            admission_id="admission-1",
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
            admission_id="admission-1",
            interaction_id="interaction-1",
            principal_id="principal-1",
        )
    with pytest.raises(ValueError, match="scope"):
        verify_selector_metadata(
            metadata=metadata,
            secret=_SECRET,
            connection_id="connection-1",
            resource_id="foreign-resource",
            admission_id="admission-1",
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
        admission_id="admission-1",
        interaction_id="interaction-1",
        principal_id="principal-1",
        offset=0,
    )

    await _processor(repository, selector, slack).process(
        ExternalChannelInteractionHandoff(
            interaction_id="interaction-2",
            selector_metadata=metadata,
            selector_navigation="next",
            selector_search="ops",
            selector_view_id="V-1",
            selector_view_hash="hash-1",
        )
    )

    assert len(selector.calls) == 1
    assert selector.calls[0]["admission_id"] == "admission-1"
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
        admission=repository.admission.model_copy(
            update={
                "status": ExternalChannelConversationAdmissionStatus.SELECTED,
                "selected_route_id": "route-alpha",
            }
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
        admission_id="admission-1",
        interaction_id="interaction-1",
        principal_id="principal-1",
        offset=0,
    )

    continuation = _Continuation()
    await _processor(repository, selector, slack, continuation).process(
        ExternalChannelInteractionHandoff(
            interaction_id="interaction-2",
            selector_metadata=metadata,
            selected_route_id="route-alpha",
        )
    )

    assert len(selector.selection_calls) == 1
    call = selector.selection_calls[0]
    assert call["admission_id"] == "admission-1"
    assert call["principal_id"] == "principal-1"
    assert call["route_id"] == "route-alpha"
    assert isinstance(call["now"], datetime.datetime)
    assert len(continuation.calls) == 1
    assert continuation.calls[0]["admission_id"] == "admission-1"
    assert continuation.calls[0]["principal_id"] == "principal-1"
    assert slack.views == []


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
        admission_id="admission-1",
        interaction_id="interaction-1",
        principal_id="principal-1",
        offset=0,
    )

    with pytest.raises(ValueError, match="metadata"):
        await _processor(repository, selector, slack).process(
            ExternalChannelInteractionHandoff(
                interaction_id="interaction-2",
                selector_metadata=metadata[:-1] + ("A" if metadata[-1] != "A" else "B"),
                selected_route_id="route-alpha",
            )
        )

    assert selector.selection_calls == []


@pytest.mark.asyncio
async def test_expired_admission_blocks_modal_before_provider_io() -> None:
    """Expired selector scope cannot open or update a Slack modal."""
    repository = _Repository()
    repository.admission = repository.admission.model_copy(
        update={"expires_at": _NOW - datetime.timedelta(days=1)}
    )
    selector = _Selector(_catalog())
    slack = _Slack(
        SlackInteractionViewResult(
            status="opened",
            error_kind=None,
            error_summary=None,
        )
    )

    with pytest.raises(ValueError, match="admission is unavailable"):
        await _processor(repository, selector, slack).process(_handoff())

    assert selector.calls == []
    assert slack.views == []
