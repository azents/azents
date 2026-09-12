"""Actor-private Slack linking and independent model draft presentation."""

from dataclasses import replace

from azents.core.external_account_link import ExternalAccountLinkState
from azents.core.external_model_settings import ExternalModelEditor
from azents.services.external_channel.slack_events import SlackInteractionView
from azents.services.external_channel.slack_native_protocol import (
    SlackNativeScope,
    sign_native_scope,
)


def _text(value: str) -> dict[str, object]:
    return {"type": "plain_text", "text": value, "emoji": False}


def _section(value: str) -> dict[str, object]:
    return {"type": "section", "text": _text(value[:3000])}


def _button(label: str, action: str, metadata: str) -> dict[str, object]:
    return {
        "type": "button",
        "text": _text(label),
        "action_id": action,
        "value": metadata,
    }


def private_notice(message: str) -> SlackInteractionView:
    """Render an actor-only notice with no channel or account disclosure."""
    return SlackInteractionView(
        callback_id="azents_personal_notice",
        title="Personal settings",
        private_metadata="completed",
        blocks=[_section(message)],
        submit_title=None,
        close_title="Close",
    )


def add_personal_controls(
    view: SlackInteractionView,
    *,
    metadata: str,
    management_url: str,
    link_state: ExternalAccountLinkState | None,
    model_metadata: str | None,
) -> SlackInteractionView:
    """Append optional controls without changing the guest form or submission."""
    controls: list[dict[str, object]] = []
    if link_state in {
        ExternalAccountLinkState.ACTIVE,
        ExternalAccountLinkState.INACTIVE,
    }:
        controls.append(
            {
                "type": "button",
                "text": _text("Manage connected account"),
                "url": management_url,
            }
        )
    else:
        controls.append(
            _button(
                "Connect Azents account · optional",
                "azents_account_link_start",
                metadata,
            )
        )
    if model_metadata is not None:
        controls.append(
            _button("Edit shared model", "azents_model_open", model_metadata)
        )
    if link_state == ExternalAccountLinkState.ACTIVE:
        status_text = "Account connected"
    elif link_state == ExternalAccountLinkState.INACTIVE:
        status_text = "Account connection inactive. Manage your account in Azents."
    else:
        status_text = (
            "Account linking is optional. Existing guest access stays unchanged."
        )
    return replace(
        view,
        blocks=[
            *view.blocks,
            {"type": "divider"},
            {
                "type": "context",
                "elements": [_text(status_text)],
            },
            {"type": "actions", "elements": controls},
        ],
    )


def link_code_view(
    *, metadata: str, web_url: str, notice: str | None
) -> SlackInteractionView:
    """Collect a code privately; never echo it into modal metadata or labels."""
    blocks: list[dict[str, object]] = [
        _section(
            "Connect your Azents account (optional). Open Azents, check the account "
            "and Workspace, and create a verification code. Enter that code here "
            "using this same Slack identity. "
            "Then return to Azents for final confirmation."
        ),
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": _text("Open Azents to connect"),
                    "url": web_url,
                }
            ],
        },
        {
            "type": "input",
            "block_id": "azents_account_link_code",
            "label": _text("Verification code"),
            "element": {
                "type": "plain_text_input",
                "action_id": "value",
                "min_length": 1,
                "max_length": 128,
            },
        },
        {
            "type": "context",
            "elements": [
                _text(
                    "Linking does not change guest access "
                    "or shared conversation settings."
                )
            ],
        },
    ]
    if notice is not None:
        blocks.insert(0, _section(notice))
    return SlackInteractionView(
        callback_id="azents_account_link_code",
        title="Connect Azents account",
        private_metadata=metadata,
        blocks=blocks,
        submit_title="Verify code",
        close_title="Cancel",
    )


def _option(label: str, value: str) -> dict[str, object]:
    return {"text": _text(label[:75]), "value": value}


