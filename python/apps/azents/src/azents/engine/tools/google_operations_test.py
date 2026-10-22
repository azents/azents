"""Canonical files, partial outcomes and typed SDK calls cross the engine boundary."""

import base64
import dataclasses
import hashlib
import json
from unittest.mock import AsyncMock, NonCallableMock

import httpx
import pytest
from azcommon.result import Success

from azents.core.google_policy import GoogleService
from azents.core.google_runtime import GoogleExecutionState
from azents.core.google_tool_groups import groups_for_services
from azents.core.google_workspace_policy import GoogleWorkspaceOperation as Op
from azents.core.tools import GoogleToolkitConfig
from azents.engine.run.types import FunctionToolError, FunctionToolResult
from azents.engine.tools.google import GoogleToolkit
from azents.engine.tools.google_files import GoogleFileBridge
from azents.engine.tools.google_files_test import _artifact, _bridge, _vfs
from azents.engine.tools.google_test import _context, _sdk, _turn
from azents.services.google_oauth.runtime_test import _harness
from azents.services.google_workspace import gmail_models as gm
from azents.services.google_workspace.drive_models import DriveCreateFileInput
from azents.services.google_workspace.file_models import GoogleFileInput
from azents.services.google_workspace.transport import GoogleWorkspaceSdk


def _mock(value: object) -> NonCallableMock:
    assert isinstance(value, NonCallableMock)
    return value


@pytest.mark.parametrize(
    "model", [gm.GmailFilterCreateInput, gm.GmailFilterReplaceInput]
)
def test_filter_schema_describes_persistent_forwarding(
    model: type[gm.GmailFilterCreateInput],
) -> None:
    schema = model.model_json_schema()
    description = schema["$defs"]["GmailFilterAction"]["properties"]["forward"][
        "description"
    ]
    assert all(
        text in description
        for text in (
            "future matching mail",
            "Google-verified",
            "persistent",
            "disabled or disconnected",
            "labels only",
            "historical messages",
        )
    )


def _workspace_toolkit(
    service: GoogleService,
    scope: str,
    sdk: GoogleWorkspaceSdk,
    bridge: GoogleFileBridge,
) -> GoogleToolkit:
    h = _harness(expired=False)
    current = dataclasses.replace(
        h.current,
        config=GoogleToolkitConfig(
            services=(service,),
            oauth_request_scopes=("https://www.googleapis.com/auth/" + scope,),
            timeout=h.current.config.timeout,
            tool_groups=groups_for_services((service,)),
        ),
        connection=dataclasses.replace(
            h.current.connection,
            candidate=h.current.connection.candidate.model_copy(
                update={
                    "tokens": h.current.connection.candidate.tokens.model_copy(
                        update={
                            "granted_scopes": (
                                "https://www.googleapis.com/auth/" + scope,
                            )
                        }
                    )
                }
            ),
        ),
    )
    h.repo.load.return_value = current
    return GoogleToolkit(
        runtime=h.service,
        sdk=sdk,
        context=_context(),
        timeout=5,
        files=lambda authority: bridge,
    )


@pytest.mark.parametrize("source_current", [True, False])
async def test_drive_upload_resolves_and_revalidates_canonical_input(
    source_current: bool,
) -> None:
    bridge = _bridge()
    revalidate = AsyncMock(return_value=source_current)
    _mock(bridge.resolver).resolve.return_value = _vfs(b"canonical bytes", revalidate)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={
                    "location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=fixture"
                },
                stream=httpx.ByteStream(b""),
            )
        return httpx.Response(200, stream=httpx.ByteStream(b'{"id":"created"}'))

    toolkit = _workspace_toolkit(
        GoogleService.DRIVE, "drive.file", _sdk(handler), bridge
    )
    tool = next(
        item
        for item in (await toolkit.update_context(_turn())).tools
        if item.spec.name == Op.DRIVE_CREATE_FILE
    )
    value = DriveCreateFileInput(
        name="new.txt",
        parent_id=None,
        description=None,
        content=GoogleFileInput(
            source="azents://execution/output.txt", filename=None, media_type=None
        ),
        text=None,
        media_type="text/plain",
    )
    if not source_current:
        with pytest.raises(FunctionToolError, match="file_source_changed"):
            await tool.handler(value.model_dump_json())
        assert requests == []
        return
    result = await tool.handler(value.model_dump_json())
    assert isinstance(result, FunctionToolResult)
    assert [request.method for request in requests] == ["POST", "PUT"]
    assert requests[1].content == b"canonical bytes"
    assert "canonical bytes" not in str(result.output)
    assert revalidate.await_count >= 4


