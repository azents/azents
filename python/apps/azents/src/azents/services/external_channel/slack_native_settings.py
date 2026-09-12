"""Slack-only orchestration of private account and shared-model controls."""

import datetime
import logging
from dataclasses import dataclass
from typing import Annotated, assert_never
from urllib.parse import urlsplit

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.external_account_link import (
    ExternalAccountLinkError,
    ExternalAccountLinkInvalidCode,
    ExternalAccountLinkState,
    VerifiedExternalAccountActor,
)
from azents.core.external_model_settings import (
    ExternalModelActorContext,
    ExternalModelDraftSelection,
    ExternalModelNoticeOutcome,
    ExternalModelTargetContext,
)
from azents.services.external_account_link import ExternalAccountLinkService
from azents.services.external_channel.model_settings import ExternalModelSettingsService
from azents.services.external_channel.participation import (
    ExternalChannelParticipationSettings,
)
from azents.services.external_channel.slack_events import SlackInteractionView
from azents.services.external_channel.slack_native_protocol import (
    SlackNativeControl,
    SlackNativeScope,
    sign_native_scope,
)
from azents.services.external_channel.slack_native_views import (
    add_personal_controls,
    link_code_view,
    model_editor_view,
    private_notice,
)

_MODEL_PAGE_SIZE = 10
logger = logging.getLogger(__name__)


def _model_actor(actor: VerifiedExternalAccountActor) -> ExternalModelActorContext:
    return ExternalModelActorContext(
        provider=actor.provider,
        connection_id=actor.connection_id,
        configuration_generation=actor.connection_configuration_generation,
        principal_id=actor.principal_id,
        provider_tenant_id=actor.provider_tenant_id,
        provider_user_id=actor.provider_user_id,
        provider_display_name=actor.provider_display_label,
    )


