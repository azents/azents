"""Account-bound Gmail SDK operations with explicit compound steps and MIME limits."""

import dataclasses
import re
from typing import TYPE_CHECKING

from azents.core.file_transfer import GENERAL_FILE_MAXIMUM_BYTES
from azents.core.google_oauth import GoogleOAuthError
from azents.core.google_workspace_policy import GoogleWorkspaceOperation
from azents.services.google_workspace import gmail_models as m
from azents.services.google_workspace.errors import (
    GoogleCompletedStep,
    GoogleWorkspacePartialError,
)
from azents.services.google_workspace.file_models import (
    GooglePreparedFile,
    GoogleWorkspaceOutput,
    safe_file_name,
)
from azents.services.google_workspace.gmail_mime import (
    GMAIL_ATTACHMENT_MAXIMUM_BYTES,
    GmailDecodedMessage,
    GmailMimeContext,
    GmailPreparedMessage,
    GmailSourceAttachment,
    decode_gmail_bytes,
    decode_message,
    message_parts,
    parse_raw_draft,
    prepare_message,
    source_header,
    validate_input_files,
)
from azents.services.google_workspace.transport import (
    GoogleEmptyResponse,
    GoogleSdkError,
    GoogleSdkSession,
)

if TYPE_CHECKING:
    from googleapiclient._apis.gmail.v1.schemas import (
        BatchModifyMessagesRequest,
        Draft,
        Filter,
        FilterAction,
        FilterCriteria,
        Label,
        LabelColor,
        Message,
        ModifyMessageRequest,
        ModifyThreadRequest,
    )


def _read_part(
    session: GoogleSdkSession, message_id: str, part: m.GmailPart, maximum_bytes: int
) -> bytes:
    body = part.body
    if body is None or body.size is not None and body.size > maximum_bytes:
        raise GoogleSdkError(
            "gmail_file_unavailable_or_oversized", dispatched=True, status=None
        )
    if body.data is not None:
        return decode_gmail_bytes(
            body.data, maximum_bytes=maximum_bytes, expected_size=body.size
        )
    if body.attachment_id is None:
        if body.size in {None, 0}:
            return b""
        raise GoogleSdkError("gmail_body_unavailable", dispatched=True, status=None)
    receipt = session.decode(
        m.GmailBody,
        session.gmail.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=body.attachment_id),
    )
    if (
        receipt.data is None
        or body.size is not None
        and receipt.size is not None
        and body.size != receipt.size
    ):
        raise GoogleSdkError("invalid_gmail_length", dispatched=True, status=None)
    return decode_gmail_bytes(
        receipt.data,
        maximum_bytes=maximum_bytes,
        expected_size=body.size if body.size is not None else receipt.size,
    )


def _read_message(session: GoogleSdkSession, message_id: str) -> m.GmailMessageEnvelope:
    result = session.decode(
        m.GmailMessageEnvelope,
        session.gmail.users().messages().get(userId="me", id=message_id, format="full"),
    )
    if result.id != message_id:
        raise GoogleSdkError("message_identity_mismatch", dispatched=True, status=None)
    return result


def _decoded(
    session: GoogleSdkSession, message: m.GmailMessageEnvelope, character_limit: int
) -> GmailDecodedMessage:
    return decode_message(
        message,
        character_limit=character_limit,
        read_body=lambda part, maximum: _read_part(session, message.id, part, maximum),
    )


def get_message(
    session: GoogleSdkSession, value: m.GmailMessageGetInput
) -> GoogleWorkspaceOutput[m.GmailMessageResult]:
    decoded = _decoded(
        session, _read_message(session, value.message_id), value.body_character_limit
    )
    return GoogleWorkspaceOutput(decoded.value, decoded.files)


