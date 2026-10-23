"""Gmail operations use the real SDK against deterministic synthetic HTTP."""

import base64
import dataclasses
import json
from collections.abc import Callable, Iterator
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from azents.core.google_oauth import GoogleOAuthError
from azents.core.google_policy import GoogleService
from azents.core.google_workspace_policy import GoogleWorkspaceOperation as Op
from azents.core.google_workspace_policy import eligible_operations, operation_permitted
from azents.services.google_workspace import gmail
from azents.services.google_workspace import gmail_models as m
from azents.services.google_workspace.errors import GoogleWorkspacePartialError
from azents.services.google_workspace.file_models import (
    GoogleFileInput,
    GooglePreparedFile,
)
from azents.services.google_workspace.transport import (
    GoogleSdkError,
    GoogleSdkLimits,
    GoogleSdkSession,
    GoogleWorkspaceSdk,
)


class _Stream(httpx.SyncByteStream):
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __iter__(self) -> Iterator[bytes]:
        yield self.data


@dataclasses.dataclass(frozen=True)
class _Reply:
    status: int
    payload: object


async def _run[T](
    operation: Callable[[GoogleSdkSession], T],
    replies: tuple[_Reply, ...],
    requests: list[httpx.Request],
    *,
    before_request: Callable[[], None] = lambda: None,
) -> T:
    responses = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        reply = next(responses)
        body = b"" if reply.status == 204 else json.dumps(reply.payload).encode()
        return httpx.Response(
            reply.status,
            headers={"content-type": "application/json"},
            stream=_Stream(body),
        )

    sdk = GoogleWorkspaceSdk(
        capacity=1,
        client_factory=lambda proxy, timeout: httpx.Client(
            transport=httpx.MockTransport(handler)
        ),
    )
    return await sdk.run(
        access_token="fixture-access",
        limits=GoogleSdkLimits(
            maximum_response_bytes=524288,
            maximum_total_received_bytes=2097152,
            maximum_upload_bytes=524288,
            timeout=5,
        ),
        proxy_url=None,
        before_request=before_request,
        operation=operation,
    )


@pytest.fixture
def compose() -> m.GmailCompose:
    return m.GmailCompose(
        sender=None,
        to=(m.GmailMailbox(email="recipient@example.com", display_name=None),),
        cc=(),
        bcc=(),
        reply_to=(),
        subject="Review",
        text="Message body.",
        html=None,
        body_file=None,
        body_file_format=None,
        attachments=(),
    )


def _change(value: m.GmailCompose, **changes: object) -> m.GmailCompose:
    payload = value.model_dump()
    payload.update(changes)
    return m.GmailCompose.model_validate(payload)


def _message(message_id: str = "original") -> dict[str, object]:
    data = b"Original body."
    return {
        "id": message_id,
        "threadId": "thread",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "connected@example.com"},
                {"name": "Subject", "value": "Original topic"},
                {"name": "Message-ID", "value": "<original@example.com>"},
            ],
            "body": {
                "data": base64.urlsafe_b64encode(data).decode(),
                "size": len(data),
            },
        },
    }


def _parsed(request: httpx.Request, *, draft: bool) -> EmailMessage:
    payload = json.loads(request.content)
    encoded = payload["message"]["raw"] if draft else payload["raw"]
    result = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(encoded)
    )
    assert isinstance(result, EmailMessage)
    return result


def _scope(name: str) -> str:
    return "https://www.googleapis.com/auth/" + name


def _gate(
    operation: Op, scopes: tuple[str, ...], auxiliary: tuple[Op, ...]
) -> Callable[[], None]:
    def admit() -> None:
        if not operation_permitted(
            operation, (GoogleService.GMAIL,), scopes, auxiliary
        ):
            raise GoogleOAuthError(
                "capability_unavailable", "Current scope does not permit this request."
            )

    return admit


async def test_send_only_uses_one_send_request_without_mailbox_reads(
    compose: m.GmailCompose,
) -> None:
    requests: list[httpx.Request] = []
    result = await _run(
        lambda session: gmail.send_message(
            session,
            m.GmailSendInput(message=compose),
            primary_email="connected@example.com",
            attachments=(),
            body_file=None,
        ),
        (_Reply(200, {"id": "sent", "threadId": "newthread"}),),
        requests,
        before_request=_gate(Op.GMAIL_SEND_MESSAGE, (_scope("gmail.send"),), ()),
    )
    assert result.id == "sent" and len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/gmail/v1/users/me/messages/send"
    parsed = _parsed(requests[0], draft=False)
    assert str(parsed["From"]) == "connected@example.com"
    assert parsed.get_content().strip() == "Message body."


