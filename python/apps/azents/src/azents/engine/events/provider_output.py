"""Transient provider output decoding and dual file materialization."""

import base64
import binascii
import dataclasses
import datetime
import hashlib
import uuid
import warnings
from io import BytesIO
from typing import Literal

from azcommon.result import Failure
from azcommon.types import JSONValue
from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExchangeFileOrigin, ExchangeFileProvenanceKind
from azents.engine.events.generated_files import (
    GeneratedFileOutput,
    PendingGeneratedFileOutput,
)
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.events.types import (
    AttachmentOutputPart,
    ClientToolResultPayload,
    Event,
    FileOutputPart,
    ProviderToolCallPayload,
)
from azents.engine.run.errors import ModelCallError
from azents.repos.exchange_file import exchange_file_object_key
from azents.repos.exchange_file.data import ExchangeFile, ExchangeFileCreate
from azents.repos.model_file import model_file_storage_key
from azents.repos.model_file.data import ModelFile, ModelFileCreate
from azents.services.exchange_file import (
    ExchangeFileService,
    make_exchange_preview_thumbnail,
    sanitize_exchange_filename,
)
from azents.services.file_lifecycle_policy import exchange_file_expires_at
from azents.services.model_file import (
    ModelFileService,
    normalize_model_file_body,
)
from azents.services.session_resource_authority import SessionResourceAuthority

_MAX_DECODED_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_ENCODED_IMAGE_CHARS = ((_MAX_DECODED_IMAGE_BYTES + 2) // 3) * 4
_MAX_IMAGE_DIMENSION = 8192
_MAX_IMAGE_PIXELS = 4096 * 4096
_IMAGE_MEDIA_TYPES: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
    "GIF": ("image/gif", "gif"),
}
_PROVIDER_OUTPUT_NAMESPACE = uuid.UUID("67ca5840-937d-51cb-bff0-ff385172230c")


@dataclasses.dataclass(frozen=True)
class _ObjectUpload:
    """One prepared object-storage upload."""

    key: str
    body: bytes
    media_type: str


@dataclasses.dataclass(frozen=True)
class _PreparedGeneratedImage:
    """Metadata and objects prepared for one generated image."""

    call_id: str
    output_index: int
    exchange_source: ExchangeFileCreate
    exchange_preview: ExchangeFileCreate | None
    preview_width: int | None
    preview_height: int | None
    preview_generated_at: datetime.datetime | None
    model_file: ModelFileCreate
    uploads: tuple[_ObjectUpload, ...]
    attachment_part: AttachmentOutputPart
    file_part: FileOutputPart


@dataclasses.dataclass
class PreparedProviderOutput:
    """Prepared provider output awaiting transactional upload and admission."""

    normalized: NormalizedAdapterOutput
    materializer: "ProviderOutputMaterializer"
    generated_images: tuple[_PreparedGeneratedImage, ...]
    uploaded_keys: set[str] = dataclasses.field(default_factory=set)
    admitted: bool = False

    async def persist(self, session: AsyncSession) -> None:
        """Persist file metadata in the caller's model-output transaction."""
        await self.materializer.persist(
            session,
            self.generated_images,
            uploaded_keys=self.uploaded_keys,
        )

    async def cleanup(self) -> None:
        """Compensate uploaded objects unless metadata admission succeeded."""
        if self.admitted or not self.uploaded_keys:
            return
        await self.materializer.cleanup(
            self.generated_images,
            uploaded_keys=self.uploaded_keys,
        )
        self.uploaded_keys.clear()


@dataclasses.dataclass
class PreparedClientToolOutput:
    """Prepared client tool output awaiting transactional admission."""

    result: ClientToolResultPayload
    materializer: "ProviderOutputMaterializer"
    generated_images: tuple[_PreparedGeneratedImage, ...]
    uploaded_keys: set[str] = dataclasses.field(default_factory=set)
    admitted: bool = False

    async def persist(self, session: AsyncSession) -> None:
        """Persist file metadata in the caller's tool-result transaction."""
        await self.materializer.persist(
            session,
            self.generated_images,
            uploaded_keys=self.uploaded_keys,
        )

    async def cleanup(self) -> None:
        """Compensate uploaded objects unless result admission succeeded."""
        if self.admitted or not self.uploaded_keys:
            return
        await self.materializer.cleanup(
            self.generated_images,
            uploaded_keys=self.uploaded_keys,
        )
        self.uploaded_keys.clear()


