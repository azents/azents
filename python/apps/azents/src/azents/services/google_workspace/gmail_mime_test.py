"""MIME correctness, original byte preservation and bounded parsing/composition."""

import base64
import dataclasses
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import pytest
from pydantic import ValidationError

from azents.services.google_workspace import gmail_mime
from azents.services.google_workspace.file_models import (
    GoogleFileInput,
    GooglePreparedFile,
)
from azents.services.google_workspace.gmail_mime import (
    GmailMimeContext,
    GmailPreparedMessage,
    GmailSourceAttachment,
    decode_gmail_bytes,
    decode_message,
    message_parts,
    parse_raw_draft,
    prepare_message,
)
from azents.services.google_workspace.gmail_models import (
    GmailBody,
    GmailCompose,
    GmailHeader,
    GmailMailbox,
    GmailMessageEnvelope,
    GmailPart,
)
from azents.services.google_workspace.transport import GoogleSdkError


@pytest.fixture
def compose() -> GmailCompose:
    return GmailCompose(
        sender=None,
        to=(GmailMailbox(email="reader@example.com", display_name="Reader"),),
        cc=(),
        bcc=(),
        reply_to=(),
        subject="Project review",
        text="Review details.",
        html=None,
        body_file=None,
        body_file_format=None,
        attachments=(),
    )


def _change(value: GmailCompose, **changes: object) -> GmailCompose:
    payload = value.model_dump()
    payload.update(changes)
    return GmailCompose.model_validate(payload)


def _context(compose: GmailCompose) -> GmailMimeContext:
    return GmailMimeContext(
        message=compose,
        primary_email="connected@example.com",
        attachments=(),
        body_file=None,
        original=None,
        mode="new",
        reply_all=False,
        quote_original=False,
        source_attachments=(),
    )


def _parsed(value: GmailPreparedMessage) -> EmailMessage:
    result = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(value.raw)
    )
    assert isinstance(result, EmailMessage)
    return result


def _original() -> GmailMessageEnvelope:
    body = "Original message body.".encode()
    return GmailMessageEnvelope(
        id="original",
        threadId="thread",
        payload=GmailPart(
            partId="",
            mimeType="text/plain",
            headers=(
                GmailHeader(name="From", value="Alice <alice@example.com>"),
                GmailHeader(name="Reply-To", value="reply@example.com"),
                GmailHeader(
                    name="To",
                    value=(
                        "Connected <connected@example.com>, Other <other@example.com>"
                    ),
                ),
                GmailHeader(name="Cc", value="cc@example.com"),
                GmailHeader(name="Bcc", value="private@example.com"),
                GmailHeader(name="Subject", value="Original subject"),
                GmailHeader(name="Message-ID", value="<original@example.com>"),
                GmailHeader(name="References", value="<older@example.com>"),
            ),
            body=GmailBody(
                data=base64.urlsafe_b64encode(body).decode(), size=len(body)
            ),
        ),
    )


def _read_body(part: GmailPart, maximum: int) -> bytes:
    assert part.body is not None and part.body.data is not None
    return decode_gmail_bytes(
        part.body.data, maximum_bytes=maximum, expected_size=part.body.size
    )


@pytest.mark.parametrize("data", [b"", b"f", b"fo", b"foo", bytes(range(256))])
def test_canonical_urlsafe_base64_preserves_every_byte(data: bytes) -> None:
    encoded = base64.urlsafe_b64encode(data).decode()
    assert (
        decode_gmail_bytes(encoded, maximum_bytes=len(data), expected_size=len(data))
        == data
    )
    assert (
        decode_gmail_bytes(
            encoded.rstrip("="), maximum_bytes=len(data), expected_size=len(data)
        )
        == data
    )


@pytest.mark.parametrize(
    "encoded", ["%not-base64", "a", "Zg===", "Zh==", "Zm9=", "Zg/+"]
)
def test_invalid_or_noncanonical_base64_is_rejected(encoded: str) -> None:
    with pytest.raises(GoogleSdkError):
        decode_gmail_bytes(encoded, maximum_bytes=100, expected_size=None)


def test_announced_and_measured_decoded_size_must_agree() -> None:
    with pytest.raises(GoogleSdkError, match="not be confirmed"):
        decode_gmail_bytes("Zm9v", maximum_bytes=100, expected_size=5)
    with pytest.raises(GoogleSdkError):
        decode_gmail_bytes("Zm9v", maximum_bytes=2, expected_size=None)


@pytest.mark.parametrize(
    "email,display",
    [
        ("attacker@example.com\r\nBcc: victim@example.com", None),
        ("user@example.com, other@example.com", None),
        ("missing-domain", None),
        ("user@example.com", "Name\nBcc: victim@example.com"),
    ],
)
def test_mailbox_fields_cannot_inject_headers(email: str, display: str | None) -> None:
    with pytest.raises(ValidationError):
        GmailMailbox(email=email, display_name=display)


