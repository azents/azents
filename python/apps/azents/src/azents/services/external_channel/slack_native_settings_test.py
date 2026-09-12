"""Slack private linking, independent model drafts, and safe callback contracts."""

import asyncio
import datetime
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from azents.core.config import AuthConfig, Config, JWTConfig
from azents.core.enums import (
    ExternalChannelInteractionType,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.core.external_account_link import (
    ExternalAccountLinkInvalidCode,
    ExternalAccountLinkState,
    ExternalAccountNativeLinkState,
    ExternalAccountOriginCreated,
    VerifiedExternalAccountActor,
)
from azents.core.external_model_settings import (
    ExternalModelApplied,
    ExternalModelDraft,
    ExternalModelDraftCancelled,
    ExternalModelDraftSelection,
    ExternalModelEditor,
    ExternalModelEditorReady,
    ExternalModelNoticeOutcome,
    ExternalModelOption,
    ExternalModelOptionPage,
    ExternalModelStale,
    ExternalModelTargetContext,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import (
    ModelExecutionOptionId,
    list_model_execution_option_definitions,
)
from azents.repos.external_channel.data import ExternalChannelConnectionConfiguration
from azents.services.external_account_link import ExternalAccountLinkService
from azents.services.external_channel.interaction_test import (
    _catalog,
    _handoff,
    _processor,
    _Repository,
    _Selector,
    _Slack,
)
from azents.services.external_channel.model_settings import ExternalModelSettingsService
from azents.services.external_channel.slack_events import (
    SlackInteractionView,
    SlackInteractionViewResult,
)
from azents.services.external_channel.slack_http import (
    SlackHTTPInvalidPayload,
    parse_slack_interaction_payload,
)
from azents.services.external_channel.slack_native_protocol import (
    NativeAction,
    SlackNativeControl,
    SlackNativeScope,
    parse_native_scope,
    sign_native_scope,
)
from azents.services.external_channel.slack_native_settings import (
    SlackNativeSettingsService,
)
from azents.services.external_channel.slack_native_views import (
    add_personal_controls,
    model_editor_view,
    private_notice,
)

_NOW = datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC)
_SECRET = "native-test-signing-secret"


def _scope() -> SlackNativeScope:
    return SlackNativeScope(
        connection_id="connection-1",
        principal_id="principal-1",
        channel_id="C1",
        thread_id="123.456",
        expires_at=_NOW + datetime.timedelta(minutes=10),
        origin_id="origin-1",
        draft_id="draft-1",
        selection_fingerprint="aaaaaaaaaaaaaaaa",
        offset=0,
    )


def _actor() -> VerifiedExternalAccountActor:
    return VerifiedExternalAccountActor(
        connection_id="connection-1",
        connection_configuration_generation=1,
        principal_id="principal-1",
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="T1",
        provider_tenant_display_label=None,
        provider_user_id="U1",
        provider_display_label="Private actor",
        provider_interaction_id="interaction-1",
        provider_channel_id="C1",
        provider_thread_id="123.456",
    )


def _control(action: NativeAction) -> SlackNativeControl:
    return SlackNativeControl(
        action=action,
        metadata=sign_native_scope(_scope(), secret=_SECRET),
        code=None,
        option_id=None,
        reasoning_effort=None,
        execution_options=None,
        view_id="V1",
        view_hash="hash-1",
    )


def _config() -> Config:
    return Config.model_construct(
        web_url="https://azents.example",
        auth=AuthConfig.model_construct(
            jwt=JWTConfig.model_construct(secret_key=_SECRET)
        ),
    )


def _editor(*, offset: int = 0, options_supported: bool = True) -> ExternalModelEditor:
    selected = ExternalModelOption(
        option_id="opaque-model",
        label="Model <private>",
        model_display_name="Model & name",
        reasoning_efforts=[ModelReasoningEffort.LOW, ModelReasoningEffort.HIGH]
        if options_supported
        else [],
        execution_options=list_model_execution_option_definitions()
        if options_supported
        else [],
    )
    return ExternalModelEditor(
        draft=ExternalModelDraft(
            id="draft-1",
            owner_interaction_key="interaction-1",
            target=ExternalModelTargetContext(
                binding_id="binding-1", session_id="session-1", agent_id="agent-1"
            ),
            expected_generation=2,
            selection_fingerprint="aaaaaaaaaaaaaaaa",
            selection=ExternalModelDraftSelection(
                option_id=selected.option_id,
                reasoning_effort=None,
                enabled_execution_options=[],
            ),
            expires_at=_NOW + datetime.timedelta(minutes=15),
        ),
        selected_option=selected,
        scope_label="Only this connected thread",
        current_profile=RequestedInferenceProfile(
            model_target_label="current-model",
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
        current_generation=2,
        options=ExternalModelOptionPage(
            items=[
                selected.model_copy(update={"option_id": f"opaque-{index}"})
                for index in range(offset, offset + 10)
            ],
            offset=offset,
            limit=10,
            total_count=120,
        ),
    )


def _service() -> SlackNativeSettingsService:
    return SlackNativeSettingsService(
        linking=AsyncMock(spec=ExternalAccountLinkService),
        models=AsyncMock(spec=ExternalModelSettingsService),
        config=_config(),
    )


def test_signed_scope_rejects_tampering_expiry_and_wrong_secret() -> None:
    metadata = sign_native_scope(_scope(), secret=_SECRET)
    assert parse_native_scope(metadata, secret=_SECRET, now=_NOW) == _scope()
    for invalid, secret in [(metadata + "x", _SECRET), (metadata, "wrong")]:
        with pytest.raises(ValueError):
            parse_native_scope(invalid, secret=secret, now=_NOW)
    with pytest.raises(ValueError):
        parse_native_scope(
            metadata, secret=_SECRET, now=_NOW + datetime.timedelta(minutes=11)
        )


def _code_payload(code: str) -> dict[str, object]:
    return {
        "type": "view_submission",
        "api_app_id": "app-1",
        "team": {"id": "T1"},
        "user": {"id": "U1"},
        "trigger_id": "transient-trigger",
        "view": {
            "callback_id": "azents_account_link_code",
            "id": "V1",
            "hash": "hash-1",
            "private_metadata": sign_native_scope(_scope(), secret=_SECRET),
            "state": {
                "values": {"azents_account_link_code": {"value": {"value": code}}}
            },
        },
    }


def test_code_is_request_local_and_absent_from_durable_projection() -> None:
    code = "CODE-MUST-NEVER-PERSIST"
    callback = parse_slack_interaction_payload(
        payload=_code_payload(code),
        provider_interaction_key="interaction-1",
        received_at=_NOW,
    )
    assert callback.handler == "native_control"
    assert callback.native_control is not None
    assert callback.native_control.code == code
    assert code not in repr(callback)
    assert code not in repr(callback.native_control)
    durable = callback.interaction_create(
        connection_id="connection-1", transport=ExternalChannelTransport.HTTP
    )
    assert code not in repr(durable)
    assert code not in json.dumps(callback.projection)


@pytest.mark.parametrize("code", ["", "x" * 129])
def test_code_validation_errors_do_not_retain_input_in_visible_exception(
    code: str,
) -> None:
    with pytest.raises(SlackHTTPInvalidPayload) as error:
        parse_slack_interaction_payload(
            payload=_code_payload(code),
            provider_interaction_key="interaction-1",
            received_at=_NOW,
        )
    assert str(error.value) == "Slack private control is invalid."
    assert error.value.__suppress_context__


def test_controls_preserve_guest_submission_and_do_not_inline_model_inputs() -> None:
    guest = replace(
        private_notice("Guest response controls"),
        callback_id="guest-save",
        submit_title="Save",
        private_metadata="guest-scope",
    )
    decorated = add_personal_controls(
        guest,
        metadata="signed-personal-scope",
        management_url="https://azents.example/account/external-accounts",
        link_state=None,
        model_metadata="signed-draft-scope",
    )
    assert decorated.callback_id == guest.callback_id
    assert decorated.private_metadata == guest.private_metadata
    assert decorated.submit_title == "Save"
    assert decorated.blocks[: len(guest.blocks)] == guest.blocks
    assert "azents_account_link_start" in repr(decorated.blocks)
    assert "azents_model_open" in repr(decorated.blocks)
    assert "azents_model_apply" not in repr(decorated.blocks)


def test_inactive_link_retains_private_management_without_model_authority() -> None:
    view = add_personal_controls(
        private_notice("Guest controls"),
        metadata="signed-scope",
        management_url="https://azents.example/account/external-accounts",
        link_state=ExternalAccountLinkState.INACTIVE,
        model_metadata=None,
    )
    assert "connection inactive" in repr(view.blocks)
    assert "Manage connected account" in repr(view.blocks)
    assert "azents_model_open" not in repr(view.blocks)


def test_private_model_view_pages_full_catalog_and_selected_capabilities() -> None:
    editor = _editor(offset=10)
    view = model_editor_view(editor, scope=_scope(), secret=_SECRET, notice=None)
    rendered = json.dumps(view.blocks)
    assert "azents_model_previous" in rendered and "azents_model_next" in rendered
    assert "of 120" in rendered
    assert "azents_model_effort" in rendered and "azents_model_execution" in rendered
    assert view.submit_title == "Apply"
    assert "current-model" in rendered and "whole conversation" in rendered
    assert "Model <private>" in rendered
    assert '"type": "mrkdwn"' not in rendered
    assert (
        parse_native_scope(view.private_metadata, secret=_SECRET, now=_NOW).offset == 10
    )
    unsupported = model_editor_view(
        _editor(options_supported=False), scope=_scope(), secret=_SECRET, notice=None
    )
    assert "azents_model_effort" not in repr(unsupported.blocks)
    assert "azents_model_execution" not in repr(unsupported.blocks)


@pytest.mark.asyncio
async def test_actor_mismatch_does_not_call_domain_or_expose_scope() -> None:
    service = _service()
    view = await service.process(
        actor=replace(_actor(), principal_id="wrong-actor"),
        scope=_scope(),
        control=_control("azents_account_link_start"),
        now=_NOW,
    )
    assert "unavailable" in repr(view.blocks)
    assert "Private actor" not in repr(view.blocks)
    assert isinstance(service.linking, AsyncMock)
    service.linking.create_origin.assert_not_awaited()
    assert isinstance(service.models, AsyncMock)
    service.models.open_editor.assert_not_awaited()


@pytest.mark.asyncio
async def test_denied_guest_still_gets_own_optional_link_only_surface() -> None:
    service = _service()
    assert isinstance(service.linking, AsyncMock)
    service.linking.get_native_link_state.return_value = ExternalAccountNativeLinkState(
        link=None, management_path="/account/external-accounts"
    )
    view = await service.decorate(
        view=private_notice("Conversation settings unavailable"),
        actor=_actor(),
        settings=None,
        now=_NOW,
    )
    assert "azents_account_link_start" in repr(view.blocks)
    assert "azents_model_open" not in repr(view.blocks)
    assert "session-1" not in repr(view.blocks)
    assert isinstance(service.models, AsyncMock)
    service.models.open_editor.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_start_and_code_verification_never_apply_models() -> None:
    service = _service()
    assert isinstance(service.linking, AsyncMock)
    service.linking.create_origin.return_value = ExternalAccountOriginCreated(
        origin_id="origin-new",
        expires_at=_NOW + datetime.timedelta(minutes=10),
        web_path="/external-channel/link/origin-new",
        management_path="/account/external-accounts",
    )
    view = await service.process(
        actor=_actor(),
        scope=_scope(),
        control=_control("azents_account_link_start"),
        now=_NOW,
    )
    assert view.callback_id == "azents_account_link_code"
    assert (
        parse_native_scope(view.private_metadata, secret=_SECRET, now=_NOW).origin_id
        == "origin-new"
    )
    control = _control("azents_account_link_code").model_copy(
        update={"code": "temporary-code"}
    )
    verified = await service.process(
        actor=_actor(), scope=_scope(), control=control, now=_NOW
    )
    assert "explicitly confirm" in repr(verified.blocks)
    assert "temporary-code" not in repr(verified)
    service.linking.verify_candidate_code.assert_awaited_once_with(
        actor=_actor(), origin_id="origin-1", code="temporary-code", now=_NOW
    )
    assert isinstance(service.models, AsyncMock)
    service.models.apply_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_code_reopens_blank_private_input() -> None:
    service = _service()
    assert isinstance(service.linking, AsyncMock)
    service.linking.verify_candidate_code.side_effect = ExternalAccountLinkInvalidCode(
        remaining_attempts=3
    )
    control = _control("azents_account_link_code").model_copy(
        update={"code": "incorrect-code"}
    )
    view = await service.process(
        actor=_actor(), scope=_scope(), control=control, now=_NOW
    )
    assert view.submit_title == "Verify code"
    assert "3 attempts remain" in repr(view.blocks)
    assert "incorrect-code" not in repr(view)
    assert "initial_value" not in repr(view.blocks)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", ["azents_model_next", "azents_model_effort", "azents_model_execution"]
)
async def test_draft_actions_never_apply_shared_state(action: NativeAction) -> None:
    service = _service()
    assert isinstance(service.models, AsyncMock)
    service.models.page_options.return_value = ExternalModelEditorReady(
        editor=_editor()
    )
    service.models.update_draft.return_value = ExternalModelEditorReady(
        editor=_editor()
    )
    control = _control(action).model_copy(
        update={
            "reasoning_effort": ModelReasoningEffort.HIGH,
            "execution_options": [ModelExecutionOptionId.FAST],
        }
    )
    view = await service.process(
        actor=_actor(), scope=_scope(), control=control, now=_NOW
    )
    assert view.submit_title == "Apply"
    service.models.apply_draft.assert_not_awaited()
    if action == "azents_model_next":
        assert service.models.page_options.await_args.kwargs["offset"] == 10
    else:
        service.models.update_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_apply_refreshes_authoritative_state() -> None:
    service = _service()
    assert isinstance(service.models, AsyncMock)
    refreshed = _editor().model_copy(
        update={
            "current_generation": 3,
            "current_profile": RequestedInferenceProfile(
                model_target_label="authoritative-new",
                reasoning_effort=None,
                enabled_execution_options=[],
            ),
        }
    )
    service.models.apply_draft.return_value = ExternalModelStale(editor=refreshed)
    view = await service.process(
        actor=_actor(), scope=_scope(), control=_control("azents_model_apply"), now=_NOW
    )
    assert "Nothing was saved" in repr(view.blocks)
    assert "authoritative-new" in repr(view.blocks)
    assert "current-model" not in repr(view.blocks)


@pytest.mark.asyncio
async def test_saved_notice_failure_still_reports_committed_settings() -> None:
    service = _service()
    assert isinstance(service.models, AsyncMock)
    service.models.apply_draft.return_value = ExternalModelApplied(
        editor=_editor(),
        created=True,
        mutation_id="mutation-1",
        notice_outcome=ExternalModelNoticeOutcome.FAILED,
    )
    view = await service.process(
        actor=_actor(), scope=_scope(), control=_control("azents_model_apply"), now=_NOW
    )
    assert "your settings are saved" in repr(view.blocks)
    assert "could not be confirmed" in repr(view.blocks)
    service.models.apply_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_discards_only_private_draft() -> None:
    service = _service()
    assert isinstance(service.models, AsyncMock)
    service.models.cancel_draft.return_value = ExternalModelDraftCancelled(
        draft_id="draft-1"
    )
    view = await service.process(
        actor=_actor(),
        scope=_scope(),
        control=_control("azents_model_cancel"),
        now=_NOW,
    )
    assert "Draft discarded" in repr(view.blocks)
    service.models.apply_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_web_url_never_blocks_guest_settings() -> None:
    service = _service()
    service.config = _config().model_copy(update={"web_url": ""})
    assert isinstance(service.linking, AsyncMock)
    service.linking.get_native_link_state.return_value = ExternalAccountNativeLinkState(
        link=None, management_path="/account/external-accounts"
    )
    guest = replace(private_notice("Guest controls"), submit_title="Save")
    assert (
        await service.decorate(view=guest, actor=_actor(), settings=None, now=_NOW)
        == guest
    )


@pytest.mark.asyncio
async def test_apply_uses_visible_selection_during_pending_update() -> None:
    """A conflicting later private update cannot commit an unseen model choice."""
    initial = _editor()
    first = initial.model_copy(
        update={
            "draft": initial.draft.model_copy(
                update={
                    "selection": initial.draft.selection.model_copy(
                        update={"reasoning_effort": ModelReasoningEffort.HIGH}
                    ),
                    "selection_fingerprint": "aaaaaaaaaaaaaaaa",
                }
            )
        }
    )
    second = initial.model_copy(
        update={
            "draft": initial.draft.model_copy(
                update={
                    "selection": initial.draft.selection.model_copy(
                        update={"reasoning_effort": ModelReasoningEffort.LOW}
                    ),
                    "selection_fingerprint": "bbbbbbbbbbbbbbbb",
                }
            )
        }
    )
    current = initial
    shared_writes: list[str] = []
    observed_fingerprints: list[str] = []
    second_view_in_flight = asyncio.Event()
    release_second_view = asyncio.Event()

    class DelayedSlack(_Slack):
        visible: SlackInteractionView | None = None
        updates = 0

        async def update_interaction_view(
            self,
            *,
            bot_token: str,
            view_id: str,
            view_hash: str | None,
            view: SlackInteractionView,
        ) -> SlackInteractionViewResult:
            assert view_hash == "same-original-hash"
            self.updates += 1
            if self.updates == 1:
                self.visible = view
                return SlackInteractionViewResult(
                    status="updated", error_kind=None, error_summary=None
                )
            second_view_in_flight.set()
            await release_second_view.wait()
            return SlackInteractionViewResult(
                status="conflict", error_kind="hash_conflict", error_summary=None
            )

    async def page_options(**kwargs: object) -> ExternalModelEditorReady:
        return ExternalModelEditorReady(editor=current)

    async def update_draft(
        *, selection: ExternalModelDraftSelection, **kwargs: object
    ) -> ExternalModelEditorReady:
        nonlocal current
        current = (
            first if selection.reasoning_effort == ModelReasoningEffort.HIGH else second
        )
        return ExternalModelEditorReady(editor=current)

    async def apply_draft(
        *, expected_selection_fingerprint: str, **kwargs: object
    ) -> ExternalModelStale | ExternalModelApplied:
        observed_fingerprints.append(expected_selection_fingerprint)
        if expected_selection_fingerprint != current.draft.selection_fingerprint:
            return ExternalModelStale(editor=current)
        shared_writes.append(expected_selection_fingerprint)
        return ExternalModelApplied(
            editor=current,
            created=True,
            mutation_id="mutation-1",
            notice_outcome=ExternalModelNoticeOutcome.DELIVERED,
        )

    service = _service()
    assert isinstance(service.models, AsyncMock)
    service.models.page_options.side_effect = page_options
    service.models.update_draft.side_effect = update_draft
    service.models.apply_draft.side_effect = apply_draft
    repository = _Repository()
    for interaction_id, interaction_type in [
        ("interaction-1", ExternalChannelInteractionType.BLOCK_ACTION),
        ("interaction-2", ExternalChannelInteractionType.BLOCK_ACTION),
        ("interaction-3", ExternalChannelInteractionType.VIEW_SUBMISSION),
    ]:
        repository.interactions[interaction_id] = repository.interaction.model_copy(
            update={"id": interaction_id, "interaction_type": interaction_type}
        )
    slack = DelayedSlack(
        SlackInteractionViewResult(status="opened", error_kind=None, error_summary=None)
    )
    processor = _processor(
        repository,
        _Selector(_catalog()),
        slack,
        scheduled_task_control=AsyncMock(),
        scheduled_task_channel=AsyncMock(),
    )
    processor.native_settings = service
    processor.config = _config()
    scope = _scope().model_copy(
        update={"expires_at": datetime.datetime.max.replace(tzinfo=datetime.UTC)}
    )
    first_control = _control("azents_model_effort").model_copy(
        update={
            "metadata": sign_native_scope(scope, secret=_SECRET),
            "view_hash": "same-original-hash",
            "reasoning_effort": ModelReasoningEffort.HIGH,
        }
    )
    await processor.process(
        replace(_handoff(), handler="native_control", native_control=first_control)
    )
    assert slack.visible is not None
    visible_metadata = slack.visible.private_metadata
    second_task = asyncio.create_task(
        processor.process(
            replace(
                _handoff(),
                interaction_id="interaction-2",
                handler="native_control",
                native_control=first_control.model_copy(
                    update={"reasoning_effort": ModelReasoningEffort.LOW}
                ),
            )
        )
    )
    try:
        await asyncio.wait_for(second_view_in_flight.wait(), timeout=5)
        assert current.draft.selection_fingerprint == "bbbbbbbbbbbbbbbb"
        await processor.process(
            replace(
                _handoff(),
                interaction_id="interaction-3",
                handler="native_control",
                native_control=_control("azents_model_apply").model_copy(
                    update={"metadata": visible_metadata}
                ),
            )
        )
    finally:
        release_second_view.set()
        await second_task
    assert observed_fingerprints == ["aaaaaaaaaaaaaaaa"]
    assert shared_writes == []
    assert slack.updates == 2
    assert "Nothing was saved" in repr(slack.views)


@pytest.mark.parametrize(
    ("user_fields", "expected"),
    [
        ({"name": "Workspace nickname", "username": "username"}, "Workspace nickname"),
        ({"username": "fallback-name"}, "fallback-name"),
        ({"name": " \n Display\t Name "}, "Display Name"),
        ({"name": 123, "username": "valid-name"}, "valid-name"),
        ({"name": " "}, "U1"),
        ({}, "U1"),
        ({"name": "x" * 300}, "x" * 255),
    ],
)
def test_interaction_display_name_is_bounded_optional_metadata(
    user_fields: dict[str, object], expected: str
) -> None:
    payload = _code_payload("request-local-test-code")
    payload["user"] = {"id": "U1", **user_fields}
    callback = parse_slack_interaction_payload(
        payload=payload, provider_interaction_key="interaction-1", received_at=_NOW
    )
    configuration = ExternalChannelConnectionConfiguration.model_construct(
        id="connection-1",
        provider_tenant_id="T1",
        provider_app_id="app-1",
        configuration_generation=3,
    )
    actor = callback.verified_actor(
        configuration=configuration, principal_id="principal-1"
    )
    assert actor.provider_display_name == expected
    assert actor.provider_user_id == "U1"
    assert actor.configuration_generation == 3
    assert callback.principal_create().display_name == expected
    assert "actor_display_name" not in callback.projection


def test_interaction_nickname_renders_as_literal_private_text() -> None:
    name = "<@U2> & nickname"
    payload = _code_payload("request-local-test-code")
    payload["user"] = {"id": "U1", "name": name}
    callback = parse_slack_interaction_payload(
        payload=payload, provider_interaction_key="interaction-1", received_at=_NOW
    )
    assert callback.actor_display_name == name
    view = private_notice(callback.actor_display_name)
    assert view.blocks == [
        {
            "type": "section",
            "text": {"type": "plain_text", "text": name, "emoji": False},
        }
    ]
    assert name not in repr(callback)


def test_slash_command_display_name_uses_signed_user_name_field() -> None:
    callback = parse_slack_interaction_payload(
        payload={
            "command": "/azents",
            "text": "settings",
            "user_id": "U1",
            "user_name": "Command nickname",
            "team_id": "T1",
            "api_app_id": "app-1",
            "trigger_id": "request-local-trigger",
            "channel_id": "C1",
        },
        provider_interaction_key="interaction-1",
        received_at=_NOW,
    )
    assert callback.principal_create().display_name == "Command nickname"
    assert callback.actor_user_id == "U1"