async def test_reply_requires_read_before_any_provider_effect(
    compose: m.GmailCompose,
) -> None:
    value = m.GmailReplyInput(
        message=_change(compose, to=[], subject=None),
        source_message_id="original",
        reply_all=False,
        quote_original=True,
        reuse_source_attachments=False,
    )
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleOAuthError):
        await _run(
            lambda session: gmail.reply_message(
                session,
                value,
                primary_email="connected@example.com",
                attachments=(),
                body_file=None,
            ),
            (),
            requests,
            before_request=_gate(Op.GMAIL_REPLY_MESSAGE, (_scope("gmail.send"),), ()),
        )
    assert not requests


async def test_reply_sends_in_exact_original_thread_after_read(
    compose: m.GmailCompose,
) -> None:
    value = m.GmailReplyInput(
        message=_change(compose, to=[], subject=None),
        source_message_id="original",
        reply_all=False,
        quote_original=True,
        reuse_source_attachments=False,
    )
    requests: list[httpx.Request] = []
    await _run(
        lambda session: gmail.reply_message(
            session,
            value,
            primary_email="connected@example.com",
            attachments=(),
            body_file=None,
        ),
        (_Reply(200, _message()), _Reply(200, {"id": "reply", "threadId": "thread"})),
        requests,
        before_request=_gate(
            Op.GMAIL_REPLY_MESSAGE, (_scope("gmail.send"), _scope("gmail.readonly")), ()
        ),
    )
    assert [request.method for request in requests] == ["GET", "POST"]
    assert json.loads(requests[1].content)["threadId"] == "thread"
    parsed = _parsed(requests[1], draft=False)
    assert str(parsed["To"]) == "sender@example.com"
    assert str(parsed["In-Reply-To"]) == "<original@example.com>"


async def test_unverified_alias_does_not_send(compose: m.GmailCompose) -> None:
    message = _change(
        compose, sender={"email": "alias@example.com", "display_name": None}
    )
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: gmail.send_message(
                session,
                m.GmailSendInput(message=message),
                primary_email="connected@example.com",
                attachments=(),
                body_file=None,
            ),
            (
                _Reply(
                    200,
                    {
                        "sendAsEmail": "alias@example.com",
                        "verificationStatus": "pending",
                    },
                ),
            ),
            requests,
        )
    assert error.value.code == "sender_alias_unverified"
    assert len(requests) == 1 and requests[0].method == "GET"


async def test_verified_alias_uses_explicit_settings_read_scope(
    compose: m.GmailCompose,
) -> None:
    message = _change(
        compose, sender={"email": "alias@example.com", "display_name": "Alias"}
    )
    auxiliary = gmail.compose_prerequisites(message, None, "connected@example.com")
    assert auxiliary == (Op.GMAIL_GET_SEND_AS,)
    requests: list[httpx.Request] = []
    await _run(
        lambda session: gmail.send_message(
            session,
            m.GmailSendInput(message=message),
            primary_email="connected@example.com",
            attachments=(),
            body_file=None,
        ),
        (
            _Reply(
                200,
                {"sendAsEmail": "alias@example.com", "verificationStatus": "accepted"},
            ),
            _Reply(200, {"id": "sent"}),
        ),
        requests,
        before_request=_gate(
            Op.GMAIL_SEND_MESSAGE,
            (_scope("gmail.send"), _scope("gmail.settings.basic")),
            auxiliary,
        ),
    )
    assert len(requests) == 2
    assert requests[0].url.path.endswith("/settings/sendAs/alias@example.com")
    assert "alias@example.com" in str(_parsed(requests[1], draft=False)["From"])


async def test_send_only_cannot_borrow_alias_verification_read(
    compose: m.GmailCompose,
) -> None:
    message = _change(
        compose, sender={"email": "alias@example.com", "display_name": None}
    )
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleOAuthError):
        await _run(
            lambda session: gmail.send_message(
                session,
                m.GmailSendInput(message=message),
                primary_email="connected@example.com",
                attachments=(),
                body_file=None,
            ),
            (),
            requests,
            before_request=_gate(
                Op.GMAIL_SEND_MESSAGE,
                (_scope("gmail.send"),),
                gmail.compose_prerequisites(message, None, "connected@example.com"),
            ),
        )
    assert not requests


