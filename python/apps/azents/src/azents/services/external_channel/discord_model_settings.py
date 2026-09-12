"""Discord-native presentation for actor-private shared model drafts."""

from dataclasses import dataclass

from azents.core.external_model_settings import (
    ExternalModelApplied,
    ExternalModelApplyResult,
    ExternalModelBusy,
    ExternalModelCancelResult,
    ExternalModelDraftCancelled,
    ExternalModelEditor,
    ExternalModelEditorReady,
    ExternalModelEditorResult,
    ExternalModelNoticeOutcome,
    ExternalModelOption,
    ExternalModelRejected,
    ExternalModelSettingsRejectionCode,
    ExternalModelStale,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.services.external_channel.discord_settings_scope import (
    build_discord_model_settings_custom_id,
)

_MODEL_PAGE_SIZE = 10


@dataclass(frozen=True)
class DiscordModelSettingsPresentation:
    """Optional private model-editor entry point prepared from live authority."""

    summary: str | None
    rows: list[dict[str, object]]


def discord_model_entry_presentation(
    *,
    result: ExternalModelEditorResult,
    secret: str,
) -> DiscordModelSettingsPresentation:
    """Expose the separate model editor only for a live authorized draft."""
    if isinstance(result, ExternalModelEditorReady):
        editor = result.editor
        return DiscordModelSettingsPresentation(
            summary=f"Model: **{_current_model_label(editor)}**.",
            rows=[
                _button_row(
                    {
                        "type": 2,
                        "style": 2,
                        "label": "Edit conversation model",
                        "custom_id": build_discord_model_settings_custom_id(
                            secret=secret,
                            action="open",
                            draft_id=editor.draft.id,
                            offset=editor.options.offset,
                            selection_fingerprint=None,
                        ),
                    }
                )
            ],
        )
    if isinstance(result, (ExternalModelRejected, ExternalModelBusy)):
        return DiscordModelSettingsPresentation(summary=None, rows=[])
    raise AssertionError("Discord model editor result is not exhaustive.")


def discord_model_editor_response(
    *,
    editor: ExternalModelEditor,
    secret: str,
    status: str | None = None,
) -> dict[str, object]:
    """Render one complete typed draft without applying a selection."""
    description = (
        f"Scope: **{_discord_text(editor.scope_label, 160)}**\n"
        f"Current model: **{_current_model_label(editor)}**\n"
        f"Draft model: **{_draft_model_label(editor)}**\n"
        f"{editor.effect_notice}"
    )
    if status is not None:
        description = f"{status}\n\n{description}"
    return {
        "type": 7,
        "data": {
            "content": description,
            "embeds": [
                {
                    "title": "Conversation model",
                    "description": description,
                    "color": 0x5865F2,
                }
            ],
            "components": _editor_rows(editor=editor, secret=secret),
            "allowed_mentions": {"parse": []},
        },
    }


def discord_model_apply_response(
    *,
    result: ExternalModelApplyResult,
    secret: str,
) -> dict[str, object]:
    """Render authoritative Apply, stale refresh, or safe failure state."""
    if isinstance(result, ExternalModelApplied):
        if result.notice_outcome is ExternalModelNoticeOutcome.DELIVERED:
            notice = "The shared setting was saved and the conversation was notified."
        elif result.notice_outcome is ExternalModelNoticeOutcome.FAILED:
            notice = (
                "The shared setting was saved, but Discord could not post the "
                "conversation notice."
            )
        else:
            notice = (
                "The shared setting was saved. Discord notice delivery could not "
                "be confirmed."
            )
        return _model_terminal_response(
            title="Model settings saved",
            description=notice,
            color=0x57F287,
        )
    if isinstance(result, ExternalModelStale):
        return discord_model_editor_response(
            editor=result.editor,
            secret=secret,
            status=(
                "The conversation model changed after this screen opened. "
                "Current values are shown below; review and apply again."
            ),
        )
    if isinstance(result, ExternalModelRejected):
        return _model_rejected_response(result.code)
    if isinstance(result, ExternalModelBusy):
        return _model_terminal_response(
            title="Model settings busy",
            description="Azents is busy. Reopen settings and try again.",
            color=0x99AAB5,
        )
    raise AssertionError("Discord model Apply result is not exhaustive.")


def discord_model_cancel_response(
    result: ExternalModelCancelResult,
) -> dict[str, object]:
    """Confirm cancellation without changing the shared conversation."""
    if isinstance(result, ExternalModelDraftCancelled):
        return _model_terminal_response(
            title="Model changes discarded",
            description="The draft was discarded. No conversation setting changed.",
            color=0x99AAB5,
        )
    if isinstance(result, ExternalModelRejected):
        return _model_rejected_response(result.code)
    if isinstance(result, ExternalModelBusy):
        return _model_terminal_response(
            title="Model settings busy",
            description="Azents is busy. Reopen settings and try again.",
            color=0x99AAB5,
        )
    raise AssertionError("Discord model cancellation result is not exhaustive.")


def discord_model_editor_result_response(
    *,
    result: ExternalModelEditorResult,
    secret: str,
) -> dict[str, object]:
    """Render a draft update/page result or its safe private failure."""
    if isinstance(result, ExternalModelEditorReady):
        return discord_model_editor_response(editor=result.editor, secret=secret)
    if isinstance(result, ExternalModelRejected):
        return _model_rejected_response(result.code)
    if isinstance(result, ExternalModelBusy):
        return _model_terminal_response(
            title="Model settings busy",
            description="Azents is busy. Reopen settings and try again.",
            color=0x99AAB5,
        )
    raise AssertionError("Discord model editor result is not exhaustive.")


def selected_model_option(editor: ExternalModelEditor) -> ExternalModelOption:
    """Return the authoritative selected option independent of catalog paging."""
    return editor.selected_option


def parse_reasoning_effort(value: str | None) -> ModelReasoningEffort | None:
    """Decode the provider sentinel or one supported reasoning value."""
    if value == "default":
        return None
    if value is None:
        raise ValueError("Discord model reasoning selection is invalid.")
    try:
        return ModelReasoningEffort(value)
    except ValueError as error:
        raise ValueError("Discord model reasoning selection is invalid.") from error


def model_page_size() -> int:
    """Return the private provider page size used by Discord controls."""
    return _MODEL_PAGE_SIZE


def discord_model_invalid_selection_response() -> dict[str, object]:
    """Reject malformed provider values without invoking model authority."""
    return _model_terminal_response(
        title="Model settings unavailable",
        description="That model selection is invalid. Reopen settings.",
        color=0x99AAB5,
    )


def _editor_rows(
    *,
    editor: ExternalModelEditor,
    secret: str,
) -> list[dict[str, object]]:
    page = editor.options
    draft = editor.draft
    rows: list[dict[str, object]] = []
    if page.items:
        rows.append(
            _select_row(
                custom_id=build_discord_model_settings_custom_id(
                    secret=secret,
                    action="select_model",
                    draft_id=draft.id,
                    offset=page.offset,
                    selection_fingerprint=None,
                ),
                placeholder="Choose model",
                min_values=1,
                max_values=1,
                options=[
                    {
                        "label": _discord_text(option.label, 100),
                        "description": _discord_text(option.model_display_name, 100),
                        "value": option.option_id,
                        "default": option.option_id == draft.selection.option_id,
                    }
                    for option in page.items
                ],
            )
        )
    selected_option = selected_model_option(editor)
    if selected_option is not None:
        reasoning_options: list[dict[str, object]] = [
            {
                "label": "Default",
                "value": "default",
                "default": draft.selection.reasoning_effort is None,
            }
        ]
        reasoning_options.extend(
            [
                {
                    "label": _reasoning_label(effort),
                    "value": effort.value,
                    "default": draft.selection.reasoning_effort is effort,
                }
                for effort in selected_option.reasoning_efforts
            ]
        )
        rows.append(
            _select_row(
                custom_id=build_discord_model_settings_custom_id(
                    secret=secret,
                    action="select_reasoning",
                    draft_id=draft.id,
                    offset=page.offset,
                    selection_fingerprint=None,
                ),
                placeholder="Reasoning effort",
                min_values=1,
                max_values=1,
                options=reasoning_options[:25],
            )
        )
        execution_options = selected_option.execution_options
        if execution_options:
            enabled = set(draft.selection.enabled_execution_options)
            rows.append(
                _select_row(
                    custom_id=build_discord_model_settings_custom_id(
                        secret=secret,
                        action="select_execution",
                        draft_id=draft.id,
                        offset=page.offset,
                        selection_fingerprint=None,
                    ),
                    placeholder="Execution options",
                    min_values=0,
                    max_values=len(execution_options),
                    options=[
                        {
                            "label": _discord_text(option.label, 100),
                            "description": _discord_text(
                                f"{option.description} {option.cost_hint}",
                                100,
                            ),
                            "value": option.id.value,
                            "default": option.id in enabled,
                        }
                        for option in execution_options
                    ],
                )
            )
    controls: list[dict[str, object]] = []
    if page.total_count > page.limit:
        controls.append(
            {
                "type": 2,
                "style": 2,
                "label": "Previous",
                "custom_id": build_discord_model_settings_custom_id(
                    secret=secret,
                    action="previous_page",
                    draft_id=draft.id,
                    offset=max(0, page.offset - page.limit),
                    selection_fingerprint=None,
                ),
                "disabled": page.offset == 0,
            }
        )
        controls.append(
            {
                "type": 2,
                "style": 2,
                "label": "Next",
                "custom_id": build_discord_model_settings_custom_id(
                    secret=secret,
                    action="next_page",
                    draft_id=draft.id,
                    offset=page.offset + page.limit,
                    selection_fingerprint=None,
                ),
                "disabled": page.offset + page.limit >= page.total_count,
            }
        )
    controls.append(
        {
            "type": 2,
            "style": 1,
            "label": "Apply",
            "custom_id": build_discord_model_settings_custom_id(
                secret=secret,
                action="apply",
                draft_id=draft.id,
                offset=page.offset,
                selection_fingerprint=draft.selection_fingerprint,
            ),
        }
    )
    controls.append(
        {
            "type": 2,
            "style": 2,
            "label": "Cancel",
            "custom_id": build_discord_model_settings_custom_id(
                secret=secret,
                action="cancel",
                draft_id=draft.id,
                offset=page.offset,
                selection_fingerprint=None,
            ),
        }
    )
    rows.append(_button_row(*controls))
    return rows[:5]


def _select_row(
    *,
    custom_id: str,
    placeholder: str,
    min_values: int,
    max_values: int,
    options: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "type": 1,
        "components": [
            {
                "type": 3,
                "custom_id": custom_id,
                "placeholder": placeholder,
                "min_values": min_values,
                "max_values": max_values,
                "options": options,
            }
        ],
    }


def _model_rejected_response(
    code: ExternalModelSettingsRejectionCode,
) -> dict[str, object]:
    descriptions = {
        ExternalModelSettingsRejectionCode.ACTOR_MISMATCH: (
            "This model control is unavailable. Reopen settings."
        ),
        ExternalModelSettingsRejectionCode.DRAFT_EXPIRED: (
            "This model draft expired. Reopen settings."
        ),
        ExternalModelSettingsRejectionCode.DRAFT_NOT_FOUND: (
            "This model draft is unavailable. Reopen settings."
        ),
        ExternalModelSettingsRejectionCode.LINK_REQUIRED: (
            "Link your Azents account from settings before editing the model."
        ),
        ExternalModelSettingsRejectionCode.ACCOUNT_UNAVAILABLE: (
            "Your linked Azents account is unavailable."
        ),
        ExternalModelSettingsRejectionCode.MEMBERSHIP_REQUIRED: (
            "Workspace membership is required to edit the conversation model."
        ),
        ExternalModelSettingsRejectionCode.PARTICIPATION_DENIED: (
            "You cannot edit the model for this conversation."
        ),
        ExternalModelSettingsRejectionCode.TARGET_UNAVAILABLE: (
            "This conversation no longer has an editable model target."
        ),
        ExternalModelSettingsRejectionCode.MODEL_OPTION_UNAVAILABLE: (
            "That model option is no longer available. Reopen settings."
        ),
    }
    return _model_terminal_response(
        title="Model settings unavailable",
        description=descriptions[code],
        color=0x99AAB5,
    )


def _model_terminal_response(
    *,
    title: str,
    description: str,
    color: int,
) -> dict[str, object]:
    return {
        "type": 7,
        "data": {
            "content": description,
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": color,
                }
            ],
            "components": [],
            "allowed_mentions": {"parse": []},
        },
    }


def _current_model_label(editor: ExternalModelEditor) -> str:
    profile = editor.current_profile
    if profile is None:
        return "Agent default"
    return _discord_text(profile.model_target_label, 80)


def _draft_model_label(editor: ExternalModelEditor) -> str:
    option = selected_model_option(editor)
    if option is None:
        return "Selected option on another page"
    return _discord_text(option.label, 80)


def _reasoning_label(effort: ModelReasoningEffort) -> str:
    return effort.value.replace("xhigh", "Extra high").replace("_", " ").title()


def _button_row(*buttons: dict[str, object]) -> dict[str, object]:
    return {"type": 1, "components": list(buttons)}


def _discord_text(value: str, limit: int) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("*", "_", "`", "~", "|", ">", "#"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped[:limit]
