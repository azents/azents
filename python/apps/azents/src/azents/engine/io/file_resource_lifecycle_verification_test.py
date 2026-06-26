"""File resource lifecycle deterministic verification tests."""

import datetime
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStartReason,
    AgentSessionStatus,
    ArtifactStatus,
    EventKind,
    WorkspaceUserRole,
)
from azents.core.llm_catalog import ModelCapabilities, ModelModalities, ModelModality
from azents.engine.events.file_parts import ModelFileLoweringContent
from azents.engine.events.litellm_responses import LiteLLMResponsesLowerer
from azents.engine.events.types import (
    ArtifactOutputPart,
    AttachmentOutputPart,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    EventPayload,
    FileOutputPart,
    NativeArtifact,
    build_native_compat_key,
)
from azents.engine.run.types import FunctionToolError
from azents.engine.tools.import_file import make_import_file_tool
from azents.engine.tools.testing import FakeSharedStorage
from azents.repos.agent_session.data import AgentSession
from azents.repos.artifact.data import Artifact, ArtifactCreate
from azents.repos.workspace_user.data import WorkspaceUser
from azents.services.artifact import ArtifactService

_NOW = datetime.datetime.now(datetime.timezone.utc)


class _FakeArtifactRepository:
    """Artifact repository for tests."""

    def __init__(self) -> None:
        self.artifacts: dict[str, Artifact] = {}
        self.next_id = "a" * 32

    async def create(self, session: AsyncSession, create: ArtifactCreate) -> Artifact:
        """Store Artifact create input."""
        del session
        artifact_id = self.next_id
        artifact = Artifact(
            id=artifact_id,
            workspace_id=create.workspace_id,
            session_id=create.session_id,
            agent_id=create.agent_id,
            created_run_id=create.created_run_id,
            created_run_index=create.created_run_index,
            expires_after_run_index=create.expires_after_run_index,
            name=create.name,
            media_type=create.media_type,
            size_bytes=create.size_bytes,
            storage_key=(
                f"artifacts/{create.workspace_id}/{create.session_id}/"
                f"{create.created_run_index}/{artifact_id}"
            ),
            status=ArtifactStatus.AVAILABLE,
            sha256=create.sha256,
            source_tool_name=create.source_tool_name,
            source_call_id=create.source_call_id,
            source_part_index=create.source_part_index,
            description=create.description,
            metadata=create.metadata,
            created_at=_NOW,
            expired_at=None,
        )
        self.artifacts[artifact.id] = artifact
        return artifact

    async def get_by_id(
        self,
        session: AsyncSession,
        artifact_id: str,
    ) -> Artifact | None:
        """Fetch Artifact by ID."""
        del session
        return self.artifacts.get(artifact_id)

    async def get_by_storage_key(
        self,
        session: AsyncSession,
        storage_key: str,
    ) -> Artifact | None:
        """Fetch Artifact by storage key."""
        del session
        for artifact in self.artifacts.values():
            if artifact.storage_key == storage_key:
                return artifact
        return None

    async def expire_for_run_boundary(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        current_run_index: int,
        expired_at: datetime.datetime,
    ) -> list[Artifact]:
        """Expire Artifact by run boundary."""
        del session
        expired: list[Artifact] = []
        for artifact in list(self.artifacts.values()):
            if (
                artifact.session_id == session_id
                and artifact.status == ArtifactStatus.AVAILABLE
                and artifact.expires_after_run_index < current_run_index
            ):
                updated = artifact.model_copy(
                    update={"status": ArtifactStatus.EXPIRED, "expired_at": expired_at}
                )
                self.artifacts[artifact.id] = updated
                expired.append(updated)
        return expired


class _FakeAgentSessionRepository:
    """AgentSession repository for tests."""

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> AgentSession | None:
        """Fetch AgentSession."""
        del session
        if session_id != "session-1":
            return None
        return AgentSession(
            id="session-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
            status=AgentSessionStatus.ACTIVE,
            start_reason=AgentSessionStartReason.INITIAL,
            title=None,
            title_source=None,
            title_generated_at=None,
            title_generation_event_id=None,
            end_reason=None,
            started_at=_NOW,
            ended_at=None,
            created_at=_NOW,
            updated_at=_NOW,
        )