def batch_get_messages(
    session: GoogleSdkSession, value: m.GmailBatchGetInput
) -> GoogleWorkspaceOutput[m.GmailBatchMessageResult]:
    messages: list[m.GmailMessageResult] = []
    files: list[GooglePreparedFile] = []
    identifiers = tuple(dict.fromkeys(value.message_ids))
    for index, message_id in enumerate(identifiers):
        try:
            result = get_message(
                session,
                m.GmailMessageGetInput(
                    message_id=message_id,
                    body_character_limit=value.body_character_limit,
                ),
            )
        except (GoogleSdkError, GoogleOAuthError) as error:
            raise GoogleWorkspacePartialError(
                completed=tuple(
                    GoogleCompletedStep(action="get_message", resource_ids=(item.id,))
                    for item in messages
                ),
                unconfirmed_action="get_message",
                remaining_ids=identifiers[index:],
                cause_code=error.code,
                status=error.status if isinstance(error, GoogleSdkError) else None,
                dispatched=bool(messages)
                or isinstance(error, GoogleSdkError)
                and error.dispatched,
            ) from None
        messages.append(result.value)
        files.extend(result.files)
    return GoogleWorkspaceOutput(
        m.GmailBatchMessageResult(messages=tuple(messages)), tuple(files)
    )


def get_thread(
    session: GoogleSdkSession, value: m.GmailThreadGetInput
) -> GoogleWorkspaceOutput[m.GmailThreadResult]:
    thread = session.decode(
        m.GmailThreadEnvelope,
        session.gmail.users()
        .threads()
        .get(userId="me", id=value.thread_id, format="full"),
    )
    if thread.id != value.thread_id:
        raise GoogleSdkError("thread_identity_mismatch", dispatched=True, status=None)
    results = tuple(
        _decoded(session, message, value.body_character_limit)
        for message in thread.messages[: value.maximum_messages]
    )
    return GoogleWorkspaceOutput(
        m.GmailThreadResult(
            id=thread.id,
            messages=tuple(item.value for item in results),
            truncated=len(thread.messages) > value.maximum_messages,
            remaining_message_ids=tuple(
                message.id for message in thread.messages[value.maximum_messages :]
            ),
        ),
        tuple(file for result in results for file in result.files),
    )


def search_messages(
    session: GoogleSdkSession, value: m.GmailSearchInput
) -> m.GmailMessageListResult:
    return session.decode(
        m.GmailMessageListResult,
        session.gmail.users()
        .messages()
        .list(
            userId="me",
            q=value.query,
            pageToken=value.page_token,
            maxResults=value.page_size,
            includeSpamTrash=value.include_spam_trash,
            labelIds=list(value.label_ids) or None,
        ),
    )


def search_threads(
    session: GoogleSdkSession, value: m.GmailSearchInput
) -> m.GmailThreadListResult:
    return session.decode(
        m.GmailThreadListResult,
        session.gmail.users()
        .threads()
        .list(
            userId="me",
            q=value.query,
            pageToken=value.page_token,
            maxResults=value.page_size,
            includeSpamTrash=value.include_spam_trash,
            labelIds=list(value.label_ids) or None,
        ),
    )


def _part_file(
    session: GoogleSdkSession, message_id: str, part: m.GmailPart, maximum_bytes: int
) -> GooglePreparedFile:
    if (
        re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", part.mime_type)
        is None
    ):
        raise GoogleSdkError("invalid_file_media_type", dispatched=True, status=None)
    return GooglePreparedFile(
        filename=safe_file_name(part.filename, fallback="message-part.bin"),
        media_type=part.mime_type,
        content=_read_part(session, message_id, part, maximum_bytes),
        source_ids=(message_id,),
    )