def model_editor_view(
    editor: ExternalModelEditor,
    *,
    scope: SlackNativeScope,
    secret: str,
    notice: str | None,
) -> SlackInteractionView:
    """Render an explicit Apply draft with full paging and supported controls."""
    scope = scope.model_copy(
        update={
            "draft_id": editor.draft.id,
            "offset": editor.options.offset,
            "selection_fingerprint": editor.draft.selection_fingerprint,
        }
    )
    metadata = sign_native_scope(scope, secret=secret)
    selected = editor.selected_option
    selection = editor.draft.selection
    blocks: list[dict[str, object]] = [
        _section(editor.scope_label),
        _section(editor.effect_notice),
    ]
    if editor.current_profile is None:
        blocks.append(_section("Current applied profile: Agent default"))
    else:
        profile = editor.current_profile
        enabled = (
            ", ".join(option.value for option in profile.enabled_execution_options)
            or "none"
        )
        blocks.append(
            _section(
                f"Current applied profile: {profile.model_target_label} · "
                f"reasoning {profile.reasoning_effort or 'default'} · "
                f"execution options {enabled}"
            )
        )
    blocks.append(
        _section(f"Unsaved draft: {selected.label} — {selected.model_display_name}")
    )
    if notice is not None:
        blocks.insert(0, _section(notice))
    options = [_option(item.label, item.option_id) for item in editor.options.items]
    if options:
        element: dict[str, object] = {
            "type": "static_select",
            "action_id": "azents_model_select",
            "options": options,
            "placeholder": _text("Choose an authorized model"),
        }
        if any(item.option_id == selected.option_id for item in editor.options.items):
            element["initial_option"] = _option(selected.label, selected.option_id)
        blocks.append(
            {"type": "section", "text": _text("Draft model"), "accessory": element}
        )
    page = editor.options
    navigation: list[dict[str, object]] = []
    if page.offset > 0:
        navigation.append(_button("Previous models", "azents_model_previous", metadata))
    if page.offset + page.limit < page.total_count:
        navigation.append(_button("Next models", "azents_model_next", metadata))
    blocks.append(
        {
            "type": "context",
            "elements": [
                _text(
                    f"Models {min(page.offset + 1, page.total_count)}–"
                    f"{min(page.offset + page.limit, page.total_count)} "
                    f"of {page.total_count}"
                )
            ],
        }
    )
    if navigation:
        blocks.append({"type": "actions", "elements": navigation})
    if selected.reasoning_efforts:
        efforts = [
            _option("Model default", "default"),
            *[
                _option(value.value, value.value)
                for value in selected.reasoning_efforts
            ],
        ]
        current = selection.reasoning_effort
        blocks.append(
            {
                "type": "section",
                "text": _text("Draft reasoning effort"),
                "accessory": {
                    "type": "static_select",
                    "action_id": "azents_model_effort",
                    "options": efforts,
                    "initial_option": _option(
                        current.value if current else "Model default",
                        current.value if current else "default",
                    ),
                },
            }
        )
    if selected.execution_options:
        execution: dict[str, object] = {
            "type": "checkboxes",
            "action_id": "azents_model_execution",
            "options": [
                _option(item.label, item.id.value)
                for item in selected.execution_options
            ],
        }
        initial = [
            _option(item.label, item.id.value)
            for item in selected.execution_options
            if item.id in selection.enabled_execution_options
        ]
        if initial:
            execution["initial_options"] = initial
        blocks.append({"type": "actions", "elements": [execution]})
        for item in selected.execution_options:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        _text(f"{item.label}: {item.description} {item.cost_hint}")
                    ],
                }
            )
    blocks.append(
        {
            "type": "actions",
            "elements": [_button("Discard draft", "azents_model_cancel", metadata)],
        }
    )
    return SlackInteractionView(
        callback_id="azents_model_apply",
        title="Shared model settings",
        private_metadata=metadata,
        blocks=blocks,
        submit_title="Apply",
        close_title="Cancel",
    )