@pytest.mark.parametrize("update", [False, True])
async def test_draft_create_update_use_mime_without_hidden_reads(
    compose: m.GmailCompose, update: bool
) -> None:
    compose = _change(
        compose,
        subject="초안 검토 📄",
        to=[{"email": "recipient@example.com", "display_name": "수신인"}],
        text="한글 본문",
    )
    requests: list[httpx.Request] = []

    def operation(session: GoogleSdkSession) -> m.GmailDraftSummary:
        if update:
            return gmail.update_draft(
                session,
                m.GmailDraftUpdateInput(
                    message=compose, context=None, draft_id="draft"
                ),
                primary_email="connected@example.com",
                attachments=(),
                body_file=None,
            )
        return gmail.create_draft(
            session,
            m.GmailDraftCreateInput(message=compose, context=None),
            primary_email="connected@example.com",
            attachments=(),
            body_file=None,
        )

    result = await _run(
        operation,
        (_Reply(200, {"id": "draft", "message": {"id": "draftmessage"}}),),
        requests,
    )
    assert result.id == "draft" and len(requests) == 1
    assert requests[0].method == ("PUT" if update else "POST")
    payload = json.loads(requests[0].content)
    raw = base64.urlsafe_b64decode(payload["message"]["raw"])
    assert raw.split(b"\r\n\r\n", 1)[0].isascii()
    parsed = _parsed(requests[0], draft=True)
    assert str(parsed["Subject"]) == "초안 검토 📄"
    assert parsed["To"].addresses[0].display_name == "수신인"
    assert parsed.get_content().strip() == "한글 본문"


async def test_get_draft_raw_works_with_compose_without_attachment_api() -> None:
    raw_message = EmailMessage(policy=policy.SMTPUTF8)
    raw_message["From"] = "connected@example.com"
    raw_message["Subject"] = "Draft"
    raw_message.set_content("Draft body.")
    raw_message.add_attachment(
        b"\x00\xffdata",
        maintype="application",
        subtype="octet-stream",
        filename="binary.bin",
    )
    raw = raw_message.as_bytes()
    requests: list[httpx.Request] = []
    result = await _run(
        lambda session: gmail.get_draft(
            session, m.GmailDraftGetInput(draft_id="draft", body_character_limit=1000)
        ),
        (
            _Reply(
                200,
                {
                    "id": "draft",
                    "message": {
                        "id": "draftmessage",
                        "raw": base64.urlsafe_b64encode(raw).decode(),
                    },
                },
            ),
        ),
        requests,
        before_request=_gate(Op.GMAIL_GET_DRAFT, (_scope("gmail.compose"),), ()),
    )
    assert len(requests) == 1 and requests[0].url.params["format"] == "raw"
    assert result.files[0].content == raw
    assert any(file.content == b"\x00\xffdata" for file in result.files)
    assert result.value.message.body_parts[0].text is not None
    assert result.value.message.body_parts[0].text.strip() == "Draft body."
    assert "raw" not in result.value.model_dump()


async def test_send_saved_draft_never_fetches_or_rebuilds_message() -> None:
    requests: list[httpx.Request] = []
    await _run(
        lambda session: gmail.send_draft(
            session, m.GmailDraftIdInput(draft_id="draft")
        ),
        (_Reply(200, {"id": "sent"}),),
        requests,
        before_request=_gate(Op.GMAIL_SEND_DRAFT, (_scope("gmail.compose"),), ()),
    )
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/drafts/send")
    assert json.loads(requests[0].content) == {"id": "draft"}


async def test_send_scope_alone_does_not_admit_saved_draft_send() -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleOAuthError):
        await _run(
            lambda session: gmail.send_draft(
                session, m.GmailDraftIdInput(draft_id="draft")
            ),
            (),
            requests,
            before_request=_gate(Op.GMAIL_SEND_DRAFT, (_scope("gmail.send"),), ()),
        )
    assert not requests


async def test_attachment_download_keeps_original_bytes_hash_and_safe_name() -> None:
    binary = b"\x00\xffbinary"
    message = {
        "id": "message",
        "payload": {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "partId": "1",
                    "filename": "../../attachment.bin",
                    "mimeType": "application/octet-stream",
                    "body": {"attachmentId": "attachment", "size": len(binary)},
                }
            ],
        },
    }
    requests: list[httpx.Request] = []
    result = await _run(
        lambda session: gmail.download_attachment(
            session,
            m.GmailAttachmentInput(
                message_id="message", attachment_id="attachment", part_id=None
            ),
            maximum_bytes=1024,
        ),
        (
            _Reply(200, message),
            _Reply(
                200,
                {
                    "data": base64.urlsafe_b64encode(binary).decode(),
                    "size": len(binary),
                },
            ),
        ),
        requests,
    )
    assert len(requests) == 2
    assert result.files[0].content == binary
    assert result.files[0].filename == "attachment.bin"
    assert len(result.files[0].sha256) == 64
    assert result.value.size == len(binary)
    assert "data" not in result.value.model_dump()