def download_attachment(
    session: GoogleSdkSession, value: m.GmailAttachmentInput, *, maximum_bytes: int
) -> GoogleWorkspaceOutput[m.GmailAttachmentInfo]:
    message = _read_message(session, value.message_id)
    parts = (
        []
        if message.payload is None
        else [
            part
            for part in message_parts(message.payload)
            if value.part_id is not None
            and part.part_id == value.part_id
            or value.attachment_id is not None
            and part.body is not None
            and part.body.attachment_id == value.attachment_id
        ]
    )
    if len(parts) != 1:
        raise GoogleSdkError(
            "attachment_unavailable_or_ambiguous", dispatched=True, status=None
        )
    part = parts[0]
    file = _part_file(
        session, message.id, part, min(maximum_bytes, GENERAL_FILE_MAXIMUM_BYTES)
    )
    return GoogleWorkspaceOutput(
        m.GmailAttachmentInfo(
            part_id=part.part_id,
            attachment_id=None if part.body is None else part.body.attachment_id,
            filename=file.filename,
            media_type=file.media_type,
            size=file.size,
        ),
        (file,),
    )


def list_drafts(
    session: GoogleSdkSession, value: m.GmailPageInput
) -> m.GmailDraftListResult:
    return session.decode(
        m.GmailDraftListResult,
        session.gmail.users()
        .drafts()
        .list(
            userId="me",
            q=value.query,
            pageToken=value.page_token,
            maxResults=value.page_size,
            includeSpamTrash=value.include_spam_trash,
        ),
    )


def get_draft(
    session: GoogleSdkSession, value: m.GmailDraftGetInput
) -> GoogleWorkspaceOutput[m.GmailDraftResult]:
    receipt = session.decode(
        m.GmailDraftEnvelope,
        session.gmail.users()
        .drafts()
        .get(userId="me", id=value.draft_id, format="raw"),
    )
    if receipt.id != value.draft_id:
        raise GoogleSdkError("draft_identity_mismatch", dispatched=True, status=None)
    parsed = parse_raw_draft(receipt.message)
    decoded = _decoded(session, parsed.message, value.body_character_limit)
    files = [
        GooglePreparedFile(
            filename=f"draft-{receipt.id}.eml",
            media_type="message/rfc822",
            content=parsed.original,
            source_ids=(receipt.id, parsed.message.id),
        ),
        *decoded.files,
    ]
    for part in decoded.attachments:
        if part.body is not None:
            files.append(
                _part_file(session, parsed.message.id, part, GENERAL_FILE_MAXIMUM_BYTES)
            )
    return GoogleWorkspaceOutput(
        m.GmailDraftResult(id=receipt.id, message=decoded.value), tuple(files)
    )


def compose_prerequisites(
    message: m.GmailCompose,
    context: m.GmailDraftContext | None,
    primary_email: str | None,
) -> tuple[GoogleWorkspaceOperation, ...]:
    prerequisites: list[GoogleWorkspaceOperation] = []
    if message.sender is not None and (
        primary_email is None
        or message.sender.email.casefold() != primary_email.casefold()
    ):
        prerequisites.append(GoogleWorkspaceOperation.GMAIL_GET_SEND_AS)
    if context is not None:
        prerequisites.append(GoogleWorkspaceOperation.GMAIL_GET_MESSAGE)
        if context.reuse_source_attachments:
            prerequisites.append(GoogleWorkspaceOperation.GMAIL_DOWNLOAD_ATTACHMENT)
    return tuple(prerequisites)


def _verify_sender(
    session: GoogleSdkSession, message: m.GmailCompose, primary_email: str | None
) -> None:
    if (
        message.sender is None
        or primary_email is not None
        and message.sender.email.casefold() == primary_email.casefold()
    ):
        return
    sender = session.decode(
        m.GmailSendAsResult,
        session.gmail.users()
        .settings()
        .sendAs()
        .get(userId="me", sendAsEmail=message.sender.email),
    )
    if (
        sender.send_as_email.casefold() != message.sender.email.casefold()
        or sender.verification_status != "accepted"
    ):
        raise GoogleSdkError("sender_alias_unverified", dispatched=True, status=None)


