"""Current direct-operation admission is independent of the former task ceiling."""

import dataclasses
import datetime

import pytest

from azents.core.google_oauth import GoogleOAuthError
from azents.core.google_policy import GoogleTask
from azents.core.google_workspace_policy import GoogleWorkspaceOperation as Op
from azents.services.google_oauth.runtime_test import _harness


async def test_broad_actual_grant_admits_write_under_old_read_service_membership() -> (
    None
):
    h = _harness(expired=False)
    current = dataclasses.replace(
        h.current,
        config=h.current.config.model_copy(update={"tasks": [GoogleTask.GMAIL_READ]}),
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
        config=h.current.config.model_copy(update={"tasks": [GoogleTask.GMAIL_READ]}),
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