async def test_announced_attachment_limit_prevents_download_request() -> None:
    requests: list[httpx.Request] = []
    payload = {
        "id": "message",
        "payload": {
            "partId": "1",
            "mimeType": "application/octet-stream",
            "filename": "binary.bin",
            "body": {"attachmentId": "attachment", "size": 999},
        },
    }
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: gmail.download_attachment(
                session,
                m.GmailAttachmentInput(
                    message_id="message", attachment_id="attachment", part_id=None
                ),
                maximum_bytes=10,
            ),
            (_Reply(200, payload),),
            requests,
        )
    assert error.value.code == "gmail_file_unavailable_or_oversized"
    assert len(requests) == 1


async def test_small_inline_attachment_needs_no_additional_provider_call() -> None:
    requests: list[httpx.Request] = []
    payload = {
        "id": "message",
        "payload": {
            "partId": "1",
            "mimeType": "application/octet-stream",
            "filename": "small.bin",
            "body": {"data": "YWJj", "size": 3},
        },
    }
    result = await _run(
        lambda session: gmail.download_attachment(
            session,
            m.GmailAttachmentInput(
                message_id="message", attachment_id=None, part_id="1"
            ),
            maximum_bytes=10,
        ),
        (_Reply(200, payload),),
        requests,
    )
    assert result.files[0].content == b"abc" and len(requests) == 1


async def test_attachment_length_mismatch_is_not_success() -> None:
    requests: list[httpx.Request] = []
    payload = {
        "id": "message",
        "payload": {
            "partId": "1",
            "mimeType": "application/octet-stream",
            "filename": "small.bin",
            "body": {"attachmentId": "attachment", "size": 3},
        },
    }
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: gmail.download_attachment(
                session,
                m.GmailAttachmentInput(
                    message_id="message", attachment_id="attachment", part_id=None
                ),
                maximum_bytes=10,
            ),
            (_Reply(200, payload), _Reply(200, {"data": "YWI=", "size": 2})),
            requests,
        )
    assert error.value.code == "invalid_gmail_length"


async def test_message_get_can_fetch_a_separately_stored_text_body() -> None:
    payload = {
        "id": "message",
        "payload": {
            "mimeType": "text/plain",
            "body": {"attachmentId": "body", "size": 3},
        },
    }
    requests: list[httpx.Request] = []
    result = await _run(
        lambda session: gmail.get_message(
            session,
            m.GmailMessageGetInput(message_id="message", body_character_limit=2),
        ),
        (_Reply(200, payload), _Reply(200, {"data": "YWJj", "size": 3})),
        requests,
    )
    assert result.value.body_parts[0].text == "ab"
    assert result.value.body_parts[0].status == "truncated"
    assert result.files[0].content == b"abc"
    assert len(requests) == 2


async def test_search_pagination_is_returned_without_hidden_fetches() -> None:
    requests: list[httpx.Request] = []
    result = await _run(
        lambda session: gmail.search_messages(
            session,
            m.GmailSearchInput(
                query="from:sender@example.com",
                page_token="cursor",
                page_size=10,
                include_spam_trash=False,
                label_ids=("INBOX",),
            ),
        ),
        (
            _Reply(
                200,
                {
                    "messages": [{"id": "message", "threadId": "thread"}],
                    "nextPageToken": "next",
                },
            ),
        ),
        requests,
    )
    assert result.next_page_token == "next" and len(requests) == 1
    assert requests[0].url.params["pageToken"] == "cursor"
    assert requests[0].url.params["includeSpamTrash"] == "false"


async def test_batch_read_failure_raises_with_confirmed_prefix() -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleWorkspacePartialError) as error:
        await _run(
            lambda session: gmail.batch_get_messages(
                session,
                m.GmailBatchGetInput(
                    message_ids=("first", "second", "third"), body_character_limit=100
                ),
            ),
            (
                _Reply(200, _message("first")),
                _Reply(503, {"error": {"message": "provider-content-canary"}}),
            ),
            requests,
        )
    assert error.value.partial.completed[0].resource_ids == ("first",)
    assert error.value.partial.remaining_ids == ("second", "third")
    assert error.value.status == 503
    assert "provider-content-canary" not in str(error.value)
    assert len(requests) == 2


async def test_batch_mutation_failure_does_not_replay_confirmed_chunk() -> None:
    identifiers = tuple(f"id{index}" for index in range(201))
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleWorkspacePartialError) as error:
        await _run(
            lambda session: gmail.batch_modify_messages(
                session,
                m.GmailBatchModifyInput(
                    message_ids=identifiers,
                    add_label_ids=("STARRED",),
                    remove_label_ids=("UNREAD",),
                ),
            ),
            (_Reply(204, None), _Reply(503, {"error": {"message": "uncertain"}})),
            requests,
        )
    assert error.value.partial.completed[0].resource_ids == identifiers[:100]
    assert error.value.partial.remaining_ids == identifiers[100:]
    assert len(requests) == 2
    assert json.loads(requests[1].content)["ids"] == list(identifiers[100:200])