def _prepare(
    session: GoogleSdkSession,
    message: m.GmailCompose,
    context: m.GmailDraftContext | None,
    *,
    primary_email: str | None,
    attachments: tuple[GooglePreparedFile, ...],
    body_file: GooglePreparedFile | None,
) -> GmailPreparedMessage:
    validate_input_files(message, attachments, body_file)
    _verify_sender(session, message, primary_email)
    original = (
        None
        if context is None
        else _decoded(session, _read_message(session, context.source_message_id), 65536)
    )
    reused: list[GmailSourceAttachment] = []
    if (
        original is not None
        and context is not None
        and context.reuse_source_attachments
    ):
        if len(original.attachments) + len(attachments) > 25:
            raise GoogleSdkError("gmail_attachment_limit", dispatched=True, status=None)
        remaining = GMAIL_ATTACHMENT_MAXIMUM_BYTES - sum(
            file.size for file in attachments
        )
        known_source_bytes = sum(
            part.body.size
            for part in original.attachments
            if part.body is not None and part.body.size is not None
        )
        if known_source_bytes > remaining:
            raise GoogleSdkError("gmail_attachment_limit", dispatched=True, status=None)
        for part in original.attachments:
            file = _part_file(session, original.value.id, part, remaining)
            remaining -= file.size
            content_id = source_header(part, "Content-ID")
            if (
                content_id is not None
                and re.fullmatch(r"<[^<>\s\x00]+>", content_id) is None
            ):
                raise GoogleSdkError("invalid_content_id", dispatched=True, status=None)
            reused.append(
                GmailSourceAttachment(file, content_id, content_id is not None)
            )
    return prepare_message(
        GmailMimeContext(
            message=message,
            primary_email=primary_email,
            attachments=attachments,
            body_file=body_file,
            original=original,
            mode="new" if context is None else context.mode,
            reply_all=False if context is None else context.reply_all,
            quote_original=False if context is None else context.quote_original,
            source_attachments=tuple(reused),
        )
    )


def _message_body(prepared: GmailPreparedMessage) -> "Message":
    body: Message = {"raw": prepared.raw}
    if prepared.thread_id is not None:
        body["threadId"] = prepared.thread_id
    return body


def _send_prepared(
    session: GoogleSdkSession, prepared: GmailPreparedMessage
) -> m.GmailMessageSummary:
    if prepared.recipient_count == 0:
        raise GoogleSdkError("recipient_unavailable", dispatched=False, status=None)
    receipt = session.decode(
        m.GmailMessageSummary,
        session.gmail.users()
        .messages()
        .send(userId="me", body=_message_body(prepared)),
    )
    if prepared.thread_id is not None and receipt.thread_id != prepared.thread_id:
        raise GoogleWorkspacePartialError(
            completed=(
                GoogleCompletedStep(action="send_message", resource_ids=(receipt.id,)),
            ),
            unconfirmed_action="verify_reply_thread",
            remaining_ids=(prepared.thread_id,),
            cause_code="reply_thread_mismatch",
            status=None,
            dispatched=True,
        )
    return receipt


def send_message(
    session: GoogleSdkSession,
    value: m.GmailSendInput,
    *,
    primary_email: str | None,
    attachments: tuple[GooglePreparedFile, ...],
    body_file: GooglePreparedFile | None,
) -> m.GmailMessageSummary:
    return _send_prepared(
        session,
        _prepare(
            session,
            value.message,
            None,
            primary_email=primary_email,
            attachments=attachments,
            body_file=body_file,
        ),
    )


def reply_message(
    session: GoogleSdkSession,
    value: m.GmailReplyInput,
    *,
    primary_email: str | None,
    attachments: tuple[GooglePreparedFile, ...],
    body_file: GooglePreparedFile | None,
) -> m.GmailMessageSummary:
    context = m.GmailDraftContext(
        mode="reply",
        source_message_id=value.source_message_id,
        reply_all=value.reply_all,
        quote_original=value.quote_original,
        reuse_source_attachments=value.reuse_source_attachments,
    )
    return _send_prepared(
        session,
        _prepare(
            session,
            value.message,
            context,
            primary_email=primary_email,
            attachments=attachments,
            body_file=body_file,
        ),
    )