def test_korean_subject_display_name_and_body_survive_mime_roundtrip(
    compose: GmailCompose,
) -> None:
    message = _change(
        compose,
        sender={"email": "connected@example.com", "display_name": "건우"},
        subject="프로젝트 검토",
        text="안녕하세요. 검토 부탁드립니다.",
    )
    parsed = _parsed(prepare_message(_context(message)))
    assert str(parsed["Subject"]) == "프로젝트 검토"
    assert "건우" in str(parsed["From"])
    assert parsed.get_content().strip() == "안녕하세요. 검토 부탁드립니다."


def test_binary_attachment_is_preserved_without_inline_base64_in_result(
    compose: GmailCompose,
) -> None:
    source = GoogleFileInput(
        source="artifact://fixture",
        filename="sample.bin",
        media_type="application/octet-stream",
    )
    message = _change(compose, attachments=[source.model_dump()])
    content = bytes(range(256))
    prepared = GooglePreparedFile("sample.bin", "application/octet-stream", content, ())
    parsed = _parsed(
        prepare_message(dataclasses.replace(_context(message), attachments=(prepared,)))
    )
    attachments = list(parsed.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_payload(decode=True) == content
    assert attachments[0].get_filename() == "sample.bin"


def test_reply_preserves_thread_references_and_uses_reply_to_without_copying_bcc(
    compose: GmailCompose,
) -> None:
    original = decode_message(_original(), character_limit=1000, read_body=_read_body)
    message = _change(compose, to=[], subject=None)
    prepared = prepare_message(
        dataclasses.replace(
            _context(message),
            mode="reply",
            original=original,
            reply_all=True,
            quote_original=True,
        )
    )
    parsed = _parsed(prepared)
    assert prepared.thread_id == "thread"
    assert prepared.recipient_count == 3
    assert str(parsed["In-Reply-To"]) == "<original@example.com>"
    assert str(parsed["References"]) == "<older@example.com> <original@example.com>"
    assert str(parsed["Subject"]) == "Re: Original subject"
    assert "reply@example.com" in str(parsed["To"])
    assert "other@example.com" in str(parsed["To"])
    assert "connected@example.com" not in str(parsed["To"])
    assert "cc@example.com" in str(parsed["Cc"])
    assert parsed["Bcc"] is None
    assert "Original message body." in parsed.get_content()


def test_forward_does_not_attach_to_original_thread(compose: GmailCompose) -> None:
    original = decode_message(_original(), character_limit=1000, read_body=_read_body)
    prepared = prepare_message(
        dataclasses.replace(
            _context(_change(compose, subject=None)),
            mode="forward",
            original=original,
            quote_original=True,
        )
    )
    parsed = _parsed(prepared)
    assert prepared.thread_id is None
    assert parsed["In-Reply-To"] is None
    assert str(parsed["Subject"]) == "Fwd: Original subject"


def test_reused_inline_image_retains_content_id_and_related_mime_structure(
    compose: GmailCompose,
) -> None:
    original = decode_message(_original(), character_limit=1000, read_body=_read_body)
    original = dataclasses.replace(
        original, html_text='<p>Original</p><img src="cid:image1">'
    )
    image = GooglePreparedFile(
        "image.png", "image/png", b"fixture-image", ("original",)
    )
    prepared = prepare_message(
        dataclasses.replace(
            _context(compose),
            mode="forward",
            original=original,
            quote_original=True,
            source_attachments=(GmailSourceAttachment(image, "<image1>", True),),
        )
    )
    parsed = _parsed(prepared)
    matches = [part for part in parsed.walk() if str(part["Content-ID"]) == "<image1>"]
    assert len(matches) == 1 and matches[0].get_payload(decode=True) == b"fixture-image"
    assert any(part.get_content_type() == "multipart/related" for part in parsed.walk())


def test_body_file_text_is_kept_in_html_alternative_when_quoting(
    compose: GmailCompose,
) -> None:
    body_source = GoogleFileInput(
        source="exchange://fixture", filename=None, media_type=None
    )
    message = _change(
        compose, text=None, body_file=body_source.model_dump(), body_file_format="plain"
    )
    original = dataclasses.replace(
        decode_message(_original(), character_limit=1000, read_body=_read_body),
        html_text="<p>Original HTML</p>",
    )
    body_file = GooglePreparedFile("body.txt", "text/plain", b"Prepared file body.", ())
    parsed = _parsed(
        prepare_message(
            dataclasses.replace(
                _context(message),
                mode="forward",
                original=original,
                quote_original=True,
                body_file=body_file,
            )
        )
    )
    rich = parsed.get_body(preferencelist=("html",))
    assert rich is not None and "Prepared file body." in rich.get_content()


def test_truncated_text_is_a_preview_and_keeps_full_original_bytes() -> None:
    original = _original()
    result = decode_message(original, character_limit=4, read_body=_read_body)
    assert result.value.body_parts[0].text == "Orig"
    assert result.value.body_parts[0].status == "truncated"
    assert result.files[0].content == b"Original message body."
    assert result.plain_text == "Original message body."


def test_unknown_charset_keeps_original_file_without_claiming_extracted_text() -> None:
    envelope = GmailMessageEnvelope(
        id="message",
        payload=GmailPart(
            mimeType="text/plain",
            headers=(
                GmailHeader(
                    name="Content-Type", value="text/plain; charset=unknown-encoding"
                ),
            ),
            body=GmailBody(data="YWJj", size=3),
        ),
    )
    result = decode_message(envelope, character_limit=100, read_body=_read_body)
    assert result.value.body_parts[0].status == "unsupported_charset"
    assert result.value.body_parts[0].text is None
    assert result.files[0].content == b"abc"


def test_opaque_attached_message_is_not_quoted_as_ordinary_body() -> None:
    payload = GmailPart(
        mimeType="multipart/mixed",
        parts=(
            GmailPart(
                mimeType="message/rfc822",
                filename="attached.eml",
                parts=(
                    GmailPart(
                        mimeType="text/plain", body=GmailBody(data="c2VjcmV0", size=6)
                    ),
                ),
            ),
        ),
    )
    result = decode_message(
        GmailMessageEnvelope(id="message", payload=payload),
        character_limit=100,
        read_body=_read_body,
    )
    assert not result.value.body_parts
    assert result.value.attachments[0].filename == "attached.eml"


def test_parse_raw_draft_preserves_exact_rfc822_and_decodes_binary_parts() -> None:
    original = EmailMessage(policy=policy.SMTPUTF8)
    original["From"] = "connected@example.com"
    original["To"] = "reader@example.com"
    original["Subject"] = "초안"
    original.set_content("Draft text.")
    original.add_attachment(
        b"\x00\xffbinary",
        maintype="application",
        subtype="octet-stream",
        filename="sample.bin",
    )
    raw = original.as_bytes()
    envelope = GmailMessageEnvelope(
        id="message", threadId="thread", raw=base64.urlsafe_b64encode(raw).decode()
    )
    parsed = parse_raw_draft(envelope)
    assert parsed.original == raw
    assert parsed.message.payload is not None
    assert any(
        header.name == "Subject" and header.value == "초안"
        for header in parsed.message.payload.headers
    )
    parts = tuple(message_parts(parsed.message.payload))
    assert _read_body(parts[1], 100) == b"\x00\xffbinary"
    decoded = decode_message(parsed.message, character_limit=1000, read_body=_read_body)
    assert (
        decoded.plain_text is not None and decoded.plain_text.strip() == "Draft text."
    )


def test_raw_draft_parser_stops_at_bounded_part_count() -> None:
    raw = (
        b'MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary="x"\r\n\r\n'
        + b"--x\r\nContent-Type: text/plain\r\n\r\npart\r\n" * 1001
        + b"--x--\r\n"
    )
    with pytest.raises(GoogleSdkError) as error:
        parse_raw_draft(
            GmailMessageEnvelope(
                id="message", raw=base64.urlsafe_b64encode(raw).decode()
            )
        )
    assert error.value.code == "mime_structure_limit"


def test_parser_rejects_excessive_payload_depth() -> None:
    part = GmailPart(mimeType="text/plain", body=GmailBody(data="eA==", size=1))
    for _ in range(22):
        part = GmailPart(mimeType="multipart/mixed", parts=(part,))
    with pytest.raises(GoogleSdkError) as error:
        tuple(message_parts(part))
    assert error.value.code == "mime_structure_limit"


def test_outbound_size_limits_are_checked_before_dispatch(
    compose: GmailCompose, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gmail_mime, "GMAIL_MESSAGE_MAXIMUM_BYTES", 100)
    with pytest.raises(GoogleSdkError) as error:
        prepare_message(_context(compose))
    assert error.value.code == "gmail_message_limit"
    assert not error.value.dispatched


def test_reply_subject_must_preserve_original_thread_subject(
    compose: GmailCompose,
) -> None:
    original = decode_message(_original(), character_limit=1000, read_body=_read_body)
    with pytest.raises(GoogleSdkError) as error:
        prepare_message(
            dataclasses.replace(
                _context(compose),
                mode="reply",
                original=original,
            )
        )
    assert error.value.code == "reply_subject_mismatch"