@pytest.mark.parametrize(
    "labels",
    [
        {"add_label_ids": ["INBOX"], "remove_label_ids": ["INBOX"]},
        {"add_label_ids": ["SENT"], "remove_label_ids": []},
        {"add_label_ids": [], "remove_label_ids": []},
    ],
)
def test_mailbox_effects_are_validated_before_batch_dispatch(
    labels: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        m.GmailBatchModifyInput.model_validate({"message_ids": ["message"], **labels})


def _criteria() -> m.GmailFilterCriteria:
    return m.GmailFilterCriteria(
        sender="sender@example.com",
        recipient=None,
        subject=None,
        query=None,
        negated_query=None,
        has_attachment=None,
        exclude_chats=None,
        size=None,
        size_comparison=None,
    )


def _filter(action: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "id": "filter",
        "criteria": {"from": "sender@example.com"},
        "action": {"addLabelIds": ["STARRED"], "removeLabelIds": ["UNREAD"]}
        if action is None
        else action,
    }


async def test_filter_forwarding_uses_google_settings_contract_without_extra_gate() -> (
    None
):
    requests: list[httpx.Request] = []
    value = m.GmailFilterCreateInput(
        criteria=_criteria(),
        action=m.GmailFilterAction(
            add_label_ids=(), remove_label_ids=(), forward="verified@example.com"
        ),
    )
    result = await _run(
        lambda session: gmail.create_filter(session, value),
        (_Reply(200, {"id": "created"}),),
        requests,
        before_request=_gate(
            Op.GMAIL_CREATE_FILTER, (_scope("gmail.settings.basic"),), ()
        ),
    )
    assert result.id == "created"
    assert json.loads(requests[0].content)["action"] == {
        "addLabelIds": [],
        "removeLabelIds": [],
        "forward": "verified@example.com",
    }


async def test_filter_replacement_failure_retains_new_id_without_recreation() -> None:
    requests: list[httpx.Request] = []
    value = m.GmailFilterReplaceInput(
        filter_id="old",
        criteria=_criteria(),
        action=m.GmailFilterAction(
            add_label_ids=("STARRED",), remove_label_ids=(), forward=None
        ),
    )
    with pytest.raises(GoogleWorkspacePartialError) as error:
        await _run(
            lambda session: gmail.replace_filter(session, value),
            (
                _Reply(200, {"id": "created"}),
                _Reply(503, {"error": {"message": "provider-canary"}}),
            ),
            requests,
        )
    assert error.value.partial.completed[0].resource_ids == ("created",)
    assert error.value.partial.remaining_ids == ("old",)
    assert [request.method for request in requests] == ["POST", "DELETE"]
    assert "provider-canary" not in str(error.value)


async def test_service_off_after_filter_create_blocks_delete_and_reports_prefix() -> (
    None
):
    admissions = 0

    def admit() -> None:
        nonlocal admissions
        admissions += 1
        if admissions > 1:
            raise GoogleOAuthError(
                "capability_unavailable", "Current service is disabled."
            )

    requests: list[httpx.Request] = []
    value = m.GmailFilterReplaceInput(
        filter_id="old",
        criteria=_criteria(),
        action=m.GmailFilterAction(
            add_label_ids=("STARRED",), remove_label_ids=(), forward=None
        ),
    )
    with pytest.raises(GoogleWorkspacePartialError) as error:
        await _run(
            lambda session: gmail.replace_filter(session, value),
            (_Reply(200, {"id": "created"}),),
            requests,
            before_request=admit,
        )
    assert len(requests) == 1
    assert error.value.partial.completed[0].resource_ids == ("created",)
    assert error.value.partial.cause_code == "capability_unavailable"


def test_filter_preview_and_modification_have_distinct_scope_authority() -> None:
    allowed = eligible_operations((GoogleService.GMAIL,), (_scope("gmail.readonly"),))
    assert Op.GMAIL_PREVIEW_FILTER in allowed
    assert Op.GMAIL_APPLY_FILTER not in allowed


async def test_filter_preview_reads_without_historical_forwarding() -> None:
    requests: list[httpx.Request] = []
    value = m.GmailFilterPreviewInput(
        filter_id="filter",
        maximum_messages=10,
        page_token=None,
        include_spam_trash=False,
    )
    result = await _run(
        lambda session: gmail.preview_filter(session, value),
        (
            _Reply(200, _filter({"forward": "verified@example.com"})),
            _Reply(200, {"messages": [{"id": "one"}], "nextPageToken": "next"}),
            _Reply(200, {"messages": []}),
        ),
        requests,
        before_request=_gate(Op.GMAIL_PREVIEW_FILTER, (_scope("gmail.readonly"),), ()),
    )
    assert result.matched_message_ids == ("one",) and not result.confirmed_message_ids
    assert result.dry_run and not result.forwarding_applied
    assert all(request.method == "GET" for request in requests)
    assert requests[1].url.params["q"] == 'from:"sender@example.com"'


async def test_existing_mail_apply_changes_only_filter_label_effects() -> None:
    requests: list[httpx.Request] = []
    value = m.GmailFilterApplyInput(
        filter_id="filter",
        maximum_messages=10,
        page_token=None,
        include_spam_trash=False,
    )
    result = await _run(
        lambda session: gmail.apply_filter(session, value),
        (
            _Reply(200, _filter()),
            _Reply(200, {"messages": [{"id": "one"}, {"id": "two"}]}),
            _Reply(204, None),
        ),
        requests,
        before_request=_gate(Op.GMAIL_APPLY_FILTER, (_scope("gmail.modify"),), ()),
    )
    assert result.confirmed_message_ids == ("one", "two")
    assert not result.forwarding_applied and not result.dry_run
    assert json.loads(requests[-1].content) == {
        "ids": ["one", "two"],
        "addLabelIds": ["STARRED"],
        "removeLabelIds": ["UNREAD"],
    }


async def test_forward_only_filter_cannot_report_old_mail_as_modified() -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: gmail.apply_filter(
                session,
                m.GmailFilterApplyInput(
                    filter_id="filter",
                    maximum_messages=10,
                    page_token=None,
                    include_spam_trash=False,
                ),
            ),
            (
                _Reply(200, _filter({"forward": "verified@example.com"})),
                _Reply(200, {"messages": [{"id": "one"}]}),
            ),
            requests,
        )
    assert error.value.code == "filter_has_no_label_effects"
    assert len(requests) == 2 and all(request.method == "GET" for request in requests)