def forward_message(
    session: GoogleSdkSession,
    value: m.GmailForwardInput,
    *,
    primary_email: str | None,
    attachments: tuple[GooglePreparedFile, ...],
    body_file: GooglePreparedFile | None,
) -> m.GmailMessageSummary:
    context = m.GmailDraftContext(
        mode="forward",
        source_message_id=value.source_message_id,
        reply_all=False,
        quote_original=value.quote_original,
        reuse_source_attachments=value.reuse_source_attachments,
    )
    return _send_prepared(
        session,
        _prepare(
            session,
            value.message,
            context,
            primary_email=primary_email,
            attachments=attachments,
            body_file=body_file,
        ),
    )


def create_draft(
    session: GoogleSdkSession,
    value: m.GmailDraftCreateInput,
    *,
    primary_email: str | None,
    attachments: tuple[GooglePreparedFile, ...],
    body_file: GooglePreparedFile | None,
) -> m.GmailDraftSummary:
    prepared = _prepare(
        session,
        value.message,
        value.context,
        primary_email=primary_email,
        attachments=attachments,
        body_file=body_file,
    )
    body: Draft = {"message": _message_body(prepared)}
    return session.decode(
        m.GmailDraftSummary,
        session.gmail.users().drafts().create(userId="me", body=body),
    )


def update_draft(
    session: GoogleSdkSession,
    value: m.GmailDraftUpdateInput,
    *,
    primary_email: str | None,
    attachments: tuple[GooglePreparedFile, ...],
    body_file: GooglePreparedFile | None,
) -> m.GmailDraftSummary:
    prepared = _prepare(
        session,
        value.message,
        value.context,
        primary_email=primary_email,
        attachments=attachments,
        body_file=body_file,
    )
    body: Draft = {"message": _message_body(prepared)}
    return session.decode(
        m.GmailDraftSummary,
        session.gmail.users()
        .drafts()
        .update(userId="me", id=value.draft_id, body=body),
    )


def delete_draft(
    session: GoogleSdkSession, value: m.GmailDraftIdInput
) -> m.GmailMutationResult:
    session.decode(
        GoogleEmptyResponse,
        session.gmail.users().drafts().delete(userId="me", id=value.draft_id),
    )
    return m.GmailMutationResult(confirmed_ids=(value.draft_id,))


def send_draft(
    session: GoogleSdkSession, value: m.GmailDraftIdInput
) -> m.GmailMessageSummary:
    body: Draft = {"id": value.draft_id}
    return session.decode(
        m.GmailMessageSummary,
        session.gmail.users().drafts().send(userId="me", body=body),
    )


def list_labels(
    session: GoogleSdkSession, value: m.GmailEmptyInput
) -> m.GmailLabelListResult:
    return session.decode(
        m.GmailLabelListResult, session.gmail.users().labels().list(userId="me")
    )


def get_label(
    session: GoogleSdkSession, value: m.GmailLabelIdInput
) -> m.GmailLabelResult:
    return session.decode(
        m.GmailLabelResult,
        session.gmail.users().labels().get(userId="me", id=value.label_id),
    )


def _color(value: m.GmailLabelColor) -> "LabelColor":
    return {"backgroundColor": value.background_color, "textColor": value.text_color}


def create_label(
    session: GoogleSdkSession, value: m.GmailLabelCreateInput
) -> m.GmailLabelResult:
    body: Label = {
        "name": value.name,
        "labelListVisibility": value.label_list_visibility,
        "messageListVisibility": value.message_list_visibility,
    }
    if value.color is not None:
        body["color"] = _color(value.color)
    return session.decode(
        m.GmailLabelResult,
        session.gmail.users().labels().create(userId="me", body=body),
    )