@dataclass
class SlackNativeSettingsService:
    """Sequence completed domain operations before actor-private presentation."""

    linking: Annotated[ExternalAccountLinkService, Depends(ExternalAccountLinkService)]
    models: Annotated[
        ExternalModelSettingsService, Depends(ExternalModelSettingsService)
    ]
    config: Annotated[Config, Depends(get_config)]

    def web_url(self, path: str) -> str:
        """Use only the deployment web origin and service-owned relative paths."""
        base = self.config.web_url.rstrip("/")
        parsed = urlsplit(base)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("Azents web navigation is not configured.")
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Azents web navigation is unavailable.")
        return base + path

    async def decorate(
        self,
        *,
        view: SlackInteractionView,
        actor: VerifiedExternalAccountActor,
        settings: ExternalChannelParticipationSettings | None,
        now: datetime.datetime,
    ) -> SlackInteractionView:
        """Keep existing guest submission independent from personal authority."""
        scope = SlackNativeScope(
            connection_id=actor.connection_id,
            principal_id=actor.principal_id,
            channel_id=actor.provider_channel_id,
            thread_id=actor.provider_thread_id,
            expires_at=now + datetime.timedelta(minutes=15),
            origin_id=None,
            draft_id=None,
            selection_fingerprint=None,
            offset=0,
        )
        try:
            state = await self.linking.get_native_link_state(actor=actor, now=now)
        except ExternalAccountLinkError:
            return view
        linked = (
            state.link is not None
            and state.link.state == ExternalAccountLinkState.ACTIVE
        )
        model_metadata = None
        if (
            linked
            and settings is not None
            and settings.binding is not None
            and settings.session_navigation is not None
        ):
            binding = settings.binding
            editor = await self.models.open_editor(
                actor=_model_actor(actor),
                target=ExternalModelTargetContext(
                    binding_id=binding.id,
                    session_id=binding.agent_session_id,
                    agent_id=settings.session_navigation.agent_id,
                ),
                owner_interaction_key=actor.provider_interaction_id,
                now=now,
                offset=0,
                limit=_MODEL_PAGE_SIZE,
            )
            match editor.kind:
                case "ready":
                    model_metadata = sign_native_scope(
                        scope.model_copy(update={"draft_id": editor.editor.draft.id}),
                        secret=self.config.auth.jwt.secret_key,
                    )
                case "rejected":
                    logger.info(
                        "External model editor authorization rejected",
                        extra={
                            "external_model_rejection_code": editor.code.value,
                            "connection_id": actor.connection_id,
                            "binding_id": binding.id,
                            "session_id": binding.agent_session_id,
                        },
                    )
                case "busy":
                    logger.info(
                        "External model editor authorization busy",
                        extra={
                            "connection_id": actor.connection_id,
                            "binding_id": binding.id,
                            "session_id": binding.agent_session_id,
                        },
                    )
                case _ as unreachable:
                    assert_never(unreachable)
        try:
            management_url = self.web_url(state.management_path)
        except ValueError:
            return view
        return add_personal_controls(
            view,
            metadata=sign_native_scope(scope, secret=self.config.auth.jwt.secret_key),
            management_url=management_url,
            link_state=state.link.state if state.link is not None else None,
            model_metadata=model_metadata,
        )

    async def process(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        scope: SlackNativeScope,
        control: SlackNativeControl,
        now: datetime.datetime,
    ) -> SlackInteractionView:
        """Reauthorize every action; proof stays exclusively request-local."""
        if (
            scope.connection_id != actor.connection_id
            or scope.principal_id != actor.principal_id
        ):
            return private_notice(
                "This private control is unavailable. Reopen your own settings."
            )
        if control.action.startswith("azents_account_link"):
            return await self._link(actor=actor, scope=scope, control=control, now=now)
        return await self._model(actor=actor, scope=scope, control=control, now=now)

    async def _link(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        scope: SlackNativeScope,
        control: SlackNativeControl,
        now: datetime.datetime,
    ) -> SlackInteractionView:
        try:
            if control.action == "azents_account_link_start":
                origin = await self.linking.create_origin(actor=actor, now=now)
                scope = scope.model_copy(
                    update={
                        "origin_id": origin.origin_id,
                        "expires_at": origin.expires_at,
                    }
                )
                return link_code_view(
                    metadata=sign_native_scope(
                        scope, secret=self.config.auth.jwt.secret_key
                    ),
                    web_url=self.web_url(origin.web_path),
                    notice=None,
                )
            if scope.origin_id is None:
                return private_notice(
                    "This connection request is unavailable. Reopen settings."
                )
            if control.action == "azents_account_link_code_open":
                return link_code_view(
                    metadata=sign_native_scope(
                        scope, secret=self.config.auth.jwt.secret_key
                    ),
                    web_url=self.web_url(f"/external-channel/link/{scope.origin_id}"),
                    notice=None,
                )
            if control.action != "azents_account_link_code" or control.code is None:
                return private_notice(
                    "This connection request is unavailable. Reopen settings."
                )
            await self.linking.verify_candidate_code(
                actor=actor, origin_id=scope.origin_id, code=control.code, now=now
            )
            return private_notice(
                "Slack identity verified. Return to Azents, check the account and "
                "Workspace, and explicitly confirm the connection. "
                "Shared settings have not changed."
            )
        except ExternalAccountLinkInvalidCode as error:
            return link_code_view(
                metadata=sign_native_scope(
                    scope, secret=self.config.auth.jwt.secret_key
                ),
                web_url=self.web_url(f"/external-channel/link/{scope.origin_id}"),
                notice=(
                    "The code could not be verified. "
                    f"{error.remaining_attempts} attempts remain."
                ),
            )
        except ExternalAccountLinkError:
            return private_notice(
                "This connection request is unavailable or expired. "
                "Reopen settings to try again. Existing guest access is unchanged."
            )

    async def _model(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        scope: SlackNativeScope,
        control: SlackNativeControl,
        now: datetime.datetime,
    ) -> SlackInteractionView:
        if scope.draft_id is None:
            return private_notice("Model settings are unavailable. Reopen settings.")
        model_actor = _model_actor(actor)
        if control.action == "azents_model_cancel":
            cancelled = await self.models.cancel_draft(
                actor=model_actor, draft_id=scope.draft_id, now=now
            )
            match cancelled.kind:
                case "cancelled":
                    return private_notice(
                        "Draft discarded. Shared settings have not changed."
                    )
                case "rejected" | "busy":
                    return private_notice(
                        "The draft is unavailable. Shared settings have not changed."
                    )
                case _ as unreachable:
                    assert_never(unreachable)
        if control.action == "azents_model_apply":
            if scope.selection_fingerprint is None:
                return private_notice(
                    "The displayed draft is unavailable. Nothing was saved. "
                    "Reopen model settings."
                )
            applied = await self.models.apply_draft(
                actor=model_actor,
                draft_id=scope.draft_id,
                apply_interaction_key=actor.provider_interaction_id,
                expected_selection_fingerprint=scope.selection_fingerprint,
                now=now,
            )
            match applied.kind:
                case "applied":
                    notice = (
                        "Saved for the whole conversation. "
                        "Only new model calls use these settings."
                    )
                    if applied.notice_outcome != ExternalModelNoticeOutcome.DELIVERED:
                        notice += (
                            " The shared notification could not be confirmed; "
                            "your settings are saved."
                        )
                    return model_editor_view(
                        applied.editor,
                        scope=scope,
                        secret=self.config.auth.jwt.secret_key,
                        notice=notice,
                    )
                case "stale":
                    return model_editor_view(
                        applied.editor,
                        scope=scope,
                        secret=self.config.auth.jwt.secret_key,
                        notice=(
                            "Settings changed since this draft opened. "
                            "Nothing was saved. "
                            "Review the refreshed current settings and choose again."
                        ),
                    )
                case "rejected":
                    return private_notice(
                        "Model access or conversation state changed. "
                        "Nothing was saved. Reopen settings."
                    )
                case "busy":
                    return private_notice(
                        "Settings are busy. Nothing was saved. "
                        "Reopen settings and try again."
                    )
                case _ as unreachable:
                    assert_never(unreachable)
        offset = scope.offset
        if control.action == "azents_model_previous":
            offset = max(0, offset - _MODEL_PAGE_SIZE)
        elif control.action == "azents_model_next":
            offset += _MODEL_PAGE_SIZE
        result = await self.models.page_options(
            actor=model_actor,
            draft_id=scope.draft_id,
            now=now,
            offset=offset,
            limit=_MODEL_PAGE_SIZE,
        )
        if result.kind == "ready" and control.action in {
            "azents_model_select",
            "azents_model_effort",
            "azents_model_execution",
        }:
            previous = result.editor.draft.selection
            selection = ExternalModelDraftSelection(
                option_id=control.option_id
                if control.action == "azents_model_select" and control.option_id
                else previous.option_id,
                reasoning_effort=control.reasoning_effort
                if control.action == "azents_model_effort"
                else previous.reasoning_effort,
                enabled_execution_options=control.execution_options
                if control.action == "azents_model_execution"
                and control.execution_options is not None
                else previous.enabled_execution_options,
            )
            result = await self.models.update_draft(
                actor=model_actor,
                draft_id=scope.draft_id,
                selection=selection,
                now=now,
                offset=offset,
                limit=_MODEL_PAGE_SIZE,
            )
        match result.kind:
            case "ready":
                return model_editor_view(
                    result.editor,
                    scope=scope,
                    secret=self.config.auth.jwt.secret_key,
                    notice=None,
                )
            case "rejected":
                return private_notice(
                    "Model settings are unavailable or expired. Reopen settings. "
                    "Shared settings have not changed."
                )
            case "busy":
                return private_notice(
                    "Settings are busy. Reopen settings and try again. "
                    "Shared settings have not changed."
                )
            case _ as unreachable:
                assert_never(unreachable)
