"""Bounded Gmail MIME parsing/composition; content is untrusted, not screened."""

import base64
import binascii
import dataclasses
import html
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from email import policy
from email.header import decode_header, make_header
from email.headerregistry import Address
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.policy import Policy
from email.utils import format_datetime, getaddresses, make_msgid
from typing import Literal

from azents.core.file_transfer import GENERAL_FILE_MAXIMUM_BYTES
from azents.services.google_workspace.file_models import (
    GooglePreparedFile,
    safe_file_name,
)
from azents.services.google_workspace.gmail_models import (
    GmailAttachmentInfo,
    GmailBody,
    GmailCompose,
    GmailHeader,
    GmailMailbox,
    GmailMessageEnvelope,
    GmailMessageResult,
    GmailPart,
    GmailTextPart,
)
from azents.services.google_workspace.transport import GoogleSdkError

GMAIL_MESSAGE_MAXIMUM_BYTES = 35 * 1024 * 1024
GMAIL_ATTACHMENT_MAXIMUM_BYTES = 25 * 1024 * 1024
_ENCODED_WORD_PREFIX = re.compile(r"=\?[^?]*\?[bBqQ]\?|=\?[^?\s]+\?[^?\s]+\?")
_ENCODED_WORD = re.compile(r"=\?([^?\s]+)\?([bBqQ])\?([^?\s]+)\?=")