def update_label(
    session: GoogleSdkSession, value: m.GmailLabelPatchInput
) -> m.GmailLabelResult:
    changes = value.changes
    body: Label = {}
    if "name" in changes:
        body["name"] = changes["name"]
    if "label_list_visibility" in changes:
        body["labelListVisibility"] = changes["label_list_visibility"]
    if "message_list_visibility" in changes:
        body["messageListVisibility"] = changes["message_list_visibility"]
    if "color" in changes:
        body["color"] = _color(changes["color"])
    return session.decode(
        m.GmailLabelResult,
        session.gmail.users().labels().patch(userId="me", id=value.label_id, body=body),
    )


def delete_label(
    session: GoogleSdkSession, value: m.GmailLabelIdInput
) -> m.GmailMutationResult:
    session.decode(
        GoogleEmptyResponse,
        session.gmail.users().labels().delete(userId="me", id=value.label_id),
    )
    return m.GmailMutationResult(confirmed_ids=(value.label_id,))


def modify_message(
    session: GoogleSdkSession, value: m.GmailModifyMessageInput
) -> m.GmailMessageSummary:
    body: ModifyMessageRequest = {
        "addLabelIds": list(value.add_label_ids),
        "removeLabelIds": list(value.remove_label_ids),
    }
    return session.decode(
        m.GmailMessageSummary,
        session.gmail.users()
        .messages()
        .modify(userId="me", id=value.message_id, body=body),
    )


def modify_thread(
    session: GoogleSdkSession, value: m.GmailModifyThreadInput
) -> m.GmailThreadMutationResult:
    body: ModifyThreadRequest = {
        "addLabelIds": list(value.add_label_ids),
        "removeLabelIds": list(value.remove_label_ids),
    }
    return session.decode(
        m.GmailThreadMutationResult,
        session.gmail.users()
        .threads()
        .modify(userId="me", id=value.thread_id, body=body),
    )


def batch_modify_messages(
    session: GoogleSdkSession, value: m.GmailBatchModifyInput
) -> m.GmailMutationResult:
    ids = tuple(dict.fromkeys(value.message_ids))
    completed: list[str] = []
    for index in range(0, len(ids), 100):
        chunk = ids[index : index + 100]
        body: BatchModifyMessagesRequest = {
            "ids": list(chunk),
            "addLabelIds": list(value.add_label_ids),
            "removeLabelIds": list(value.remove_label_ids),
        }
        try:
            session.decode(
                GoogleEmptyResponse,
                session.gmail.users().messages().batchModify(userId="me", body=body),
            )
        except (GoogleSdkError, GoogleOAuthError) as error:
            raise GoogleWorkspacePartialError(
                completed=()
                if not completed
                else (
                    GoogleCompletedStep(
                        action="batch_modify_messages", resource_ids=tuple(completed)
                    ),
                ),
                unconfirmed_action="batch_modify_messages",
                remaining_ids=ids[index:],
                cause_code=error.code,
                status=error.status if isinstance(error, GoogleSdkError) else None,
                dispatched=bool(completed)
                or isinstance(error, GoogleSdkError)
                and error.dispatched,
            ) from None
        completed.extend(chunk)
    return m.GmailMutationResult(confirmed_ids=tuple(completed))


def trash_message(
    session: GoogleSdkSession, value: m.GmailMessageIdInput
) -> m.GmailMessageSummary:
    return session.decode(
        m.GmailMessageSummary,
        session.gmail.users().messages().trash(userId="me", id=value.message_id),
    )


def untrash_message(
    session: GoogleSdkSession, value: m.GmailMessageIdInput
) -> m.GmailMessageSummary:
    return session.decode(
        m.GmailMessageSummary,
        session.gmail.users().messages().untrash(userId="me", id=value.message_id),
    )


