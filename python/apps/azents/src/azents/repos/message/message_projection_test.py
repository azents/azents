"""Message projection tests."""

import datetime

from pydantic import TypeAdapter

from azents.core.enums import EventKind, MessageRole
from azents.engine.events.types import (
    Attachment,
    AttachmentOutputPart,
    ClientToolResultPayload,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolReference,
    ProviderToolResultPayload,
    ProviderToolSemanticContent,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.rdb.models.event import JSONValue, RDBEvent
from azents.repos.message import event_to_chat_message

_JSON_PAYLOAD_ADAPTER: TypeAdapter[dict[str, JSONValue]] = TypeAdapter(
    dict[str, JSONValue]
)


def _native_artifact() -> NativeArtifact:
    """Create native artifact for message projection tests."""
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="litellm",
            native_format="responses",
            provider="openai",
            model="gpt-5.1",
            schema_version="1",
        ),
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item={"type": "provider_tool"},
    )


def test_tool_result_attachment_output_part_projects_to_rest_attachment() -> None:
    """Preserve Tool result attachment output part as REST attachment."""
    payload = _JSON_PAYLOAD_ADAPTER.validate_python(
        ClientToolResultPayload(
            call_id="call-present",
            name="present_file",
            status="completed",
            output=[
                OutputTextPart(text="Presented 1 file(s) to user: report.txt"),
                AttachmentOutputPart(
                    uri="exchange://exchange/workspace/files/file-1/original",
                    name="report.txt",
                    media_type="text/plain",
                    size=123,
                    preview_summary="preview text",
                ),
            ],
        ).model_dump(mode="json", exclude_none=True)
    )
    row = RDBEvent(
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=payload,
        model_order=1,
    )
    row.created_at = datetime.datetime.now(datetime.UTC)

    message = event_to_chat_message(row)

    assert message is not None
    assert message.role == MessageRole.TOOL
    assert message.content == "Presented 1 file(s) to user: report.txt"
    assert message.tool_call_id == "call-present"
    assert len(message.attachments) == 1
    attachment = message.attachments[0]
    assert attachment.uri == "exchange://exchange/workspace/files/file-1/original"
    assert attachment.name == "report.txt"
    assert attachment.media_type == "text/plain"
    assert attachment.size == 123
    assert attachment.text_preview == "preview text"


def test_user_message_attachment_projection_preserves_download_identity() -> None:
    """REST history projection preserves attachment rendering information."""
    created_at = datetime.datetime(2026, 6, 3, tzinfo=datetime.UTC)
    payload = _JSON_PAYLOAD_ADAPTER.validate_python(
        UserMessagePayload(
            content="image please",
            attachments=[
                Attachment(
                    attachment_id="019e8c012f6272d1af2a1b0fb6b34e8b",
                    uri=(
                        "exchange://exchange/workspace/files/"
                        "019e8c012f6272d1af2a1b0fb6b34e8b/original"
                    ),
                    name="IMG_5269.jpeg",
                    media_type="image/jpeg",
                    size=1_988_356,
                    created_at=created_at,
                    availability="available",
                    preview_title="IMG_5269.jpeg",
                    preview_summary="Preview title: IMG_5269.jpeg",
                    preview_thumbnail_uri=(
                        "exchange://exchange/workspace/files/"
                        "019e8c012f6272d1af2a1b0fb6b34e8b/preview"
                    ),
                    preview_thumbnail_media_type="image/jpeg",
                    preview_thumbnail_width=300,
                    preview_thumbnail_height=225,
                    preview_generated_at=created_at,
                )
            ],
        ).model_dump(mode="json", exclude_none=True)
    )
    row = RDBEvent(
        session_id="session-1",
        kind=EventKind.USER_MESSAGE,
        payload=payload,
        model_order=1,
    )
    row.created_at = created_at

    message = event_to_chat_message(row)

    assert message is not None
    assert message.role == MessageRole.USER
    assert len(message.attachments) == 1
    attachment = message.attachments[0]
    assert attachment.attachment_id == "019e8c012f6272d1af2a1b0fb6b34e8b"
    assert attachment.preview_thumbnail_uri is not None
    assert attachment.preview_title == "IMG_5269.jpeg"
    assert attachment.preview_thumbnail_media_type == "image/jpeg"
    assert attachment.preview_thumbnail_width == 300
    assert attachment.preview_thumbnail_height == 225
    assert attachment.preview_generated_at == created_at


def test_provider_tool_call_projects_semantic_output_and_references() -> None:
    """REST message projection preserves complete provider-call semantics."""
    provider_payload = ProviderToolCallPayload(
        call_id="call-search",
        name="web_search",
        status="completed",
        semantic=ProviderToolSemanticContent(
            input='{"query":"Azents"}',
            output=[OutputTextPart(text="search complete")],
            references=[
                ProviderToolReference(
                    kind="url",
                    uri="https://example.com/source",
                    title=None,
                    excerpt=None,
                    metadata={},
                )
            ],
        ),
        attachments=[],
        native_artifact=_native_artifact(),
    )
    row = RDBEvent(
        session_id="session-1",
        kind=EventKind.PROVIDER_TOOL_CALL,
        payload=_JSON_PAYLOAD_ADAPTER.validate_python(
            provider_payload.model_dump(mode="json", exclude_none=True)
        ),
        model_order=1,
    )
    row.created_at = datetime.datetime.now(datetime.UTC)

    message = event_to_chat_message(row)

    assert message is not None
    assert message.tool_calls is not None
    assert message.tool_calls[0].arguments == '{"query":"Azents"}'
    assert message.content is not None
    assert "Output:\nsearch complete" in message.content
    assert "References:\n- url: https://example.com/source" in message.content


def test_provider_tool_result_projects_semantic_input_output_and_references() -> None:
    """REST message projection preserves complete provider-result semantics."""
    provider_payload = ProviderToolResultPayload(
        call_id="result-search",
        name="file_search",
        status="completed",
        semantic=ProviderToolSemanticContent(
            input="find the design",
            output=[OutputTextPart(text="design found")],
            references=[
                ProviderToolReference(
                    kind="file",
                    uri=None,
                    title="design.md",
                    excerpt="Relevant design",
                    metadata={"file_id": "file-1"},
                )
            ],
        ),
        attachments=[],
        native_artifact=_native_artifact(),
    )
    row = RDBEvent(
        session_id="session-1",
        kind=EventKind.PROVIDER_TOOL_RESULT,
        payload=_JSON_PAYLOAD_ADAPTER.validate_python(
            provider_payload.model_dump(mode="json", exclude_none=True)
        ),
        model_order=1,
    )
    row.created_at = datetime.datetime.now(datetime.UTC)

    message = event_to_chat_message(row)

    assert message is not None
    assert message.content is not None
    assert "Input:\nfind the design" in message.content
    assert "Output:\ndesign found" in message.content
    assert "References:\n- file: design.md" in message.content
