"""Provider-generated image decoding and materialization tests."""

import base64
import datetime
from contextlib import AbstractAsyncContextManager
from io import BytesIO
from typing import IO, cast

import pytest
from azcommon.infra.s3.service import S3Service
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

import azents.engine.events.provider_output as provider_output
from azents.core.config import Config, FileLifecycleConfig, WorkspaceS3Config
from azents.core.enums import EventKind
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.events.provider_output import (
    ProviderOutputMaterializer,
    generated_image_output,
    pending_image_generation_output,
)
from azents.engine.events.types import (
    AgentRunState,
    ClientToolResultPayload,
    Event,
    FileOutputPart,
    NativeArtifact,
    ProviderToolResultPayload,
    build_native_compat_key,
)
from azents.engine.run.errors import ModelCallError
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.data import ExchangeFile, ExchangeFileCreate
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file.data import ModelFile, ModelFileCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService

_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ"
    "/pLvAAAAAElFTkSuQmCC"
)


def _png_base64(*, width: int, height: int) -> str:
    """Create a compact valid PNG fixture with controlled dimensions."""
    body = BytesIO()
    Image.new("1", (width, height)).save(body, format="PNG")
    return base64.b64encode(body.getvalue()).decode()


class _Session(AsyncSession):
    """No-op AsyncSession test value."""


class _SessionContext(AbstractAsyncContextManager[AsyncSession]):
    """Return one no-op session."""

    async def __aenter__(self) -> AsyncSession:
        return _Session()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback


class _SessionManager:
    """Callable session manager test double."""

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return _SessionContext()


class _AgentSessionRepository(AgentSessionRepository):
    """Return the provider-output Session scope."""

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        del session, agent_session_id
        return AgentSession.model_construct(
            id="session-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
        )


class _WorkspaceUserRepository(WorkspaceUserRepository):
    """Authorize the provider-output actor."""

    async def get_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser | None:
        del session
        return WorkspaceUser.model_construct(
            id="workspace-user-1",
            workspace_id=workspace_id,
            user_id=user_id,
        )


class _AgentRunRepository(AgentRunRepository):
    """Serialize provider-output admission on the synthetic run."""

    def __init__(self) -> None:
        self.lock_calls = 0

    async def lock_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        del session
        self.lock_calls += 1
        return AgentRunState.model_construct(
            id=run_id,
            session_id="session-1",
        )


class _ExchangeFileRepository(ExchangeFileRepository):
    """Record Exchange metadata admission."""

    def __init__(self) -> None:
        self.created: list[ExchangeFileCreate] = []
        self.preview_links: list[tuple[str, str]] = []

    async def create(
        self,
        session: AsyncSession,
        create: ExchangeFileCreate,
    ) -> ExchangeFile:
        del session
        self.created.append(create)
        return self._build_created(create)

    async def get_by_id(
        self,
        session: AsyncSession,
        file_id: str,
    ) -> ExchangeFile | None:
        del session
        for create in self.created:
            if create.id == file_id:
                return self._build_created(create)
        return None

    def _build_created(self, create: ExchangeFileCreate) -> ExchangeFile:
        preview_id = next(
            (
                preview_id
                for source_id, preview_id in self.preview_links
                if source_id == create.id
            ),
            None,
        )
        return ExchangeFile.model_construct(
            **create.model_dump(),
            status="available",
            object_key=f"exchange/workspace-1/files/{create.id}/original",
            preview_thumbnail_file_id=preview_id,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    async def set_preview_thumbnail_file_id(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        preview_thumbnail_file_id: str,
        preview_thumbnail_media_type: str,
        preview_thumbnail_width: int,
        preview_thumbnail_height: int,
        preview_generated_at: datetime.datetime,
    ) -> ExchangeFile:
        del (
            session,
            preview_thumbnail_media_type,
            preview_thumbnail_width,
            preview_thumbnail_height,
            preview_generated_at,
        )
        self.preview_links.append((file_id, preview_thumbnail_file_id))
        return ExchangeFile.model_construct(id=file_id)


class _ModelFileRepository(ModelFileRepository):
    """Record ModelFile metadata admission."""

    def __init__(self) -> None:
        self.created: list[ModelFileCreate] = []

    async def create(
        self,
        session: AsyncSession,
        create: ModelFileCreate,
    ) -> ModelFile:
        del session
        self.created.append(create)
        return self._build_created(create)

    async def get_by_id(
        self,
        session: AsyncSession,
        model_file_id: str,
    ) -> ModelFile | None:
        del session
        for create in self.created:
            if create.id == model_file_id:
                return self._build_created(create)
        return None

    @staticmethod
    def _build_created(create: ModelFileCreate) -> ModelFile:
        return ModelFile.model_construct(
            **create.model_dump(),
            status="available",
            storage_key=(
                f"model-files/{create.workspace_id}/{create.session_id}/{create.id}"
            ),
            created_at=datetime.datetime.now(datetime.UTC),
        )


class _S3Service(S3Service):
    """Record prepared object uploads and compensation deletes."""

    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}
        self.upload_calls: list[str] = []
        self.deleted: list[str] = []

    async def upload(
        self,
        bucket: str,
        key: str,
        body: str | bytes | IO[str] | IO[bytes],
        *,
        content_type: str | None = None,
    ) -> None:
        del bucket, content_type
        assert isinstance(body, bytes)
        self.upload_calls.append(key)
        self.uploaded[key] = body

    async def delete(self, bucket: str, key: str) -> None:
        del bucket
        self.deleted.append(key)