@dataclasses.dataclass
class ProviderOutputMaterializer:
    """Materialize transient provider images as Exchange and ModelFile resources."""

    exchange_file_service: ExchangeFileService
    model_file_service: ModelFileService
    authority: SessionResourceAuthority

    @property
    def workspace_id(self) -> str:
        """Return the authorized Workspace identity."""
        return self.authority.workspace_id

    @property
    def agent_id(self) -> str:
        """Return the authorized Agent identity."""
        return self.authority.agent_id

    @property
    def session_id(self) -> str:
        """Return the authorized Session identity."""
        return self.authority.session_id

    @property
    def run_id(self) -> str:
        """Return the authorized Run identity."""
        return self.authority.run_id

    @property
    def run_index(self) -> int:
        """Return the authorized Run index."""
        return self.authority.run_index

    async def prepare(
        self,
        normalized: NormalizedAdapterOutput,
    ) -> PreparedProviderOutput:
        """Validate scope, prepare metadata and bytes, and update events."""
        pending = normalized.pending_provider_files
        if not pending:
            return PreparedProviderOutput(
                normalized=normalized,
                materializer=self,
                generated_images=(),
            )
        retention_root_session_id = await self._validate_scope()
        generated_images = tuple(
            self._prepare_generated_image(
                file,
                source_kind="provider_tool",
                retention_root_session_id=retention_root_session_id,
            )
            for file in pending
        )
        self._validate_unique_outputs(generated_images)
        return PreparedProviderOutput(
            normalized=self._attach_resources(normalized, generated_images),
            materializer=self,
            generated_images=generated_images,
        )

    async def prepare_client_result(
        self,
        result: ClientToolResultPayload,
    ) -> PreparedClientToolOutput:
        """Prepare transient client-generated images for result admission."""
        pending = result.pending_generated_files
        if not pending:
            return PreparedClientToolOutput(
                result=result,
                materializer=self,
                generated_images=(),
            )
        retention_root_session_id = await self._validate_scope()
        if any(file.call_id != result.call_id for file in pending):
            raise ModelCallError("Generated image result identity is invalid.")
        generated_images = tuple(
            self._prepare_generated_image(
                file,
                source_kind="client_tool",
                retention_root_session_id=retention_root_session_id,
            )
            for file in pending
        )
        self._validate_unique_outputs(generated_images)
        return PreparedClientToolOutput(
            result=self._attach_client_resources(result, generated_images),
            materializer=self,
            generated_images=generated_images,
        )

    async def persist(
        self,
        session: AsyncSession,
        generated_images: tuple[_PreparedGeneratedImage, ...],
        *,
        uploaded_keys: set[str],
    ) -> None:
        """Serialize admission, upload new objects, and persist file metadata."""
        if not generated_images:
            return
        retention_root_session_id = await self._validate_scope_in_session(
            session,
            lock=True,
        )
        if any(
            image.exchange_source.retention_root_session_id != retention_root_session_id
            for image in generated_images
        ):
            raise ModelCallError("Generated image output scope changed.")
        existing_keys = await self._validated_persisted_object_keys_in_session(
            session,
            generated_images,
        )
        await self._upload(
            generated_images,
            skip_keys=existing_keys,
            uploaded_keys=uploaded_keys,
        )
        exchange_repository = self.exchange_file_service.exchange_file_repository
        model_repository = self.model_file_service.model_file_repository
        for image in generated_images:
            source = await exchange_repository.get_by_id(
                session,
                image.exchange_source.id,
            )
            if source is None:
                source = await exchange_repository.create(
                    session,
                    image.exchange_source,
                )
            self._validate_existing_exchange_file(source, image.exchange_source)

            preview = image.exchange_preview
            if preview is not None:
                existing_preview = await exchange_repository.get_by_id(
                    session,
                    preview.id,
                )
                if existing_preview is None:
                    existing_preview = await exchange_repository.create(
                        session,
                        preview,
                    )
                self._validate_existing_exchange_file(existing_preview, preview)
                if (
                    image.preview_width is None
                    or image.preview_height is None
                    or image.preview_generated_at is None
                ):
                    raise ModelCallError(
                        "Generated image preview metadata is incomplete."
                    )
                if source.preview_thumbnail_file_id not in {None, preview.id}:
                    raise ModelCallError("Generated image output identity collided.")
                if source.preview_thumbnail_file_id is None:
                    await exchange_repository.set_preview_thumbnail_file_id(
                        session,
                        file_id=image.exchange_source.id,
                        preview_thumbnail_file_id=preview.id,
                        preview_thumbnail_media_type=preview.media_type,
                        preview_thumbnail_width=image.preview_width,
                        preview_thumbnail_height=image.preview_height,
                        preview_generated_at=image.preview_generated_at,
                    )

            model_file = await model_repository.get_by_id(
                session,
                image.model_file.id,
            )
            if model_file is None:
                model_file = await model_repository.create(
                    session,
                    image.model_file,
                )
            self._validate_existing_model_file(model_file, image.model_file)

    async def cleanup(
        self,
        generated_images: tuple[_PreparedGeneratedImage, ...],
        *,
        uploaded_keys: set[str],
    ) -> None:
        """Serialize compensation and preserve any newly committed retry output."""
        async with self.model_file_service.session_manager() as session:
            run = await self.model_file_service.agent_run_repository.lock_by_id(
                session,
                self.run_id,
            )
            protected_keys = (
                await self._validated_persisted_object_keys_in_session(
                    session,
                    generated_images,
                )
                if run is not None and run.session_id == self.session_id
                else set()
            )
            for key in sorted(uploaded_keys - protected_keys):
                await self.model_file_service.s3_service.delete(
                    bucket=self.model_file_service.config.workspace_s3.bucket,
                    key=key,
                )

    async def _validated_persisted_object_keys_in_session(
        self,
        session: AsyncSession,
        generated_images: tuple[_PreparedGeneratedImage, ...],
    ) -> set[str]:
        """Validate identities visible inside the current admission transaction."""
        protected: set[str] = set()
        exchange_repository = self.exchange_file_service.exchange_file_repository
        model_repository = self.model_file_service.model_file_repository
        for image in generated_images:
            source = await exchange_repository.get_by_id(
                session,
                image.exchange_source.id,
            )
            if source is not None:
                self._validate_existing_exchange_file(
                    source,
                    image.exchange_source,
                )
                protected.add(source.object_key)
            preview = image.exchange_preview
            if preview is not None:
                if source is not None and source.preview_thumbnail_file_id not in {
                    None,
                    preview.id,
                }:
                    raise ModelCallError("Generated image output identity collided.")
                existing_preview = await exchange_repository.get_by_id(
                    session,
                    preview.id,
                )
                if existing_preview is not None:
                    self._validate_existing_exchange_file(
                        existing_preview,
                        preview,
                    )
                    protected.add(existing_preview.object_key)
            model_file = await model_repository.get_by_id(
                session,
                image.model_file.id,
            )
            if model_file is not None:
                self._validate_existing_model_file(
                    model_file,
                    image.model_file,
                )
                protected.add(model_file.storage_key)
        return protected

    @staticmethod
    def _validate_existing_exchange_file(
        existing: ExchangeFile,
        expected: ExchangeFileCreate,
    ) -> None:
        """Reject deterministic Exchange identities bound to different bytes."""
        if (
            existing.id != expected.id
            or existing.workspace_id != expected.workspace_id
            or existing.agent_id != expected.agent_id
            or existing.filename != expected.filename
            or existing.media_type != expected.media_type
            or existing.size_bytes != expected.size_bytes
            or existing.sha256 != expected.sha256
            or existing.provenance_kind != expected.provenance_kind
            or existing.source_user_id != expected.source_user_id
            or existing.source_agent_id != expected.source_agent_id
            or existing.source_run_id != expected.source_run_id
            or existing.source_tool_name != expected.source_tool_name
            or existing.source_provider != expected.source_provider
            or existing.source_exchange_file_id != expected.source_exchange_file_id
            or existing.retention_root_session_id != expected.retention_root_session_id
        ):
            raise ModelCallError("Generated image output identity collided.")

    @staticmethod
    def _validate_existing_model_file(
        existing: ModelFile,
        expected: ModelFileCreate,
    ) -> None:
        """Reject deterministic ModelFile identities bound to different bytes."""
        if (
            existing.id != expected.id
            or existing.workspace_id != expected.workspace_id
            or existing.session_id != expected.session_id
            or existing.agent_id != expected.agent_id
            or existing.name != expected.name
            or existing.media_type != expected.media_type
            or existing.kind != expected.kind
            or existing.size_bytes != expected.size_bytes
            or existing.sha256 != expected.sha256
            or existing.created_run_id != expected.created_run_id
            or existing.created_run_index != expected.created_run_index
            or existing.normalized_format != expected.normalized_format
        ):
            raise ModelCallError("Generated image output identity collided.")

    async def _validate_scope(self) -> str:
        """Validate provider output ownership and return its retention root."""
        async with self.model_file_service.session_manager() as session:
            return await self._validate_scope_in_session(session)

    async def _validate_scope_in_session(
        self,
        session: AsyncSession,
        *,
        lock: bool = False,
    ) -> str:
        """Validate scope and return the root AgentSession retention owner."""
        if not await self.model_file_service.validate_resource_authority_in_session(
            session,
            self.authority,
            lock=lock,
        ):
            raise ModelCallError("Generated image output scope is unavailable.")
        return self.authority.root_session_id

    def _prepare_generated_image(
        self,
        pending: PendingGeneratedFileOutput,
        *,
        source_kind: Literal["provider_tool", "client_tool"],
        retention_root_session_id: str,
    ) -> _PreparedGeneratedImage:
        """Prepare dual resource metadata and bytes for one pending image."""
        normalized_result = normalize_model_file_body(
            media_type=pending.media_type,
            body=pending.body,
        )
        if isinstance(normalized_result, Failure):
            raise ModelCallError("Generated image could not be normalized.")
        normalized = normalized_result.value
        now = datetime.datetime.now(datetime.UTC)
        expires_at = exchange_file_expires_at(
            now=now,
            config=self.exchange_file_service.config,
        )
        identity = f"{self.run_id}:{pending.call_id}:{pending.output_index}"
        exchange_id = _deterministic_id(identity, "exchange")
        preview_id = _deterministic_id(identity, "preview")
        model_file_id = _deterministic_id(identity, "model-file")
        filename = sanitize_exchange_filename(pending.filename)
        exchange_key = exchange_file_object_key(
            workspace_id=self.workspace_id,
            file_id=exchange_id,
        )
        exchange_source = ExchangeFileCreate(
            id=exchange_id,
            workspace_id=self.workspace_id,
            agent_id=self.agent_id,
            origin_type=ExchangeFileOrigin.ARTIFACT,
            filename=filename,
            media_type=pending.media_type,
            size_bytes=len(pending.body),
            sha256=pending.sha256,
            provenance_kind=ExchangeFileProvenanceKind.PROVIDER,
            source_user_id=None,
            source_agent_id=self.agent_id,
            source_run_id=self.run_id,
            source_tool_name=None,
            source_provider=source_kind,
            source_exchange_file_id=None,
            retention_root_session_id=retention_root_session_id,
            retention_bound_at=now,
            expires_at=expires_at,
            preview_title=filename,
            preview_generated_at=now,
        )
        uploads = [
            _ObjectUpload(
                key=exchange_key,
                body=pending.body,
                media_type=pending.media_type,
            )
        ]
        preview_body = make_exchange_preview_thumbnail(pending.body, pending.media_type)
        exchange_preview: ExchangeFileCreate | None = None
        preview_width: int | None = None
        preview_height: int | None = None
        preview_generated_at: datetime.datetime | None = None
        preview_uri: str | None = None
        preview_media_type: str | None = None
        if preview_body is not None:
            preview_media_type = "image/jpeg"
            preview_key = exchange_file_object_key(
                workspace_id=self.workspace_id,
                file_id=preview_id,
            )
            exchange_preview = ExchangeFileCreate(
                id=preview_id,
                workspace_id=self.workspace_id,
                agent_id=self.agent_id,
                origin_type=ExchangeFileOrigin.ARTIFACT,
                filename=f"{filename}.preview.jpg",
                media_type=preview_media_type,
                size_bytes=len(preview_body.body),
                sha256=hashlib.sha256(preview_body.body).hexdigest(),
                provenance_kind=ExchangeFileProvenanceKind.PREVIEW,
                source_user_id=None,
                source_agent_id=None,
                source_run_id=None,
                source_tool_name=None,
                source_provider=None,
                source_exchange_file_id=exchange_id,
                retention_root_session_id=retention_root_session_id,
                retention_bound_at=now,
                expires_at=expires_at,
                preview_title=f"{filename} preview",
                preview_generated_at=preview_body.generated_at,
            )
            preview_width = preview_body.width
            preview_height = preview_body.height
            preview_generated_at = preview_body.generated_at
            preview_uri = f"exchange://{preview_key}"
            uploads.append(
                _ObjectUpload(
                    key=preview_key,
                    body=preview_body.body,
                    media_type=preview_media_type,
                )
            )
        model_key = model_file_storage_key(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            model_file_id=model_file_id,
        )
        uploads.append(
            _ObjectUpload(
                key=model_key,
                body=normalized.body,
                media_type=normalized.media_type,
            )
        )
        file_metadata = {
            "source_kind": source_kind,
            "source_tool_name": pending.tool_name,
            "source_call_id": pending.call_id,
            "source_media_type": pending.media_type,
            "source_sha256": pending.sha256,
        }
        model_metadata: dict[str, JSONValue] = dict(file_metadata)
        model_file = ModelFileCreate(
            id=model_file_id,
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            agent_id=self.agent_id,
            name=filename,
            media_type=normalized.media_type,
            kind=normalized.kind,
            size_bytes=len(normalized.body),
            created_run_id=self.run_id,
            created_run_index=self.run_index,
            normalized_format=normalized.normalized_format,
            sha256=hashlib.sha256(normalized.body).hexdigest(),
            metadata=model_metadata,
        )
        attachment_part = AttachmentOutputPart(
            attachment_id=exchange_id,
            uri=f"exchange://{exchange_key}",
            name=filename,
            media_type=pending.media_type,
            size=len(pending.body),
            preview_title=filename,
            preview_thumbnail_uri=preview_uri,
            preview_thumbnail_media_type=preview_media_type,
            preview_thumbnail_width=preview_width,
            preview_thumbnail_height=preview_height,
            preview_generated_at=preview_generated_at,
        )
        file_part = FileOutputPart(
            model_file_id=model_file_id,
            media_type=normalized.media_type,
            name=filename,
            size=len(normalized.body),
            kind="image",
            metadata=file_metadata,
        )
        return _PreparedGeneratedImage(
            call_id=pending.call_id,
            output_index=pending.output_index,
            exchange_source=exchange_source,
            exchange_preview=exchange_preview,
            preview_width=preview_width,
            preview_height=preview_height,
            preview_generated_at=preview_generated_at,
            model_file=model_file,
            uploads=tuple(uploads),
            attachment_part=attachment_part,
            file_part=file_part,
        )

    def _attach_resources(
        self,
        normalized: NormalizedAdapterOutput,
        generated_images: tuple[_PreparedGeneratedImage, ...],
    ) -> NormalizedAdapterOutput:
        """Replace provider image skeletons with durable output parts."""
        by_call_id = {image.call_id: image for image in generated_images}
        updated_events: list[Event] = []
        attached_call_ids: set[str] = set()
        for event in normalized.events:
            payload = event.payload
            if not (
                isinstance(payload, ProviderToolCallPayload)
                and payload.name == "image_generation"
                and payload.call_id in by_call_id
            ):
                updated_events.append(event)
                continue
            image = by_call_id[payload.call_id]
            updated_payload = payload.model_copy(
                update={
                    "semantic": payload.semantic.model_copy(
                        update={"output": [image.file_part, image.attachment_part]}
                    ),
                }
            )
            updated_events.append(event.model_copy(update={"payload": updated_payload}))
            attached_call_ids.add(payload.call_id)
        if attached_call_ids != set(by_call_id):
            raise ModelCallError("Generated image provider event is missing.")
        return normalized.model_copy(
            update={
                "events": updated_events,
                "pending_provider_files": [],
            }
        )

    @staticmethod
    def _attach_client_resources(
        result: ClientToolResultPayload,
        generated_images: tuple[_PreparedGeneratedImage, ...],
    ) -> ClientToolResultPayload:
        """Replace a client result skeleton with durable output parts."""
        if len(generated_images) != 1:
            raise ModelCallError("Generated image result count is invalid.")
        image = generated_images[0]
        if image.call_id != result.call_id:
            raise ModelCallError("Generated image result identity is invalid.")
        return result.model_copy(
            update={
                "output": [image.file_part, image.attachment_part],
                "pending_generated_files": [],
            }
        )

    async def _upload(
        self,
        generated_images: tuple[_PreparedGeneratedImage, ...],
        *,
        skip_keys: set[str],
        uploaded_keys: set[str],
    ) -> None:
        """Upload objects that are not already bound to committed metadata."""
        for image in generated_images:
            for upload in image.uploads:
                if upload.key in skip_keys:
                    continue
                await self.model_file_service.s3_service.upload(
                    bucket=self.model_file_service.config.workspace_s3.bucket,
                    key=upload.key,
                    body=upload.body,
                    content_type=upload.media_type,
                )
                uploaded_keys.add(upload.key)

    @staticmethod
    def _validate_unique_outputs(
        generated_images: tuple[_PreparedGeneratedImage, ...],
    ) -> None:
        """Reject colliding call identities inside one response."""
        call_ids = [image.call_id for image in generated_images]
        if len(call_ids) != len(set(call_ids)):
            raise ModelCallError("Generated image output identity collided.")


