"""External model settings service tests."""

import datetime
import logging
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.core.enums import ExternalChannelProvider
from azents.core.external_model_settings import (
    ExternalModelActorContext,
    ExternalModelApplied,
    ExternalModelDraft,
    ExternalModelDraftSelection,
    ExternalModelEditor,
    ExternalModelNoticeOutcome,
    ExternalModelNoticePlan,
    ExternalModelOption,
    ExternalModelOptionPage,
    ExternalModelTargetContext,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.repos.external_channel.model_settings import (
    ExternalModelSettingsRepository,
)
from azents.repos.external_channel.model_settings_data import (
    ExternalModelApplyCommit,
    ExternalModelNoticeDeliveryContext,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.discord_delivery import DiscordDeliveryClient
from azents.services.external_channel.model_settings import ExternalModelSettingsService
from azents.services.external_channel.slack_events import SlackConversationClient

_NOW = datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC)
_ACTOR = ExternalModelActorContext(
    provider=ExternalChannelProvider.SLACK,
    connection_id="connection-1",
    configuration_generation=1,
    principal_id="principal-1",
    provider_tenant_id="team-1",
    provider_user_id="user-1",
    provider_display_name="External user",
)
_TARGET = ExternalModelTargetContext(
    binding_id="binding-1",
    session_id="session-1",
    agent_id="agent-1",
)
_OPTION = ExternalModelOption(
    option_id="option-1",
    label="default",
    model_display_name="Test model",
    reasoning_efforts=[],
    execution_options=[],
)
_EDITOR = ExternalModelEditor(
    draft=ExternalModelDraft(
        id="draft-1",
        owner_interaction_key="open-1",
        target=_TARGET,
        expected_generation=0,
        selection=ExternalModelDraftSelection(
            option_id="option-1",
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
        selection_fingerprint="a" * 16,
        expires_at=_NOW + datetime.timedelta(minutes=15),
    ),
    scope_label="Test thread",
    current_profile=RequestedInferenceProfile(
        model_target_label="default",
        reasoning_effort=None,
        enabled_execution_options=[],
    ),
    current_generation=1,
    selected_option=_OPTION,
    options=ExternalModelOptionPage(
        items=[_OPTION],
        offset=0,
        limit=10,
        total_count=1,
    ),
)
_PLAN = ExternalModelNoticePlan(
    mutation_id="mutation-1",
    provider=ExternalChannelProvider.SLACK,
    connection_id="connection-1",
    provider_conversation_id="channel-1",
    provider_thread_id="1.000001",
    actor_display_name="External user",
    model_label="default",
    model_display_name="Test model",
    reasoning_effort=None,
    enabled_execution_option_labels=[],
)


def _service(
    repository: object,
    slack_client: object,
    *,
    codec: ExternalChannelCredentialsCodec | None = None,
) -> ExternalModelSettingsService:
    if codec is None:
        codec = MagicMock(spec=ExternalChannelCredentialsCodec)
        codec.decrypt.return_value = SimpleNamespace(bot_token="secret")
    return ExternalModelSettingsService(
        repository=cast(ExternalModelSettingsRepository, repository),
        credentials_codec=codec,
        slack_client=cast(SlackConversationClient, slack_client),
        discord_client=cast(DiscordDeliveryClient, object()),
    )


async def test_apply_attempts_notice_once_only_for_new_commit() -> None:
    """Fresh Apply sends once and an authorized replay never resends."""
    repository = SimpleNamespace(
        apply_draft=AsyncMock(
            return_value=ExternalModelApplyCommit(
                result=ExternalModelApplied(
                    editor=_EDITOR,
                    created=True,
                    mutation_id="mutation-1",
                    notice_outcome=ExternalModelNoticeOutcome.UNKNOWN,
                ),
                notice_plan=_PLAN,
            )
        ),
        get_notice_delivery_context=AsyncMock(
            return_value=ExternalModelNoticeDeliveryContext(
                plan=_PLAN,
                encrypted_credentials="encrypted",
            )
        ),
        record_notice_outcome=AsyncMock(
            return_value=ExternalModelNoticeOutcome.DELIVERED
        ),
    )
    slack_client = SimpleNamespace(
        post_message=AsyncMock(
            return_value=SimpleNamespace(
                status="delivered",
                error_summary=None,
            )
        )
    )
    service = _service(repository, slack_client)

    applied = await service.apply_draft(
        actor=_ACTOR,
        draft_id="draft-1",
        expected_selection_fingerprint="a" * 16,
        apply_interaction_key="apply-1",
        now=_NOW,
    )
    assert isinstance(applied, ExternalModelApplied)
    assert applied.notice_outcome is ExternalModelNoticeOutcome.DELIVERED
    slack_client.post_message.assert_awaited_once()
    repository.record_notice_outcome.assert_awaited_once()

    repository.apply_draft.return_value = ExternalModelApplyCommit(
        result=ExternalModelApplied(
            editor=_EDITOR,
            created=False,
            mutation_id="mutation-1",
            notice_outcome=ExternalModelNoticeOutcome.DELIVERED,
        ),
        notice_plan=None,
    )
    replay = await service.apply_draft(
        actor=_ACTOR,
        draft_id="draft-1",
        expected_selection_fingerprint="a" * 16,
        apply_interaction_key="apply-1",
        now=_NOW,
    )
    assert isinstance(replay, ExternalModelApplied)
    assert replay.created is False
    slack_client.post_message.assert_awaited_once()
    repository.get_notice_delivery_context.assert_awaited_once()


async def test_apply_preserves_commit_when_notice_delivery_raises() -> None:
    """An unexpected provider failure records unknown without failing Apply."""
    repository = SimpleNamespace(
        apply_draft=AsyncMock(
            return_value=ExternalModelApplyCommit(
                result=ExternalModelApplied(
                    editor=_EDITOR,
                    created=True,
                    mutation_id="mutation-1",
                    notice_outcome=ExternalModelNoticeOutcome.UNKNOWN,
                ),
                notice_plan=_PLAN,
            )
        ),
        get_notice_delivery_context=AsyncMock(
            return_value=ExternalModelNoticeDeliveryContext(
                plan=_PLAN,
                encrypted_credentials="encrypted",
            )
        ),
        record_notice_outcome=AsyncMock(
            return_value=ExternalModelNoticeOutcome.UNKNOWN
        ),
    )
    slack_client = SimpleNamespace(
        post_message=AsyncMock(side_effect=RuntimeError("provider failed"))
    )
    service = _service(repository, slack_client)

    applied = await service.apply_draft(
        actor=_ACTOR,
        draft_id="draft-1",
        expected_selection_fingerprint="a" * 16,
        apply_interaction_key="apply-1",
        now=_NOW,
    )

    assert isinstance(applied, ExternalModelApplied)
    assert applied.notice_outcome is ExternalModelNoticeOutcome.UNKNOWN
    repository.record_notice_outcome.assert_awaited_once_with(
        mutation_id="mutation-1",
        outcome=ExternalModelNoticeOutcome.UNKNOWN,
        attempted_at=_NOW,
        error_summary="External model notice delivery outcome is unknown.",
    )


async def test_apply_preserves_commit_when_notice_decryption_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Credential decode failure records unknown without invoking a provider."""
    repository = SimpleNamespace(
        apply_draft=AsyncMock(
            return_value=ExternalModelApplyCommit(
                result=ExternalModelApplied(
                    editor=_EDITOR,
                    created=True,
                    mutation_id="mutation-1",
                    notice_outcome=ExternalModelNoticeOutcome.UNKNOWN,
                ),
                notice_plan=_PLAN,
            )
        ),
        get_notice_delivery_context=AsyncMock(
            return_value=ExternalModelNoticeDeliveryContext(
                plan=_PLAN,
                encrypted_credentials="encrypted",
            )
        ),
        record_notice_outcome=AsyncMock(
            return_value=ExternalModelNoticeOutcome.UNKNOWN
        ),
    )
    codec = MagicMock(spec=ExternalChannelCredentialsCodec)
    codec.decrypt.side_effect = RuntimeError("decrypted-secret-must-not-log")
    slack_client = SimpleNamespace(post_message=AsyncMock())
    service = _service(repository, slack_client, codec=codec)

    with caplog.at_level(logging.ERROR):
        applied = await service.apply_draft(
            actor=_ACTOR,
            draft_id="draft-1",
            expected_selection_fingerprint="a" * 16,
            apply_interaction_key="apply-1",
            now=_NOW,
        )

    assert isinstance(applied, ExternalModelApplied)
    assert applied.notice_outcome is ExternalModelNoticeOutcome.UNKNOWN
    assert "decrypted-secret-must-not-log" not in caplog.text
    slack_client.post_message.assert_not_awaited()
    repository.record_notice_outcome.assert_awaited_once_with(
        mutation_id="mutation-1",
        outcome=ExternalModelNoticeOutcome.UNKNOWN,
        attempted_at=_NOW,
        error_summary="External model notice delivery outcome is unknown.",
    )


async def test_apply_preserves_commit_when_notice_context_or_recording_fails() -> None:
    """Post-commit repository failures keep the already-saved unknown result."""
    applied_result = ExternalModelApplied(
        editor=_EDITOR,
        created=True,
        mutation_id="mutation-1",
        notice_outcome=ExternalModelNoticeOutcome.UNKNOWN,
    )
    repository = SimpleNamespace(
        apply_draft=AsyncMock(
            return_value=ExternalModelApplyCommit(
                result=applied_result,
                notice_plan=_PLAN,
            )
        ),
        get_notice_delivery_context=AsyncMock(
            side_effect=RuntimeError("context failed")
        ),
        record_notice_outcome=AsyncMock(),
    )
    slack_client = SimpleNamespace(post_message=AsyncMock())
    service = _service(repository, slack_client)

    context_failure = await service.apply_draft(
        actor=_ACTOR,
        draft_id="draft-1",
        expected_selection_fingerprint="a" * 16,
        apply_interaction_key="apply-1",
        now=_NOW,
    )
    assert context_failure is applied_result
    slack_client.post_message.assert_not_awaited()
    repository.record_notice_outcome.assert_not_awaited()

    repository.get_notice_delivery_context.side_effect = None
    repository.get_notice_delivery_context.return_value = (
        ExternalModelNoticeDeliveryContext(
            plan=_PLAN,
            encrypted_credentials="encrypted",
        )
    )
    repository.record_notice_outcome.side_effect = RuntimeError("record failed")
    slack_client.post_message.return_value = SimpleNamespace(
        status="delivered",
        error_summary=None,
    )

    recording_failure = await service.apply_draft(
        actor=_ACTOR,
        draft_id="draft-1",
        expected_selection_fingerprint="a" * 16,
        apply_interaction_key="apply-1",
        now=_NOW,
    )
    assert recording_failure is applied_result
    slack_client.post_message.assert_awaited_once()