async def test_unknown_filter_criteria_cannot_be_silently_dropped_for_old_mail() -> (
    None
):
    filter_value = _filter()
    filter_value["criteria"] = {"futureUnknownCondition": "restrictive"}
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: gmail.apply_filter(
                session,
                m.GmailFilterApplyInput(
                    filter_id="filter",
                    maximum_messages=10,
                    page_token=None,
                    include_spam_trash=False,
                ),
            ),
            (_Reply(200, filter_value),),
            requests,
        )
    assert error.value.code == "invalid_provider_response"
    assert len(requests) == 1


async def test_provider_ignoring_requested_page_bound_cannot_expand_mutation_set() -> (
    None
):
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: gmail.apply_filter(
                session,
                m.GmailFilterApplyInput(
                    filter_id="filter",
                    maximum_messages=1,
                    page_token=None,
                    include_spam_trash=False,
                ),
            ),
            (
                _Reply(200, _filter()),
                _Reply(200, {"messages": [{"id": "one"}, {"id": "two"}]}),
            ),
            requests,
        )
    assert error.value.code == "provider_page_limit"
    assert len(requests) == 2


async def test_error_shaped_success_response_is_not_empty_success() -> None:
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: gmail.list_filters(session, m.GmailEmptyInput()),
            (_Reply(200, {"error": {"message": "private-provider-detail"}}),),
            [],
        )
    assert error.value.code == "invalid_provider_response"
    assert "private-provider-detail" not in str(error.value)


async def test_body_file_validation_precedes_related_message_reads(
    compose: m.GmailCompose,
) -> None:
    source = GoogleFileInput(
        source="artifact://fixture", filename=None, media_type=None
    )
    message = _change(
        compose, text=None, body_file=source.model_dump(), body_file_format="plain"
    )
    context = m.GmailDraftContext(
        mode="reply",
        source_message_id="original",
        reply_all=False,
        quote_original=True,
        reuse_source_attachments=False,
    )
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda session: gmail.create_draft(
                session,
                m.GmailDraftCreateInput(message=message, context=context),
                primary_email="connected@example.com",
                attachments=(),
                body_file=GooglePreparedFile("body.txt", "text/plain", b"\xff", ()),
            ),
            (),
            requests,
        )
    assert error.value.code == "body_file_requires_utf8"
    assert not requests