def pending_image_generation_output(
    output_item: dict[str, object],
    *,
    output_index: int,
) -> PendingGeneratedFileOutput:
    """Decode and validate one provider image generation result."""
    call_id = output_item.get("call_id") or output_item.get("id")
    if not isinstance(call_id, str) or not call_id:
        raise ModelCallError("Generated image result is missing its call identity.")
    result = output_item.get("result")
    if not isinstance(result, str) or not result:
        raise ModelCallError("Generated image result is missing.")
    generated = generated_image_output(result, output_index=output_index)
    return PendingGeneratedFileOutput(
        call_id=call_id,
        tool_name="image_generation",
        output_index=generated.output_index,
        filename=generated.filename,
        media_type=generated.media_type,
        sha256=generated.sha256,
        body=generated.body,
    )


def generated_image_output(
    encoded_result: str,
    *,
    output_index: int,
) -> GeneratedFileOutput:
    """Decode and validate one client or provider generated image."""
    encoded, media_hint = _split_image_data_url(encoded_result)
    if len(encoded) > _MAX_ENCODED_IMAGE_CHARS:
        raise ModelCallError("Generated image result exceeds the size limit.")
    try:
        body = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ModelCallError("Generated image result is not valid Base64.") from exc
    if len(body) > _MAX_DECODED_IMAGE_BYTES:
        raise ModelCallError("Generated image result exceeds the size limit.")
    media_type, extension = _detect_image_media_type(body)
    if media_hint is not None and media_hint != media_type:
        raise ModelCallError("Generated image result has an invalid media type.")
    sha256 = hashlib.sha256(body).hexdigest()
    return GeneratedFileOutput(
        output_index=output_index,
        filename=f"generated-image-{sha256[:12]}.{extension}",
        media_type=media_type,
        sha256=sha256,
        body=body,
    )