async def test_drive_original_output_is_canonical_artifact_not_file_bytes() -> None:
    bridge = _bridge()
    content = b"\x00\xffbinary-original"
    artifact = _artifact(content)
    _mock(bridge.artifacts).create_for_authority.return_value = Success(artifact)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("alt") == "media":
            return httpx.Response(
                200,
                headers={"content-length": str(len(content))},
                stream=httpx.ByteStream(content),
            )
        metadata = {
            "id": "file",
            "name": "original.bin",
            "mimeType": "application/octet-stream",
            "size": str(len(content)),
            "sha256Checksum": hashlib.sha256(content).hexdigest(),
        }
        return httpx.Response(
            200, stream=httpx.ByteStream(json.dumps(metadata).encode())
        )

    toolkit = _workspace_toolkit(
        GoogleService.DRIVE, "drive.readonly", _sdk(handler), bridge
    )
    tool = next(
        item
        for item in (await toolkit.update_context(_turn())).tools
        if item.spec.name == Op.DRIVE_DOWNLOAD_FILE
    )
    result = await tool.handler(
        json.dumps(
            {
                "file_id": "file",
                "resource_key": None,
                "follow_shortcuts": False,
                "acknowledge_abuse": False,
            }
        )
    )
    assert isinstance(result, FunctionToolResult)
    assert isinstance(result.output, list)
    assert result.output[1]["type"] == "artifact"
    assert result.output[1]["uri"] == artifact.uri
    assert result.output[1]["artifact_id"] == artifact.id
    assert "binary-original" not in str(result.output)
    call = _mock(bridge.artifacts).create_for_authority.call_args.kwargs
    assert call["body"] == content and call["authority"] == bridge.authority
    assert len(requests) == 2


async def test_gmail_raw_draft_is_published_with_original_bytes() -> None:
    bridge = _bridge()
    content = (
        b"From: user@example.com\r\nTo: other@example.com\r\n"
        b"Subject: Draft\r\n\r\nBody\r\n"
    )
    _mock(bridge.artifacts).create_for_authority.return_value = Success(
        _artifact(content)
    )
    body = {
        "id": "draft",
        "message": {
            "id": "message",
            "threadId": "thread",
            "raw": base64.urlsafe_b64encode(content).decode(),
        },
    }
    toolkit = _workspace_toolkit(
        GoogleService.GMAIL,
        "gmail.compose",
        _sdk(
            lambda request: httpx.Response(
                200, stream=httpx.ByteStream(json.dumps(body).encode())
            )
        ),
        bridge,
    )
    tool = next(
        item
        for item in (await toolkit.update_context(_turn())).tools
        if item.spec.name == Op.GMAIL_GET_DRAFT
    )
    result = await tool.handler('{"draft_id":"draft","body_character_limit":1000}')
    assert isinstance(result, FunctionToolResult)
    assert "artifact://" in str(result.output)
    assert base64.urlsafe_b64encode(content).decode() not in str(result.output)
    assert (
        _mock(bridge.artifacts).create_for_authority.call_args.kwargs["body"] == content
    )


async def test_grant_loss_between_upload_steps_retains_dispatched_uncertainty() -> None:
    bridge = _bridge()
    requests: list[httpx.Request] = []
    toolkit: GoogleToolkit

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        repository = _mock(toolkit.runtime.repository)
        current = repository.load.return_value
        assert isinstance(current, GoogleExecutionState)
        repository.load.return_value = dataclasses.replace(
            current, revision=current.revision + 1
        )
        return httpx.Response(
            200,
            headers={
                "location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=fixture"
            },
            stream=httpx.ByteStream(b""),
        )

    toolkit = _workspace_toolkit(
        GoogleService.DRIVE, "drive.file", _sdk(handler), bridge
    )
    tool = next(
        item
        for item in (await toolkit.update_context(_turn())).tools
        if item.spec.name == Op.DRIVE_CREATE_FILE
    )
    value = DriveCreateFileInput(
        name="new.txt",
        parent_id=None,
        description=None,
        content=None,
        text="pending",
        media_type="text/plain",
    )
    with pytest.raises(FunctionToolError, match="No request was replayed"):
        await tool.handler(value.model_dump_json())
    assert [request.method for request in requests] == ["POST"]