@pytest.mark.parametrize(
    "model",
    [
        m.GmailEmptyInput,
        m.GmailSendInput,
        m.GmailReplyInput,
        m.GmailForwardInput,
        m.GmailDraftCreateInput,
        m.GmailDraftUpdateInput,
        m.GmailMessageGetInput,
        m.GmailThreadGetInput,
        m.GmailBatchGetInput,
        m.GmailSearchInput,
        m.GmailAttachmentInput,
        m.GmailPageInput,
        m.GmailDraftGetInput,
        m.GmailDraftIdInput,
        m.GmailLabelCreateInput,
        m.GmailLabelPatchInput,
        m.GmailModifyMessageInput,
        m.GmailModifyThreadInput,
        m.GmailBatchModifyInput,
        m.GmailFilterCreateInput,
        m.GmailFilterReplaceInput,
        m.GmailFilterIdInput,
        m.GmailFilterPreviewInput,
        m.GmailFilterApplyInput,
    ],
)
def test_gmail_tool_schemas_remain_closed_top_level_objects(
    model: type[BaseModel],
) -> None:
    schema = model.model_json_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "oneOf" not in schema


@pytest.mark.parametrize(
    "operation,reply,method,suffix,body",
    [
        (
            lambda s: gmail.list_labels(s, m.GmailEmptyInput()),
            _Reply(200, {"labels": [{"id": "INBOX", "type": "system"}]}),
            "GET",
            "/labels",
            None,
        ),
        (
            lambda s: gmail.get_label(s, m.GmailLabelIdInput(label_id="Label_1")),
            _Reply(200, {"id": "Label_1", "name": "Project"}),
            "GET",
            "/labels/Label_1",
            None,
        ),
        (
            lambda s: gmail.create_label(
                s,
                m.GmailLabelCreateInput(
                    name="Project",
                    label_list_visibility="labelShow",
                    message_list_visibility="show",
                    color=None,
                ),
            ),
            _Reply(200, {"id": "Label_1", "name": "Project"}),
            "POST",
            "/labels",
            {
                "name": "Project",
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        ),
        (
            lambda s: gmail.update_label(
                s,
                m.GmailLabelPatchInput(
                    label_id="Label_1",
                    changes={"name": "Renamed"},
                ),
            ),
            _Reply(200, {"id": "Label_1", "name": "Renamed"}),
            "PATCH",
            "/labels/Label_1",
            {"name": "Renamed"},
        ),
        (
            lambda s: gmail.delete_label(s, m.GmailLabelIdInput(label_id="Label_1")),
            _Reply(204, None),
            "DELETE",
            "/labels/Label_1",
            None,
        ),
        (
            lambda s: gmail.modify_message(
                s,
                m.GmailModifyMessageInput(
                    message_id="message",
                    add_label_ids=("STARRED",),
                    remove_label_ids=("INBOX",),
                ),
            ),
            _Reply(200, {"id": "message", "labelIds": ["STARRED"]}),
            "POST",
            "/messages/message/modify",
            {"addLabelIds": ["STARRED"], "removeLabelIds": ["INBOX"]},
        ),
        (
            lambda s: gmail.modify_thread(
                s,
                m.GmailModifyThreadInput(
                    thread_id="thread",
                    add_label_ids=("SPAM",),
                    remove_label_ids=("INBOX",),
                ),
            ),
            _Reply(200, {"id": "thread", "messages": [{"id": "message"}]}),
            "POST",
            "/threads/thread/modify",
            {"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]},
        ),
        (
            lambda s: gmail.trash_message(
                s, m.GmailMessageIdInput(message_id="message")
            ),
            _Reply(200, {"id": "message", "labelIds": ["TRASH"]}),
            "POST",
            "/messages/message/trash",
            None,
        ),
        (
            lambda s: gmail.untrash_message(
                s, m.GmailMessageIdInput(message_id="message")
            ),
            _Reply(200, {"id": "message"}),
            "POST",
            "/messages/message/untrash",
            None,
        ),
        (
            lambda s: gmail.trash_thread(s, m.GmailThreadIdInput(thread_id="thread")),
            _Reply(200, {"id": "thread"}),
            "POST",
            "/threads/thread/trash",
            None,
        ),
        (
            lambda s: gmail.untrash_thread(s, m.GmailThreadIdInput(thread_id="thread")),
            _Reply(200, {"id": "thread"}),
            "POST",
            "/threads/thread/untrash",
            None,
        ),
        (
            lambda s: gmail.delete_draft(s, m.GmailDraftIdInput(draft_id="draft")),
            _Reply(204, None),
            "DELETE",
            "/drafts/draft",
            None,
        ),
        (
            lambda s: gmail.delete_filter(s, m.GmailFilterIdInput(filter_id="filter")),
            _Reply(204, None),
            "DELETE",
            "/settings/filters/filter",
            None,
        ),
    ],
)
async def test_typed_label_and_mailbox_families_use_exact_sdk_contracts(
    operation: Callable[[GoogleSdkSession], BaseModel],
    reply: _Reply,
    method: str,
    suffix: str,
    body: dict[str, object] | None,
) -> None:
    requests: list[httpx.Request] = []
    result = await _run(operation, (reply,), requests)
    assert isinstance(result, BaseModel) and len(requests) == 1
    assert requests[0].method == method
    assert requests[0].url.path == "/gmail/v1/users/me" + suffix
    if body is not None:
        assert json.loads(requests[0].content) == body


@pytest.mark.parametrize("status", [200, 204])
async def test_void_sdk_methods_accept_valid_empty_replies(status: int) -> None:
    result = await _run(
        lambda s: gmail.delete_draft(s, m.GmailDraftIdInput(draft_id="draft")),
        (_Reply(status, {}),),
        [],
    )
    assert result.confirmed_ids == ("draft",)


async def test_void_method_rejects_raw_model_error_shaped_success() -> None:
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: gmail.delete_draft(s, m.GmailDraftIdInput(draft_id="draft")),
            (_Reply(200, {"error": {"message": "provider-content-canary"}}),),
            [],
        )
    assert error.value.code == "invalid_provider_response"
    assert "provider-content-canary" not in str(error.value)


async def test_thread_get_returns_explicit_message_truncation() -> None:
    requests: list[httpx.Request] = []
    result = await _run(
        lambda s: gmail.get_thread(
            s,
            m.GmailThreadGetInput(
                thread_id="thread",
                body_character_limit=100,
                maximum_messages=1,
            ),
        ),
        (
            _Reply(
                200, {"id": "thread", "messages": [_message("one"), _message("two")]}
            ),
        ),
        requests,
    )
    assert result.value.truncated and len(result.value.messages) == 1
    assert result.value.messages[0].id == "one"
    assert result.value.remaining_message_ids == ("two",)
    assert len(requests) == 1


async def test_reply_thread_mismatch_keeps_sent_id_without_resending(
    compose: m.GmailCompose,
) -> None:
    value = m.GmailReplyInput(
        message=_change(compose, to=[], subject=None),
        source_message_id="original",
        reply_all=False,
        quote_original=False,
        reuse_source_attachments=False,
    )
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleWorkspacePartialError) as error:
        await _run(
            lambda session: gmail.reply_message(
                session,
                value,
                primary_email="connected@example.com",
                attachments=(),
                body_file=None,
            ),
            (
                _Reply(200, _message()),
                _Reply(200, {"id": "sent", "threadId": "different"}),
            ),
            requests,
        )
    assert error.value.partial.completed[0].resource_ids == ("sent",)
    assert error.value.partial.cause_code == "reply_thread_mismatch"
    assert len(requests) == 2