def _split_image_data_url(value: str) -> tuple[str, str | None]:
    prefix = "data:"
    marker = ";base64,"
    if not value.startswith(prefix):
        return value, None
    header, separator, encoded = value.partition(marker)
    if not separator or not encoded:
        raise ModelCallError("Generated image data URL is invalid.")
    return encoded, header.removeprefix(prefix)


def _detect_image_media_type(body: bytes) -> tuple[str, str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(body)) as image:
                width, height = image.size
                if (
                    width > _MAX_IMAGE_DIMENSION
                    or height > _MAX_IMAGE_DIMENSION
                    or width * height > _MAX_IMAGE_PIXELS
                ):
                    raise ModelCallError("Generated image dimensions exceed the limit.")
                image.verify()
                image_format = image.format
    except ModelCallError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        raise ModelCallError(
            "Generated image result is corrupt or unsupported."
        ) from exc
    detected = _IMAGE_MEDIA_TYPES.get(image_format or "")
    if detected is None:
        raise ModelCallError("Generated image result is corrupt or unsupported.")
    return detected


def _deterministic_id(
    identity: str,
    resource: Literal["exchange", "preview", "model-file"],
) -> str:
    return uuid.uuid5(_PROVIDER_OUTPUT_NAMESPACE, f"{identity}:{resource}").hex