class _FakeWorkspaceUserRepository:
    """WorkspaceUser repository for tests."""

    async def get_by_workspace_and_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser | None:
        """Fetch workspace membership."""
        del session
        if workspace_id != "workspace-1" or user_id != "user-1":
            return None
        return WorkspaceUser(
            id="workspace-user-1",
            workspace_id="workspace-1",
            user_id="user-1",
            name="Test User",
            locale="en-US",
            role=WorkspaceUserRole.MEMBER,
            created_at=_NOW,
            updated_at=_NOW,
        )


class _FakeS3Service:
    """Object storage for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []

    async def upload(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        """Store object."""
        del bucket, content_type
        self.objects[key] = body

    async def download_bytes(self, bucket: str, key: str) -> bytes | None:
        """Fetch object bytes."""
        del bucket
        return self.objects.get(key)

    async def delete(self, bucket: str, key: str) -> None:
        """Delete object."""
        del bucket
        self.deleted_keys.append(key)
        self.objects.pop(key, None)


class _WorkspaceS3Config:
    """Workspace S3 config for tests."""

    bucket = "test-bucket"


class _Config:
    """Config for tests."""

    workspace_s3 = _WorkspaceS3Config()


class _StaticModelFileResolver:
    """ModelFile resolver for tests."""

    def resolve(self, part: FileOutputPart) -> ModelFileLoweringContent | None:
        """Resolve Image FilePart as request-local data URL."""
        del part
        return ModelFileLoweringContent(data_url="data:image/png;base64,abc")


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Session manager for tests."""
    yield cast(AsyncSession, object())


def _artifact(
    *,
    call_id: str = "call-1",
    name: str = "tool",
    arguments: str = "{}",
) -> NativeArtifact:
    """Create native artifact for tests."""
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
        item={
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": arguments,
        },
    )


def _event(kind: EventKind, payload: EventPayload) -> Event:
    """Create event for tests."""
    return Event(
        id="0" * 32,
        session_id="session-1",
        kind=kind,
        payload=payload,
        created_at=_NOW,
    )


def _artifact_service() -> tuple[
    ArtifactService, _FakeArtifactRepository, _FakeS3Service
]:
    """Configure ArtifactService for tests."""
    artifact_repo = _FakeArtifactRepository()
    s3_service = _FakeS3Service()
    service = ArtifactService(
        artifact_repository=cast(Any, artifact_repo),
        agent_session_repository=cast(Any, _FakeAgentSessionRepository()),
        workspace_user_repository=cast(Any, _FakeWorkspaceUserRepository()),
        session_manager=_session_manager,
        s3_service=cast(Any, s3_service),
        config=cast(Any, _Config()),
    )
    return service, artifact_repo, s3_service


@pytest.mark.asyncio
async def test_artifact_output_import_and_expiration_e2e_path() -> None:
    """Verify Artifact creation, metadata lower, import, and expiration paths."""
    service, artifact_repo, _s3 = _artifact_service()
    created = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_id="run-1",
        created_run_index=1,
        filename="report.txt",
        media_type="text/plain",
        body=b"full artifact body",
        source_tool_name="mock_mcp",
        source_call_id="call-1",
    )
    assert isinstance(created, Success)
    artifact = created.value

    lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
    request = lowerer.lower(
        [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-1",
                    name="mock_mcp",
                    arguments="{}",
                    native_artifact=_artifact(),
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="mock_mcp",
                    status="completed",
                    output=[
                        ArtifactOutputPart(
                            artifact_id=artifact.id,
                            uri=artifact.uri,
                            name=artifact.name,
                            media_type=artifact.media_type,
                            size=artifact.size_bytes,
                            expires_after_run_index=artifact.expires_after_run_index,
                        )
                    ],
                ),
            ),
        ],
        model="gpt-5.1",
    )
    lowered_output = request.input[-1]["output"]
    assert isinstance(lowered_output, str)
    assert artifact.uri in lowered_output
    assert "full artifact body" not in lowered_output

    storage = FakeSharedStorage()
    import_tool = make_import_file_tool(
        session_storage=storage,
        exchange_file_service=AsyncMock(),
        artifact_service=service,
        session_id="session-1",
        agent_id="agent-1",
        user_id="user-1",
    )
    await import_tool.handler(json.dumps({"uri": artifact.uri}))
    assert storage.put_calls == [
        ("/tmp/agent/imports/report.txt", b"full artifact body")
    ]

    assert await service.expire_for_run_boundary(
        session_id="session-1",
        current_run_index=4,
    )
    assert artifact_repo.artifacts[artifact.id].status == ArtifactStatus.EXPIRED
    with pytest.raises(FunctionToolError, match="no longer available"):
        await import_tool.handler(json.dumps({"uri": artifact.uri}))


