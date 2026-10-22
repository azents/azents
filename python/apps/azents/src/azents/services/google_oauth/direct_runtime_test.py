"""Direct-operation admission follows actual scopes and current service switches."""

import dataclasses
import datetime

import pytest

from azents.core.google_oauth import GoogleOAuthError
from azents.core.google_policy import GoogleService, GoogleToolGroup
from azents.core.google_tool_groups import group_request_scopes, groups_for_services
from azents.core.google_workspace_policy import GoogleWorkspaceOperation as Op
from azents.core.tools import GoogleToolkitConfig
from azents.services.google_oauth.runtime_test import _harness
from azents.services.google_workspace.gmail import compose_prerequisites
from azents.services.google_workspace.gmail_models import (
    GmailCompose,
    GmailDraftContext,
)


async def test_broad_actual_grant_admits_write_under_readonly_request_intent() -> None:
    h = _harness(expired=False)
    current = dataclasses.replace(
        h.current,
        config=GoogleToolkitConfig(
            services=(GoogleService.GMAIL,),
            oauth_request_scopes=("https://www.googleapis.com/auth/gmail.readonly",),
            timeout=h.current.config.timeout,
            tool_groups=groups_for_services((GoogleService.GMAIL,)),
        ),
        connection=dataclasses.replace(
            h.current.connection,
            candidate=h.current.connection.candidate.model_copy(
                update={
                    "tokens": h.current.connection.candidate.tokens.model_copy(
                        update={
                            "granted_scopes": (
                                "https://www.googleapis.com/auth/gmail.modify",
                            )
                        }
                    )
                }
            ),
        ),
    )
    h.repo.load.return_value = current
    assert Op.GMAIL_SEND_MESSAGE in await h.service.direct_operations(
        h.owner, "toolkit"
    )
    receipt = await h.service.authorize_operation(
        h.owner, "toolkit", Op.GMAIL_SEND_MESSAGE, ()
    )
    assert receipt.snapshot == current
    h.provider.refresh.assert_not_awaited()


async def test_unselected_write_is_denied_despite_broad_actual_grant() -> None:
    h = _harness(expired=False)
    current = dataclasses.replace(
        h.current,
        config=h.current.config.model_copy(
            update={"tool_groups": (GoogleToolGroup.CALENDAR_READ,)}
        ),
        connection=dataclasses.replace(
            h.current.connection,
            candidate=h.current.connection.candidate.model_copy(
                update={
                    "tokens": h.current.connection.candidate.tokens.model_copy(
                        update={
                            "granted_scopes": (
                                "https://www.googleapis.com/auth/calendar",
                            )
                        }
                    )
                }
            ),
        ),
    )
    h.repo.load.return_value = current
    assert Op.CALENDAR_GET_EVENT in await h.service.direct_operations(
        h.owner, "toolkit"
    )
    assert Op.CALENDAR_CREATE_EVENT not in await h.service.direct_operations(
        h.owner, "toolkit"
    )
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.authorize_operation(
            h.owner, "toolkit", Op.CALENDAR_CREATE_EVENT, ()
        )
    assert error.value.code == "capability_unavailable"
    h.provider.refresh.assert_not_awaited()


async def test_group_narrowing_blocks_a_previously_admitted_operation() -> None:
    h = _harness(expired=False)
    admitted = await h.service.authorize_operation(
        h.owner, "toolkit", Op.CALENDAR_GET_EVENT, ()
    )
    h.repo.load.return_value = dataclasses.replace(
        h.current,
        config=h.current.config.model_copy(update={"tool_groups": ()}),
    )
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.recheck_operation(admitted)
    assert error.value.code == "capability_unavailable"


@pytest.mark.parametrize(
    "group", [GoogleToolGroup.GMAIL_DRAFTS, GoogleToolGroup.GMAIL_SEND]
)
@pytest.mark.parametrize("variant", ["ordinary", "alias", "reply", "forward"])
async def test_selected_compose_groups_admit_supported_argument_prerequisites(
    group: GoogleToolGroup, variant: str
) -> None:
    h = _harness(expired=False)
    scopes = group_request_scopes((group,))
    current = dataclasses.replace(
        h.current,
        config=GoogleToolkitConfig(
            services=(GoogleService.GMAIL,),
            tool_groups=(group,),
            oauth_request_scopes=scopes,
            timeout=30,
        ),
        connection=dataclasses.replace(
            h.current.connection,
            candidate=h.current.connection.candidate.model_copy(
                update={
                    "tokens": h.current.connection.candidate.tokens.model_copy(
                        update={"granted_scopes": scopes}
                    )
                }
            ),
        ),
    )
    h.repo.load.return_value = current
    message = GmailCompose.model_validate(
        {
            "sender": {"email": "alias@example.com", "display_name": None}
            if variant == "alias"
            else None,
            "to": [{"email": "recipient@example.com", "display_name": None}],
            "cc": [],
            "bcc": [],
            "reply_to": [],
            "subject": "Subject",
            "text": "Body",
            "html": None,
            "body_file": None,
            "body_file_format": None,
            "attachments": [],
        }
    )
    context = (
        GmailDraftContext(
            mode=variant,
            source_message_id="source",
            reply_all=False,
            quote_original=True,
            reuse_source_attachments=True,
        )
        if variant in ("reply", "forward")
        else None
    )
    operation = (
        Op.GMAIL_CREATE_DRAFT
        if group is GoogleToolGroup.GMAIL_DRAFTS
        else Op.GMAIL_SEND_MESSAGE
    )
    admitted = await h.service.authorize_operation(
        h.owner,
        "toolkit",
        operation,
        lambda email: compose_prerequisites(message, context, email),
    )
    assert admitted.operation is operation
    h.provider.refresh.assert_not_awaited()