def trash_thread(
    session: GoogleSdkSession, value: m.GmailThreadIdInput
) -> m.GmailThreadMutationResult:
    return session.decode(
        m.GmailThreadMutationResult,
        session.gmail.users().threads().trash(userId="me", id=value.thread_id),
    )


def untrash_thread(
    session: GoogleSdkSession, value: m.GmailThreadIdInput
) -> m.GmailThreadMutationResult:
    return session.decode(
        m.GmailThreadMutationResult,
        session.gmail.users().threads().untrash(userId="me", id=value.thread_id),
    )


def _criteria(value: m.GmailFilterCriteria) -> "FilterCriteria":
    result: FilterCriteria = {}
    if value.sender is not None:
        result["from"] = value.sender
    if value.recipient is not None:
        result["to"] = value.recipient
    if value.subject is not None:
        result["subject"] = value.subject
    if value.query is not None:
        result["query"] = value.query
    if value.negated_query is not None:
        result["negatedQuery"] = value.negated_query
    if value.has_attachment is not None:
        result["hasAttachment"] = value.has_attachment
    if value.exclude_chats is not None:
        result["excludeChats"] = value.exclude_chats
    if value.size is not None:
        result["size"] = value.size
    if value.size_comparison is not None:
        result["sizeComparison"] = value.size_comparison
    return result


def create_filter(
    session: GoogleSdkSession, value: m.GmailFilterCreateInput
) -> m.GmailFilterReceipt:
    action: FilterAction = {
        "addLabelIds": list(value.action.add_label_ids),
        "removeLabelIds": list(value.action.remove_label_ids),
    }
    if value.action.forward is not None:
        action["forward"] = value.action.forward
    body: Filter = {"criteria": _criteria(value.criteria), "action": action}
    return session.decode(
        m.GmailFilterReceipt,
        session.gmail.users().settings().filters().create(userId="me", body=body),
    )


def list_filters(
    session: GoogleSdkSession, value: m.GmailEmptyInput
) -> m.GmailFilterListResult:
    return session.decode(
        m.GmailFilterListResult,
        session.gmail.users().settings().filters().list(userId="me"),
    )


def get_filter(
    session: GoogleSdkSession, value: m.GmailFilterIdInput
) -> m.GmailFilterResult:
    result = session.decode(
        m.GmailFilterResult,
        session.gmail.users().settings().filters().get(userId="me", id=value.filter_id),
    )
    if result.id != value.filter_id:
        raise GoogleSdkError("filter_identity_mismatch", dispatched=True, status=None)
    return result


def delete_filter(
    session: GoogleSdkSession, value: m.GmailFilterIdInput
) -> m.GmailMutationResult:
    session.decode(
        GoogleEmptyResponse,
        session.gmail.users()
        .settings()
        .filters()
        .delete(userId="me", id=value.filter_id),
    )
    return m.GmailMutationResult(confirmed_ids=(value.filter_id,))


def replace_filter(
    session: GoogleSdkSession, value: m.GmailFilterReplaceInput
) -> m.GmailFilterReplaceResult:
    created = create_filter(
        session, m.GmailFilterCreateInput(criteria=value.criteria, action=value.action)
    )
    try:
        if created.id == value.filter_id:
            raise GoogleSdkError(
                "filter_identity_mismatch", dispatched=True, status=None
            )
        delete_filter(session, m.GmailFilterIdInput(filter_id=value.filter_id))
    except (GoogleSdkError, GoogleOAuthError) as error:
        raise GoogleWorkspacePartialError(
            completed=(
                GoogleCompletedStep(action="create_filter", resource_ids=(created.id,)),
            ),
            unconfirmed_action="delete_old_filter",
            remaining_ids=(value.filter_id,),
            cause_code=error.code,
            status=error.status if isinstance(error, GoogleSdkError) else None,
            dispatched=True,
        ) from None
    return m.GmailFilterReplaceResult(
        created_filter_id=created.id, deleted_filter_id=value.filter_id
    )