async def test_forward_reuses_attachment_bytes_without_original_thread(
    compose: m.GmailCompose,
) -> None:
    source = _message()
    source["payload"] = {
        "mimeType": "multipart/mixed",
        "headers": [{"name": "Subject", "value": "Original topic"}],
        "parts": [
            {
                "partId": "1",
                "mimeType": "application/octet-stream",
                "filename": "binary.bin",
                "body": {"attachmentId": "attachment", "size": 3},
            }
        ],
    }
    requests: list[httpx.Request] = []
    value = m.GmailForwardInput(
        message=_change(compose, subject=None),
        source_message_id="original",
        quote_original=False,
        reuse_source_attachments=True,
    )
    await _run(
        lambda session: gmail.forward_message(
            session,
            value,
            primary_email="connected@example.com",
            attachments=(),
            body_file=None,
        ),
        (
            _Reply(200, source),
            _Reply(200, {"data": "AP94", "size": 3}),
            _Reply(200, {"id": "forwarded"}),
        ),
        requests,
    )
    assert len(requests) == 3
    assert "threadId" not in json.loads(requests[-1].content)
    attachments = list(_parsed(requests[-1], draft=False).iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_payload(decode=True) == b"\x00\xffx"


async def test_reply_draft_cannot_borrow_mailbox_reads_from_compose(
    compose: m.GmailCompose,
) -> None:
    context = m.GmailDraftContext(
        mode="reply",
        source_message_id="original",
        reply_all=False,
        quote_original=False,
        reuse_source_attachments=False,
    )
    message = _change(compose, subject=None)
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleOAuthError):
        await _run(
            lambda session: gmail.create_draft(
                session,
                m.GmailDraftCreateInput(message=message, context=context),
                primary_email="connected@example.com",
                attachments=(),
                body_file=None,
            ),
            (),
            requests,
            before_request=_gate(
                Op.GMAIL_CREATE_DRAFT,
                (_scope("gmail.compose"),),
                gmail.compose_prerequisites(message, context, "connected@example.com"),
            ),
        )
    assert not requests
