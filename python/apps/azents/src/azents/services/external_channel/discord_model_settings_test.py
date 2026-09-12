"""Discord-native shared model editor presentation tests."""

import datetime

from azents.core.external_model_settings import (
    ExternalModelApplied,
    ExternalModelDraft,
    ExternalModelDraftSelection,
    ExternalModelEditor,
    ExternalModelEditorReady,
    ExternalModelNoticeOutcome,
    ExternalModelOption,
    ExternalModelOptionPage,
    ExternalModelRejected,
    ExternalModelSettingsRejectionCode,
    ExternalModelStale,
    ExternalModelTargetContext,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import (
    ModelExecutionOptionDefinition,
    ModelExecutionOptionId,
)
from azents.services.external_channel.discord_model_settings import (
    discord_model_apply_response,
    discord_model_editor_response,
    discord_model_editor_result_response,
    discord_model_entry_presentation,
)
from azents.services.external_channel.discord_settings_scope import (
    parse_discord_model_settings_custom_id,
)

_NOW = datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC)
_DRAFT_ID = "01a03bfcc50a7891a94d3328bdbd8901"


def _option(*, option_id: str, label: str) -> ExternalModelOption:
    return ExternalModelOption(
        option_id=option_id,
        label=label,
        model_display_name=f"{label} model",
        reasoning_efforts=[
            ModelReasoningEffort.LOW,
            ModelReasoningEffort.HIGH,
        ],
        execution_options=[
            ModelExecutionOptionDefinition(
                id=ModelExecutionOptionId.FAST,
                label="Fast",
                description="Use faster processing.",
                cost_hint="Additional cost may apply.",
                control="boolean",
            )
        ],
    )


def _editor(
    *,
    offset: int = 10,
    selection_fingerprint: str = "0123456789abcdef",
) -> ExternalModelEditor:
    selected = _option(option_id="selected-option", label="Quality")
    return ExternalModelEditor(
        draft=ExternalModelDraft(
            id=_DRAFT_ID,
            owner_interaction_key="provider-interaction-1",
            target=ExternalModelTargetContext(
                binding_id="binding-1",
                session_id="session-1",
                agent_id="agent-1",
            ),
            expected_generation=4,
            selection=ExternalModelDraftSelection(
                option_id=selected.option_id,
                reasoning_effort=ModelReasoningEffort.HIGH,
                enabled_execution_options=[ModelExecutionOptionId.FAST],
            ),
            selection_fingerprint=selection_fingerprint,
            expires_at=_NOW + datetime.timedelta(minutes=15),
        ),
        scope_label="This Discord thread",
        current_profile=RequestedInferenceProfile(
            model_target_label="Balanced",
            reasoning_effort=ModelReasoningEffort.LOW,
            enabled_execution_options=[],
        ),
        current_generation=4,
        selected_option=selected,
        options=ExternalModelOptionPage(
            items=[
                _option(option_id="page-option-10", label="Fast page model"),
                _option(option_id="page-option-11", label="Smart page model"),
            ],
            offset=offset,
            limit=10,
            total_count=30,
        ),
    )


def _data(response: dict[str, object]) -> dict[str, object]:
    data = response["data"]
    assert isinstance(data, dict)
    return data


def _rows(response: dict[str, object]) -> list[dict[str, object]]:
    rows = _data(response)["components"]
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows)
    return rows


def _components(row: dict[str, object]) -> list[dict[str, object]]:
    components = row["components"]
    assert isinstance(components, list)
    assert all(isinstance(component, dict) for component in components)
    return components


def test_entry_is_exposed_only_for_ready_authorized_editor() -> None:
    """Bind the separate entry point to the backend-created private draft."""
    presentation = discord_model_entry_presentation(
        result=ExternalModelEditorReady(editor=_editor()),
        secret="secret",
    )

    assert presentation.summary == "Model: **Balanced**."
    button = _components(presentation.rows[0])[0]
    custom_id = button["custom_id"]
    assert isinstance(custom_id, str)
    scope = parse_discord_model_settings_custom_id(
        custom_id=custom_id,
        secret="secret",
    )
    assert scope.action == "open"
    assert scope.draft_id == _DRAFT_ID


def test_editor_keeps_selected_capabilities_visible_across_other_pages() -> None:
    """Use authoritative selected_option rather than requiring it on the page."""
    response = discord_model_editor_response(
        editor=_editor(offset=10),
        secret="secret",
    )

    assert response["type"] == 7
    rows = _rows(response)
    assert len(rows) == 4
    model_select = _components(rows[0])[0]
    model_options = model_select["options"]
    assert isinstance(model_options, list)
    assert all(
        option["default"] is False
        for option in model_options
        if isinstance(option, dict)
    )
    reasoning_select = _components(rows[1])[0]
    assert reasoning_select["placeholder"] == "Reasoning effort"
    execution_select = _components(rows[2])[0]
    assert execution_select["min_values"] == 0
    assert execution_select["max_values"] == 1
    controls = _components(rows[3])
    assert [control["label"] for control in controls] == [
        "Previous",
        "Next",
        "Apply",
        "Cancel",
    ]
    apply_custom_id = controls[2]["custom_id"]
    assert isinstance(apply_custom_id, str)
    apply_scope = parse_discord_model_settings_custom_id(
        custom_id=apply_custom_id,
        secret="secret",
    )
    assert apply_scope.action == "apply"
    assert apply_scope.selection_fingerprint == "0123456789abcdef"
    assert _data(response)["allowed_mentions"] == {"parse": []}


def test_stale_apply_refreshes_authoritative_editor_for_review() -> None:
    """Do not silently overwrite a newer shared generation."""
    response = discord_model_apply_response(
        result=ExternalModelStale(
            editor=_editor(selection_fingerprint="fedcba9876543210")
        ),
        secret="secret",
    )

    assert "changed after this screen opened" in str(_data(response)["content"])
    controls = _components(_rows(response)[-1])
    apply_custom_id = next(
        control["custom_id"] for control in controls if control.get("label") == "Apply"
    )
    assert isinstance(apply_custom_id, str)
    apply_scope = parse_discord_model_settings_custom_id(
        custom_id=apply_custom_id,
        secret="secret",
    )
    assert apply_scope.selection_fingerprint == "fedcba9876543210"


def test_removed_model_option_returns_private_refresh_guidance() -> None:
    """Map backend option removal to a safe no-save provider response."""
    response = discord_model_editor_result_response(
        result=ExternalModelRejected(
            code=ExternalModelSettingsRejectionCode.MODEL_OPTION_UNAVAILABLE
        ),
        secret="secret",
    )

    data = _data(response)
    assert "no longer available" in str(data["content"])
    assert data["components"] == []


def test_saved_result_distinguishes_notice_failure_without_resending() -> None:
    """Present the backend-owned notice outcome without another delivery plan."""
    response = discord_model_apply_response(
        result=ExternalModelApplied(
            editor=_editor(),
            created=True,
            mutation_id="mutation-1",
            notice_outcome=ExternalModelNoticeOutcome.FAILED,
        ),
        secret="secret",
    )

    data = _data(response)
    assert "was saved" in str(data["content"])
    assert "could not post" in str(data["content"])
    assert data["components"] == []