def _quote_query_value(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def filter_search_query(value: m.GmailProviderFilterCriteria) -> str:
    terms: list[str] = []
    for field, text in (
        ("from", value.sender),
        ("to", value.recipient),
        ("subject", value.subject),
    ):
        if text is not None:
            terms.append(field + ":" + _quote_query_value(text))
    if value.query:
        terms.append("(" + value.query + ")")
    if value.negated_query:
        terms.append("-(" + value.negated_query + ")")
    if value.has_attachment:
        terms.append("has:attachment")
    if value.exclude_chats:
        terms.append("-in:chats")
    if value.size is not None and value.size_comparison in {"smaller", "larger"}:
        terms.append(f"{value.size_comparison}:{value.size}")
    elif value.size not in {None, 0}:
        raise GoogleSdkError("unsupported_filter_size", dispatched=True, status=None)
    return " ".join(terms)


@dataclasses.dataclass(frozen=True)
class _FilterMatches:
    filter: m.GmailFilterResult
    ids: tuple[str, ...]
    next_page_token: str | None


def _filter_matches(
    session: GoogleSdkSession, value: m.GmailFilterPreviewInput
) -> _FilterMatches:
    filter_result = get_filter(session, m.GmailFilterIdInput(filter_id=value.filter_id))
    query = filter_search_query(filter_result.criteria)
    ids: list[str] = []
    seen_ids: set[str] = set()
    seen_pages: set[str] = set()
    page = value.page_token
    for _ in range(10):
        if page is not None:
            if page in seen_pages:
                raise GoogleSdkError("pagination_cycle", dispatched=True, status=None)
            seen_pages.add(page)
        expected_page_size = min(500, value.maximum_messages - len(ids))
        result = search_messages(
            session,
            m.GmailSearchInput(
                query=query,
                page_token=page,
                page_size=expected_page_size,
                include_spam_trash=value.include_spam_trash,
                label_ids=(),
            ),
        )
        if len(result.messages) > expected_page_size:
            raise GoogleSdkError("provider_page_limit", dispatched=True, status=None)
        for message in result.messages:
            if message.id not in seen_ids:
                ids.append(message.id)
                seen_ids.add(message.id)
        page = result.next_page_token
        if page is None or len(ids) >= value.maximum_messages:
            break
    return _FilterMatches(filter_result, tuple(ids), page)


def preview_filter(
    session: GoogleSdkSession, value: m.GmailFilterPreviewInput
) -> m.GmailFilterApplyResult:
    matches = _filter_matches(session, value)
    return m.GmailFilterApplyResult(
        matched_message_ids=matches.ids,
        confirmed_message_ids=(),
        next_page_token=matches.next_page_token,
        dry_run=True,
        forwarding_applied=False,
    )


def apply_filter(
    session: GoogleSdkSession, value: m.GmailFilterApplyInput
) -> m.GmailFilterApplyResult:
    matches = _filter_matches(session, value)
    action = matches.filter.action
    if not action.add_label_ids and not action.remove_label_ids:
        raise GoogleSdkError(
            "filter_has_no_label_effects", dispatched=True, status=None
        )
    effects = m.GmailLabelEffects.model_validate(
        {
            "add_label_ids": action.add_label_ids,
            "remove_label_ids": action.remove_label_ids,
        }
    )
    if matches.ids:
        batch_modify_messages(
            session,
            m.GmailBatchModifyInput(
                message_ids=matches.ids,
                add_label_ids=effects.add_label_ids,
                remove_label_ids=effects.remove_label_ids,
            ),
        )
    return m.GmailFilterApplyResult(
        matched_message_ids=matches.ids,
        confirmed_message_ids=matches.ids,
        next_page_token=matches.next_page_token,
        dry_run=False,
        forwarding_applied=False,
    )