async def test_actual_scope_denial_precedes_refresh() -> None:
    h = _harness(expired=True)
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.authorize_operation(
            h.owner, "toolkit", Op.CALENDAR_CREATE_EVENT, ()
        )
    assert error.value.code == "capability_unavailable"
    h.provider.refresh.assert_not_awaited()


async def test_argument_prerequisite_admission_precedes_refresh() -> None:
    h = _harness(expired=True)
    identities: list[str | None] = []

    def prerequisites(email: str | None) -> tuple[Op, ...]:
        identities.append(email)
        return (Op.CALENDAR_CREATE_EVENT,)

    with pytest.raises(GoogleOAuthError) as error:
        await h.service.authorize_operation(
            h.owner, "toolkit", Op.CALENDAR_GET_EVENT, prerequisites
        )
    assert error.value.code == "capability_unavailable"
    assert identities == [h.current.connection.candidate.identity.email]
    h.provider.refresh.assert_not_awaited()


async def test_post_renewal_scope_reduction_denies_operation() -> None:
    h = _harness(expired=True)
    reduced = dataclasses.replace(
        h.current,
        connection=dataclasses.replace(
            h.current.connection,
            candidate=h.current.connection.candidate.model_copy(
                update={
                    "tokens": h.current.connection.candidate.tokens.model_copy(
                        update={
                            "granted_scopes": (),
                            "expires_at": datetime.datetime.now(datetime.UTC)
                            + datetime.timedelta(hours=1),
                        }
                    )
                }
            ),
        ),
    )
    h.repo.load.side_effect = [h.current, reduced, reduced]
    h.provider.refresh.return_value = reduced.connection.candidate.tokens
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.authorize_operation(
            h.owner, "toolkit", Op.CALENDAR_GET_EVENT, ()
        )
    assert error.value.code == "capability_unavailable"
    h.provider.refresh.assert_awaited_once()


async def test_auxiliary_operations_require_their_own_enabled_service_and_scopes() -> (
    None
):
    h = _harness(expired=False)
    with pytest.raises(GoogleOAuthError):
        await h.service.authorize_operation(
            h.owner, "toolkit", Op.CALENDAR_GET_EVENT, (Op.GMAIL_GET_MESSAGE,)
        )
    h.provider.refresh.assert_not_awaited()


@pytest.mark.parametrize(
    "change", ["revision", "config", "connection", "token", "registration", "expiry"]
)
async def test_captured_receipt_rechecks_every_current_fence_without_refresh(
    change: str,
) -> None:
    h = _harness(expired=False)
    receipt = await h.service.authorize_operation(
        h.owner, "toolkit", Op.CALENDAR_GET_EVENT, ()
    )
    match change:
        case "revision":
            changed = dataclasses.replace(h.current, revision=h.current.revision + 1)
        case "config":
            changed = dataclasses.replace(
                h.current, config=h.current.config.model_copy(update={"timeout": 42})
            )
        case "connection":
            changed = dataclasses.replace(
                h.current,
                connection=dataclasses.replace(h.current.connection, id="new-grant"),
            )
        case "token":
            changed = dataclasses.replace(
                h.current,
                connection=dataclasses.replace(
                    h.current.connection, encrypted_payload="new-encrypted"
                ),
            )
        case "registration":
            changed = dataclasses.replace(
                h.current,
                registration=dataclasses.replace(
                    h.current.registration, effective_generation="new-generation"
                ),
            )
        case "expiry":
            changed = dataclasses.replace(
                h.current,
                connection=dataclasses.replace(
                    h.current.connection,
                    candidate=h.current.connection.candidate.model_copy(
                        update={
                            "tokens": h.current.connection.candidate.tokens.model_copy(
                                update={
                                    "expires_at": datetime.datetime.now(datetime.UTC)
                                    - datetime.timedelta(seconds=1)
                                }
                            )
                        }
                    ),
                ),
            )
        case _:
            raise AssertionError("Unknown fixture fence.")
    h.repo.load.return_value = changed
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.recheck_operation(receipt)
    assert error.value.code == "stale"
    h.provider.refresh.assert_not_awaited()


async def test_service_loss_blocks_subsequent_admission() -> None:
    h = _harness(expired=False)
    receipt = await h.service.authorize_operation(
        h.owner, "toolkit", Op.CALENDAR_GET_EVENT, ()
    )
    h.repo.load.return_value = dataclasses.replace(
        h.current,
        config=h.current.config.model_copy(update={"services": (GoogleService.GMAIL,)}),
    )
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.recheck_operation(receipt)
    assert error.value.code == "capability_unavailable"


async def test_401_finalization_retains_original_revision_snapshot() -> None:
    h = _harness(expired=False)
    receipt = await h.service.authorize_operation(
        h.owner, "toolkit", Op.CALENDAR_GET_EVENT, ()
    )
    h.repo.load.reset_mock()
    await h.service.direct_authentication_failed(receipt)
    h.repo.load.assert_not_awaited()
    h.repo.finalize_refresh.assert_awaited_once_with(
        h.owner, snapshot=receipt.snapshot, refreshed=None, rejected=True
    )