@pytest.mark.asyncio
async def test_attachment_output_lowers_as_metadata_only() -> None:
    """Attachment lowers to bounded metadata text, not rich input."""
    lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
    request = lowerer.lower(
        [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-1",
                    name="present_file",
                    arguments="{}",
                    native_artifact=_artifact(),
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="present_file",
                    status="completed",
                    output=[
                        AttachmentOutputPart(
                            attachment_id="file-1",
                            uri="exchange://exchange/workspace/files/file-1/original",
                            name="report.csv",
                            media_type="text/csv",
                            size=7,
                            preview_summary="a,b\\n1,2",
                        )
                    ],
                ),
            ),
        ],
        model="gpt-5.1",
    )

    lowered_output = request.input[-1]["output"]
    assert isinstance(lowered_output, str)
    assert "Attachment: report.csv" in lowered_output
    assert "exchange://exchange/workspace/files/file-1/original" in lowered_output
    assert "file_data" not in lowered_output


@pytest.mark.asyncio
async def test_file_part_capability_branch_e2e_path() -> None:
    """Same FilePart becomes rich input or placeholder depending on capability."""
    file_part = FileOutputPart(
        model_file_id="model-file-1",
        media_type="image/png",
        name="plot.png",
        size=123,
        kind="image",
    )
    transcript = [
        _event(
            EventKind.CLIENT_TOOL_CALL,
            ClientToolCallPayload(
                call_id="call-1",
                name="inspect_image",
                arguments="{}",
                native_artifact=_artifact(),
            ),
        ),
        _event(
            EventKind.CLIENT_TOOL_RESULT,
            ClientToolResultPayload(
                call_id="call-1",
                name="inspect_image",
                status="completed",
                output=[file_part],
            ),
        ),
    ]

    image_request = LiteLLMResponsesLowerer(
        provider="openai",
        model="gpt-5.1",
        model_capabilities=ModelCapabilities(
            modalities=ModelModalities(input=[ModelModality.IMAGE])
        ),
        model_file_resolver=_StaticModelFileResolver(),
    ).lower(transcript, model="gpt-5.1")
    assert image_request.input[-1]["output"] == [
        {
            "type": "input_image",
            "detail": "auto",
            "image_url": "data:image/png;base64,abc",
        }
    ]

    text_only_request = LiteLLMResponsesLowerer(
        provider="openai",
        model="text-only",
    ).lower(transcript, model="text-only")
    output = text_only_request.input[-1]["output"]
    assert isinstance(output, list)
    assert output[0]["type"] == "input_text"
    assert "model does not support this file input" in output[0]["text"]


@pytest.mark.asyncio
async def test_legacy_unsafe_payload_is_rewritten_to_safe_schema() -> None:
    """Legacy inline/provider payload is rewritten to current safe schema."""
    file_part = FileOutputPart.model_validate(
        {
            "type": "file",
            "model_file_id": "model-file-1",
            "media_type": "application/pdf",
            "name": "doc.pdf",
            "file_data": "data:application/pdf;base64,abc",
            "file_id": "provider-file-1",
            "metadata": {"file_data": "unsafe", "safe": "value"},
        }
    )

    file_data = file_part.model_dump(mode="json")
    assert "file_data" not in file_data
    assert "file_id" not in file_data
    assert file_part.metadata == {"safe": "value"}