def decode_gmail_bytes(
    value: str, *, maximum_bytes: int, expected_size: int | None
) -> bytes:
    if maximum_bytes < 0 or len(value) > ((maximum_bytes + 2) // 3) * 4 + 2:
        raise GoogleSdkError("gmail_receive_limit", dispatched=True, status=None)
    if re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", value) is None:
        raise GoogleSdkError("invalid_gmail_encoding", dispatched=True, status=None)
    try:
        raw = value.encode("ascii")
        decoded = base64.b64decode(
            raw + b"=" * (-len(raw) % 4), altchars=b"-_", validate=True
        )
    except ValueError, binascii.Error:
        raise GoogleSdkError(
            "invalid_gmail_encoding", dispatched=True, status=None
        ) from None
    if (
        len(decoded) > maximum_bytes
        or expected_size is not None
        and len(decoded) != expected_size
        or base64.urlsafe_b64encode(decoded).rstrip(b"=") != raw.rstrip(b"=")
    ):
        raise GoogleSdkError("invalid_gmail_length", dispatched=True, status=None)
    return decoded


def source_header(part: GmailPart, name: str) -> str | None:
    values = [
        item.value for item in part.headers if item.name.casefold() == name.casefold()
    ]
    if len(values) > 1:
        raise GoogleSdkError("ambiguous_mail_header", dispatched=True, status=None)
    if not values:
        return None
    value = re.sub(r"\r?\n[ \t]+", " ", values[0])
    if "\r" in value or "\n" in value or "\x00" in value:
        raise GoogleSdkError("invalid_mail_header", dispatched=True, status=None)
    return value


def _decoded_header(value: str) -> str:
    """Decode display text without repairing malformed bytes or header controls."""
    try:
        cursor = 0
        while (start := value.find("=?", cursor)) >= 0:
            if _ENCODED_WORD_PREFIX.match(value, start) is None:
                cursor = start + 2
                continue
            word = _ENCODED_WORD.match(value, start)
            if word is None or not word.group().isascii():
                raise ValueError("Malformed encoded word.")
            cursor = word.end()
            payload = word[3]
            if word[2].casefold() == "b":
                base64.b64decode(payload, validate=True)
            elif re.search(r"=(?![0-9A-Fa-f]{2})", payload):
                raise ValueError("Malformed Q escape.")
        parts = [
            (
                part.decode(charset or "ascii") if isinstance(part, bytes) else part,
                None,
            )
            for part, charset in decode_header(value)
        ]
        decoded = str(make_header(parts))
    except LookupError, UnicodeError, ValueError:
        raise GoogleSdkError(
            "invalid_mail_header_encoding", dispatched=True, status=None
        ) from None
    if any(ord(character) < 32 or ord(character) == 127 for character in decoded):
        raise GoogleSdkError("invalid_mail_header", dispatched=True, status=None)
    return decoded


def _display_header(part: GmailPart, name: str) -> str | None:
    value = source_header(part, name)
    return None if value is None else _decoded_header(value)


def message_parts(payload: GmailPart) -> Iterator[GmailPart]:
    stack = [(payload, 0)]
    seen = 0
    while stack:
        part, depth = stack.pop()
        seen += 1
        if seen > 1000 or depth > 20:
            raise GoogleSdkError("mime_structure_limit", dispatched=True, status=None)
        if part.parts and not is_attachment(part):
            stack.extend((child, depth + 1) for child in reversed(part.parts))
        else:
            yield part


def is_attachment(part: GmailPart) -> bool:
    disposition = source_header(part, "Content-Disposition") or ""
    return (
        bool(part.filename)
        or disposition.split(";", 1)[0].strip().lower() == "attachment"
    )


@dataclasses.dataclass(frozen=True)
class GmailDecodedMessage:
    value: GmailMessageResult
    files: tuple[GooglePreparedFile, ...]
    plain_text: str | None = dataclasses.field(repr=False)
    html_text: str | None = dataclasses.field(repr=False)
    attachments: tuple[GmailPart, ...]


def decode_message(
    message: GmailMessageEnvelope,
    *,
    character_limit: int,
    body_format: Literal["gmail_full", "raw_mime"],
    read_body: Callable[[GmailPart, int], bytes],
) -> GmailDecodedMessage:
    text_parts: list[GmailTextPart] = []
    files: list[GooglePreparedFile] = []
    attachments: list[GmailPart] = []
    attachment_info: list[GmailAttachmentInfo] = []
    plain: list[str] = []
    rich: list[str] = []
    received = 0
    if message.payload is not None:
        for index, part in enumerate(message_parts(message.payload)):
            if is_attachment(part) or part.mime_type not in {"text/plain", "text/html"}:
                if part.body is not None or is_attachment(part):
                    attachments.append(part)
                    attachment_info.append(
                        GmailAttachmentInfo(
                            part_id=part.part_id,
                            attachment_id=None
                            if part.body is None
                            else part.body.attachment_id,
                            filename=safe_file_name(
                                part.filename, fallback=f"attachment-{index}.bin"
                            ),
                            media_type=part.mime_type,
                            size=None if part.body is None else part.body.size,
                        )
                    )
                continue
            if part.body is None:
                continue
            content = read_body(part, GENERAL_FILE_MAXIMUM_BYTES - received)
            received += len(content)
            header = Message()
            header["Content-Type"] = (
                source_header(part, "Content-Type") or part.mime_type
            )
            # Parsed FULL text is UTF-8 even when original MIME headers say otherwise.
            charset = (
                "utf-8"
                if body_format == "gmail_full"
                else header.get_content_charset() or "utf-8"
            )
            status: Literal[
                "complete", "truncated", "unsupported_charset", "invalid_encoding"
            ]
            try:
                text = content.decode(charset)
                status = "truncated" if len(text) > character_limit else "complete"
            except LookupError:
                text = None
                status = "unsupported_charset"
            except UnicodeDecodeError:
                text = None
                status = "invalid_encoding"
            text_parts.append(
                GmailTextPart(
                    media_type=part.mime_type,
                    text=None if text is None else text[:character_limit],
                    status=status,
                )
            )
            if status != "complete":
                files.append(
                    GooglePreparedFile(
                        filename=f"message-{message.id}-part-{index}."
                        + ("html" if part.mime_type == "text/html" else "txt"),
                        media_type=part.mime_type,
                        content=content,
                        source_ids=(message.id,),
                    )
                )
            if text is not None:
                (plain if part.mime_type == "text/plain" else rich).append(text)
    return GmailDecodedMessage(
        value=GmailMessageResult(
            id=message.id,
            threadId=message.thread_id,
            labelIds=message.label_ids,
            snippet=message.snippet,
            sizeEstimate=message.size_estimate,
            headers=() if message.payload is None else message.payload.headers,
            body_parts=tuple(text_parts),
            attachments=tuple(attachment_info),
        ),
        files=tuple(files),
        plain_text="\n".join(plain) if plain else None,
        html_text="\n".join(rich) if rich else None,
        attachments=tuple(attachments),
    )


def _mailboxes(value: str | None) -> tuple[GmailMailbox, ...]:
    if value is None:
        return ()
    try:
        parsed = getaddresses([value], strict=True)
        return tuple(
            GmailMailbox(email=email, display_name=_decoded_header(name) or None)
            for name, email in parsed
        )
    except ValueError:
        raise GoogleSdkError(
            "invalid_original_address", dispatched=True, status=None
        ) from None


def _unique(
    mailboxes: tuple[GmailMailbox, ...], excluded: set[str]
) -> tuple[GmailMailbox, ...]:
    result: list[GmailMailbox] = []
    seen = set(excluded)
    for mailbox in mailboxes:
        key = mailbox.email.casefold()
        if key not in seen:
            result.append(mailbox)
            seen.add(key)
    return tuple(result)


def _addresses(values: tuple[GmailMailbox, ...]) -> tuple[Address, ...]:
    return tuple(
        Address(display_name=value.display_name or "", addr_spec=value.email)
        for value in values
    )


@dataclasses.dataclass(frozen=True)
class GmailSourceAttachment:
    file: GooglePreparedFile
    content_id: str | None
    inline: bool


@dataclasses.dataclass(frozen=True)
class GmailMimeContext:
    message: GmailCompose
    primary_email: str | None
    attachments: tuple[GooglePreparedFile, ...]
    body_file: GooglePreparedFile | None
    original: GmailDecodedMessage | None
    mode: Literal["new", "reply", "forward"]
    reply_all: bool
    quote_original: bool
    source_attachments: tuple[GmailSourceAttachment, ...]


@dataclasses.dataclass(frozen=True)
class GmailPreparedMessage:
    raw: str = dataclasses.field(repr=False)
    thread_id: str | None
    recipient_count: int


def validate_input_files(
    message: GmailCompose,
    attachments: tuple[GooglePreparedFile, ...],
    body_file: GooglePreparedFile | None,
) -> str | None:
    if len(message.attachments) != len(attachments) or (message.body_file is None) != (
        body_file is None
    ):
        raise ValueError("Every canonical Gmail input must be resolved first.")
    if (
        len(attachments) > 25
        or sum(file.size for file in attachments) > GMAIL_ATTACHMENT_MAXIMUM_BYTES
    ):
        raise GoogleSdkError("gmail_attachment_limit", dispatched=False, status=None)
    if body_file is not None:
        if body_file.size > GMAIL_MESSAGE_MAXIMUM_BYTES:
            raise GoogleSdkError("gmail_message_limit", dispatched=False, status=None)
        try:
            return body_file.content.decode("utf-8")
        except UnicodeDecodeError:
            raise GoogleSdkError(
                "body_file_requires_utf8", dispatched=False, status=None
            ) from None
    return None


def prepare_message(value: GmailMimeContext) -> GmailPreparedMessage:
    content = value.message
    file_body = validate_input_files(content, value.attachments, value.body_file)
    files = (*value.attachments, *(item.file for item in value.source_attachments))
    if (
        len(files) > 25
        or sum(file.size for file in files) > GMAIL_ATTACHMENT_MAXIMUM_BYTES
    ):
        raise GoogleSdkError("gmail_attachment_limit", dispatched=False, status=None)
    sender = content.sender
    if sender is None and value.primary_email is not None:
        sender = GmailMailbox(email=value.primary_email, display_name=None)
    to, cc, bcc = content.to, content.cc, content.bcc
    subject = content.subject
    text, rich = content.text, content.html
    if file_body is not None:
        if content.body_file_format == "html":
            rich = file_body
        else:
            text = file_body
    unquoted_text = text
    result = EmailMessage(policy=policy.SMTP)
    if sender is not None:
        result["From"] = _addresses((sender,))
    original = value.original
    thread_id: str | None = None
    if value.mode != "new":
        if original is None:
            raise ValueError(
                "Related Gmail composition requires a verified source read."
            )
        source = original.value
        headers = GmailPart(headers=source.headers)
        original_subject = _display_header(headers, "Subject") or ""
        if subject is None:
            prefix = "Re:" if value.mode == "reply" else "Fwd:"
            subject = (
                original_subject
                if original_subject.casefold().startswith(prefix.casefold())
                else f"{prefix} {original_subject}"
            )
        if value.mode == "reply":
            normalized_subject = (
                re.sub(r"^(?:re\s*:\s*)+", "", subject or "", flags=re.IGNORECASE)
                .strip()
                .casefold()
            )
            normalized_original = (
                re.sub(r"^(?:re\s*:\s*)+", "", original_subject, flags=re.IGNORECASE)
                .strip()
                .casefold()
            )
            if normalized_subject != normalized_original:
                raise GoogleSdkError(
                    "reply_subject_mismatch", dispatched=True, status=None
                )
            message_id = source_header(headers, "Message-ID")
            if (
                message_id is None
                or re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", message_id) is None
                or source.thread_id is None
            ):
                raise GoogleSdkError(
                    "reply_metadata_unavailable", dispatched=True, status=None
                )
            references = (source_header(headers, "References") or "").split()
            if len(references) > 100 or any(
                re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", reference) is None
                for reference in references
            ):
                raise GoogleSdkError(
                    "invalid_reply_references", dispatched=True, status=None
                )
            result["In-Reply-To"] = message_id
            result["References"] = " ".join(dict.fromkeys((*references, message_id)))
            thread_id = source.thread_id
            excluded = {
                address.casefold()
                for address in (
                    value.primary_email,
                    None if sender is None else sender.email,
                )
                if address is not None
            }
            if not to:
                to = _unique(
                    _mailboxes(
                        source_header(headers, "Reply-To")
                        or source_header(headers, "From")
                    ),
                    excluded,
                )
            if value.reply_all:
                to = _unique((*to, *_mailboxes(source_header(headers, "To"))), excluded)
                cc = _unique(
                    (*cc, *_mailboxes(source_header(headers, "Cc"))),
                    excluded | {address.email.casefold() for address in to},
                )
        if value.quote_original:
            if any(
                part.status in {"unsupported_charset", "invalid_encoding"}
                for part in source.body_parts
            ):
                raise GoogleSdkError(
                    "original_body_unavailable", dispatched=True, status=None
                )
            heading = (
                "\n\n---------- Original message ----------\n"
                if value.mode == "forward"
                else "\n\n---------- Reply context ----------\n"
            )
            quoted_headers = "\n".join(
                f"{name}: {header}"
                for name in ("From", "Date", "Subject", "To", "Cc")
                if (header := _display_header(headers, name)) is not None
            )
            original_plain = original.plain_text or ""
            if original.plain_text is not None:
                text = (text or "") + heading + quoted_headers + "\n\n" + original_plain
            if original.html_text is not None or rich is not None:
                rich = (
                    (rich if rich is not None else html.escape(unquoted_text or ""))
                    + "<br><br>"
                    + html.escape(heading + quoted_headers)
                    + "<blockquote>"
                    + (
                        original.html_text
                        if original.html_text is not None
                        else html.escape(original_plain)
                    )
                    + "</blockquote>"
                )
    if to:
        result["To"] = _addresses(to)
    if cc:
        result["Cc"] = _addresses(cc)
    if bcc:
        result["Bcc"] = _addresses(bcc)
    if content.reply_to:
        result["Reply-To"] = _addresses(content.reply_to)
    result["Subject"] = subject or ""
    result["Date"] = format_datetime(datetime.now(UTC))
    result["Message-ID"] = make_msgid(domain="azents.invalid")
    if rich is not None:
        if text is not None:
            result.set_content(text)
            result.add_alternative(rich, subtype="html")
        else:
            result.set_content(rich, subtype="html")
    else:
        result.set_content(text or "")
    for file in value.attachments:
        main_type, sub_type = file.media_type.split("/", 1)
        result.add_attachment(
            file.content, maintype=main_type, subtype=sub_type, filename=file.filename
        )
    for attachment in value.source_attachments:
        file = attachment.file
        main_type, sub_type = file.media_type.split("/", 1)
        rich_body = result.get_body(preferencelist=("html",))
        if (
            attachment.inline
            and attachment.content_id is not None
            and rich_body is not None
        ):
            rich_body.add_related(
                file.content,
                maintype=main_type,
                subtype=sub_type,
                filename=file.filename,
                cid=attachment.content_id,
                disposition="inline",
            )
        else:
            result.add_attachment(
                file.content,
                maintype=main_type,
                subtype=sub_type,
                filename=file.filename,
            )
    raw = result.as_bytes()
    if len(raw) > GMAIL_MESSAGE_MAXIMUM_BYTES:
        raise GoogleSdkError("gmail_message_limit", dispatched=False, status=None)
    return GmailPreparedMessage(
        raw=base64.urlsafe_b64encode(raw).decode("ascii"),
        thread_id=thread_id,
        recipient_count=len(to) + len(cc) + len(bcc),
    )


@dataclasses.dataclass(frozen=True)
class GmailParsedDraft:
    message: GmailMessageEnvelope
    original: bytes = dataclasses.field(repr=False)


def parse_raw_draft(message: GmailMessageEnvelope) -> GmailParsedDraft:
    """Use drafts.get(raw) without borrowing mailbox-read access for draft bodies."""
    if message.raw is None:
        raise GoogleSdkError("draft_raw_unavailable", dispatched=True, status=None)
    content = decode_gmail_bytes(
        message.raw, maximum_bytes=GMAIL_MESSAGE_MAXIMUM_BYTES, expected_size=None
    )
    count = 0

    class LimitedMessage(EmailMessage):
        def __init__(self, policy: Policy | None = None) -> None:
            nonlocal count
            count += 1
            if count > 1000:
                raise GoogleSdkError(
                    "mime_structure_limit", dispatched=True, status=None
                )
            super().__init__(policy=policy)

    def convert(part: Message, part_id: str, depth: int) -> GmailPart:
        if depth > 20 or part.defects:
            raise GoogleSdkError("invalid_mime_structure", dispatched=True, status=None)
        headers = tuple(
            GmailHeader(name=name, value=str(value)) for name, value in part.items()
        )
        filename = part.get_filename() or ""
        disposition = part.get_content_disposition()
        if part.is_multipart():
            # Attached containers stay opaque. The exact original RFC822 file is
            # also published without reserialization.
            if filename or disposition == "attachment":
                return GmailPart(
                    partId=part_id,
                    mimeType=part.get_content_type(),
                    filename=filename or "attached-message.eml",
                    headers=headers,
                    body=None,
                )
            payload = part.get_payload()
            if not isinstance(payload, list) or any(
                not isinstance(child, Message) for child in payload
            ):
                raise GoogleSdkError(
                    "invalid_mime_structure", dispatched=True, status=None
                )
            children: list[GmailPart] = []
            for index, child in enumerate(payload):
                if not isinstance(child, Message):
                    raise GoogleSdkError(
                        "invalid_mime_structure", dispatched=True, status=None
                    )
                child_id = f"{part_id}.{index}" if part_id else str(index)
                children.append(convert(child, child_id, depth + 1))
            return GmailPart(
                partId=part_id,
                mimeType=part.get_content_type(),
                filename=filename,
                headers=headers,
                parts=tuple(children),
            )
        body = part.get_payload(decode=True)
        if not isinstance(body, bytes) or part.defects:
            raise GoogleSdkError("invalid_mime_encoding", dispatched=True, status=None)
        return GmailPart(
            partId=part_id,
            mimeType=part.get_content_type(),
            filename=filename,
            headers=headers,
            body=GmailBody(
                data=base64.urlsafe_b64encode(body).decode("ascii"), size=len(body)
            ),
        )

    try:
        parsed = BytesParser(_class=LimitedMessage, policy=policy.default).parsebytes(
            content
        )
        envelope = GmailMessageEnvelope(
            id=message.id,
            threadId=message.thread_id,
            labelIds=message.label_ids,
            snippet=message.snippet,
            sizeEstimate=message.size_estimate,
            payload=convert(parsed, "", 0),
            raw=None,
        )
    except RecursionError:
        raise GoogleSdkError(
            "mime_structure_limit", dispatched=True, status=None
        ) from None
    return GmailParsedDraft(envelope, content)