class _FailingS3Service(_S3Service):
    """Fail after the first provider object upload."""

    async def upload(
        self,
        bucket: str,
        key: str,
        body: str | bytes | IO[str] | IO[bytes],
        *,
        content_type: str | None = None,
    ) -> None:
        if self.uploaded:
            raise OSError("object storage unavailable")
        await super().upload(
            bucket,
            key,
            body,
            content_type=content_type,
        )


def _artifact() -> NativeArtifact:
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
        item={"type": "image_generation_call", "id": "image-call-1"},
    )


def _normalized_output(
    result: str = _PNG_BASE64,
) -> NormalizedAdapterOutput:
    pending = pending_image_generation_output(
        {
            "type": "image_generation_call",
            "id": "image-call-1",
            "result": result,
        },
        output_index=0,
    )
    event = Event(
        id="00000000000000000000000000000001",
        session_id="session-1",
        kind=EventKind.PROVIDER_TOOL_RESULT,
        payload=ProviderToolResultPayload(
            call_id="image-call-1",
            name="image_generation",
            status="completed",
            output=[],
            attachments=[],
            native_artifact=_artifact(),
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    return NormalizedAdapterOutput(
        needs_follow_up=False,
        events=[event],
        pending_provider_files=[pending],
    )


def _materializer(
    s3_service: _S3Service | None = None,
) -> tuple[
    ProviderOutputMaterializer,
    _ExchangeFileRepository,
    _ModelFileRepository,
    _S3Service,
]:
    exchange_repository = _ExchangeFileRepository()
    model_repository = _ModelFileRepository()
    session_repository = _AgentSessionRepository()
    workspace_user_repository = _WorkspaceUserRepository()
    s3_service = s3_service or _S3Service()
    session_manager = cast(
        SessionManager[AsyncSession],
        _SessionManager(),
    )
    config = Config.model_construct(
        workspace_s3=WorkspaceS3Config(bucket="test-bucket"),
        file_lifecycle=FileLifecycleConfig(),
    )
    exchange_service = ExchangeFileService(
        exchange_file_repository=exchange_repository,
        agent_repository=AgentRepository(),
        agent_session_repository=session_repository,
        workspace_user_repository=workspace_user_repository,
        session_manager=session_manager,
        s3_service=s3_service,
        config=config,
    )
    model_service = ModelFileService(
        model_file_repository=model_repository,
        agent_session_repository=session_repository,
        agent_run_repository=_AgentRunRepository(),
        workspace_user_repository=workspace_user_repository,
        session_manager=session_manager,
        s3_service=s3_service,
        config=config,
    )
    return (
        ProviderOutputMaterializer(
            exchange_file_service=exchange_service,
            model_file_service=model_service,
            workspace_id="workspace-1",
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            run_id="run-1",
            run_index=3,
        ),
        exchange_repository,
        model_repository,
        s3_service,
    )


def test_decodes_valid_data_url_and_excludes_bytes_from_serialization() -> None:
    """Keep validated image bytes transient and serialization-excluded."""
    pending = pending_image_generation_output(
        {
            "id": "image-call-1",
            "result": f"data:image/png;base64,{_PNG_BASE64}",
        },
        output_index=2,
    )

    assert pending.media_type == "image/png"
    assert pending.filename.endswith(".png")
    assert pending.body.startswith(b"\x89PNG")
    assert "body" not in pending.model_dump(mode="json")


@pytest.mark.parametrize(
    ("result", "message"),
    [
        ("%%%", "not valid Base64"),
        (base64.b64encode(b"not-an-image").decode(), "corrupt or unsupported"),
    ],
)
def test_rejects_invalid_provider_image_payload(result: str, message: str) -> None:
    """Reject malformed provider payloads before event admission."""
    with pytest.raises(ModelCallError, match=message):
        pending_image_generation_output(
            {"id": "image-call-1", "result": result},
            output_index=0,
        )


def test_rejects_mismatched_data_url_media_type() -> None:
    """Trust verified image bytes rather than a conflicting data URL header."""
    with pytest.raises(ModelCallError, match="invalid media type"):
        pending_image_generation_output(
            {
                "id": "image-call-1",
                "result": f"data:image/jpeg;base64,{_PNG_BASE64}",
            },
            output_index=0,
        )


def test_rejects_provider_image_above_encoded_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject encoded payloads before allocating decoded image bytes."""
    monkeypatch.setattr(provider_output, "_MAX_ENCODED_IMAGE_CHARS", 4)

    with pytest.raises(ModelCallError, match="exceeds the size limit"):
        pending_image_generation_output(
            {"id": "image-call-1", "result": _PNG_BASE64},
            output_index=0,
        )


def test_rejects_provider_image_above_pixel_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject oversized dimensions before normalization decodes pixels."""
    monkeypatch.setattr(provider_output, "_MAX_IMAGE_PIXELS", 0)

    with pytest.raises(ModelCallError, match="dimensions exceed the limit"):
        pending_image_generation_output(
            {"id": "image-call-1", "result": _PNG_BASE64},
            output_index=0,
        )


def test_maps_pillow_decompression_bomb_to_model_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose Pillow decompression-bomb rejection as a bounded model error."""

    def reject_image(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise Image.DecompressionBombError("synthetic oversized image")

    monkeypatch.setattr(provider_output.Image, "open", reject_image)

    with pytest.raises(ModelCallError, match="corrupt or unsupported"):
        pending_image_generation_output(
            {"id": "image-call-1", "result": _PNG_BASE64},
            output_index=0,
        )


async def test_materializes_exchange_and_model_file_in_one_admission() -> None:
    """Prepare uploads and persist both metadata resources with event references."""
    materializer, exchange_repository, model_repository, s3_service = _materializer()

    prepared = await materializer.prepare(_normalized_output())

    assert s3_service.uploaded == {}
    assert prepared.normalized.pending_provider_files == []
    payload = prepared.normalized.events[0].payload
    assert isinstance(payload, ProviderToolResultPayload)
    assert len(payload.output) == 1
    assert isinstance(payload.output[0], FileOutputPart)
    assert len(payload.attachments) == 1
    assert payload.attachments[0].availability == "available"
    assert payload.attachments[0].uri.startswith("exchange://")
    serialized = prepared.normalized.model_dump_json()
    assert _PNG_BASE64 not in serialized
    assert "generated-image:" not in serialized

    await prepared.persist(_Session())
    prepared.admitted = True
    await prepared.cleanup()

    assert len(s3_service.uploaded) == 3
    assert len(exchange_repository.created) == 2
    assert len(exchange_repository.preview_links) == 1
    assert len(model_repository.created) == 1
    assert s3_service.deleted == []


async def test_materializes_client_tool_image_with_shared_storage_contract() -> None:
    """Attach client-generated image resources in the result transaction."""
    materializer, exchange_repository, model_repository, s3_service = _materializer()
    generated = generated_image_output(_PNG_BASE64, output_index=0)
    result = ClientToolResultPayload(
        call_id="image-call-1",
        name="image_generation",
        status="completed",
        output=[],
        pending_generated_files=[
            pending_image_generation_output(
                {"id": "image-call-1", "result": _PNG_BASE64},
                output_index=0,
            )
        ],
    )

    prepared = await materializer.prepare_client_result(result)

    assert prepared.result.pending_generated_files == []
    assert len(prepared.result.output) == 1
    assert isinstance(prepared.result.output[0], FileOutputPart)
    assert len(prepared.result.attachments) == 1
    assert prepared.result.attachments[0].source == "client_tool"
    assert generated.sha256 in prepared.result.output[0].metadata["source_sha256"]
    serialized = prepared.result.model_dump_json()
    assert _PNG_BASE64 not in serialized

    await prepared.persist(_Session())
    prepared.admitted = True
    await prepared.cleanup()

    assert len(s3_service.uploaded) == 3
    assert len(exchange_repository.created) == 2
    assert len(model_repository.created) == 1
    assert model_repository.created[0].metadata["source_kind"] == "client_tool"
    assert s3_service.deleted == []


async def test_retry_reuses_metadata_and_preserves_admitted_objects() -> None:
    """Keep deterministic resources safe across repeated output admission."""
    materializer, exchange_repository, model_repository, s3_service = _materializer()
    first = await materializer.prepare(_normalized_output())
    await first.persist(_Session())
    first.admitted = True
    original_upload_calls = list(s3_service.upload_calls)

    rolled_back_retry = await materializer.prepare(_normalized_output())
    await rolled_back_retry.cleanup()
    assert s3_service.deleted == []

    admitted_retry = await materializer.prepare(_normalized_output())
    await admitted_retry.persist(_Session())
    admitted_retry.admitted = True

    assert s3_service.upload_calls == original_upload_calls
    assert len(exchange_repository.created) == 2
    assert len(exchange_repository.preview_links) == 1
    assert len(model_repository.created) == 1
    assert s3_service.deleted == []


async def test_retry_rejects_changed_bytes_before_overwriting_objects() -> None:
    """Keep admitted deterministic object keys bound to their original bytes."""
    materializer, _, _, s3_service = _materializer()
    first = await materializer.prepare(_normalized_output())
    await first.persist(_Session())
    first.admitted = True
    original_objects = dict(s3_service.uploaded)
    original_upload_calls = list(s3_service.upload_calls)

    retry = await materializer.prepare(
        _normalized_output(_png_base64(width=2, height=1))
    )
    with pytest.raises(ModelCallError, match="identity collided"):
        await retry.persist(_Session())

    assert s3_service.uploaded == original_objects
    assert s3_service.upload_calls == original_upload_calls


async def test_failed_admission_compensates_every_uploaded_object() -> None:
    """Delete uploaded objects after the metadata transaction rolls back."""
    materializer, exchange_repository, model_repository, s3_service = _materializer()
    run_repository = cast(
        _AgentRunRepository,
        materializer.model_file_service.agent_run_repository,
    )
    prepared = await materializer.prepare(_normalized_output())
    await prepared.persist(_Session())
    exchange_repository.created.clear()
    exchange_repository.preview_links.clear()
    model_repository.created.clear()

    await prepared.cleanup()

    assert run_repository.lock_calls == 2
    assert sorted(s3_service.deleted) == sorted(s3_service.uploaded)


async def test_failed_upload_compensates_prepared_object_keys() -> None:
    """Compensate the full deterministic key set after a partial upload."""
    s3_service = _FailingS3Service()
    materializer, _, _, _ = _materializer(s3_service)

    prepared = await materializer.prepare(_normalized_output())
    with pytest.raises(OSError, match="object storage unavailable"):
        await prepared.persist(_Session())
    await prepared.cleanup()

    assert len(s3_service.uploaded) == 1
    assert s3_service.deleted == list(s3_service.uploaded)


async def test_requires_authenticated_actor_before_upload() -> None:
    """Reject generated user-owned files when no authenticated actor exists."""
    materializer, _, _, s3_service = _materializer()
    materializer.user_id = None

    with pytest.raises(ModelCallError, match="authenticated user"):
        await materializer.prepare(_normalized_output())

    assert s3_service.uploaded == {}


async def test_rejects_duplicate_call_identity_before_upload() -> None:
    """Reject multiple generated files for one provider result event."""
    materializer, _, _, s3_service = _materializer()
    normalized = _normalized_output()
    duplicate = normalized.pending_provider_files[0].model_copy(
        update={"output_index": 1}
    )
    normalized = normalized.model_copy(
        update={
            "pending_provider_files": [
                normalized.pending_provider_files[0],
                duplicate,
            ]
        }
    )

    with pytest.raises(ModelCallError, match="identity collided"):
        await materializer.prepare(normalized)

    assert s3_service.uploaded == {}
