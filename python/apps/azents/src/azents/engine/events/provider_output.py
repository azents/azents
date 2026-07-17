"""Transient provider output decoding and dual file materialization."""

import base64
import binascii
import dataclasses
import datetime
import hashlib
import uuid
from io import BytesIO
from typing import Literal

from azcommon.result import Failure
from azcommon.types import JSONValue
from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExchangeFileOrigin
from azents.engine.events.protocols import (
    NormalizedAdapterOutput,
    PendingProviderFileOutput,
)
from azents.engine.events.types import (
    Attachment,
    Event,
    FileOutputPart,
    ProviderToolResultPayload,
)
from azents.engine.run.errors import ModelCallError
from azents.repos.exchange_file import exchange_file_object_key
from azents.repos.exchange_file.data import ExchangeFileCreate
from azents.repos.model_file import model_file_storage_key
from azents.repos.model_file.data import ModelFileCreate
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

_MAX_DECODED_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_ENCODED_IMAGE_CHARS = ((_MAX_DECODED_IMAGE_BYTES + 2) // 3) * 4
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
    attachment: Attachment
    file_part: FileOutputPart


@dataclasses.dataclass
class PreparedProviderOutput:
    """Uploaded provider output awaiting transactional metadata admission."""

    normalized: NormalizedAdapterOutput
    materializer: "ProviderOutputMaterializer"
    generated_images: tuple[_PreparedGeneratedImage, ...]
    admitted: bool = False

    async def persist(self, session: AsyncSession) -> None:
        """Persist file metadata in the caller's model-output transaction."""
        await self.materializer.persist(session, self.generated_images)

    async def cleanup(self) -> None:
        """Compensate uploaded objects unless metadata admission succeeded."""
        if self.admitted:
            return
        await self.materializer.cleanup(self.generated_images)


@dataclasses.dataclass
class ProviderOutputMaterializer:
    """Materialize transient provider images as Exchange and ModelFile resources."""

    exchange_file_service: ExchangeFileService
    model_file_service: ModelFileService
    workspace_id: str
    agent_id: str
    session_id: str
    user_id: str | None
    run_id: str
    run_index: int

    async def prepare(
        self,
        normalized: NormalizedAdapterOutput,
    ) -> PreparedProviderOutput:
        """Validate scope, prepare metadata, upload objects, and update events."""
        pending = normalized.pending_provider_files
        if not pending:
            return PreparedProviderOutput(
                normalized=normalized,
                materializer=self,
                generated_images=(),
            )
        await self._validate_scope()
        generated_images = tuple(
            self._prepare_generated_image(file) for file in pending
        )
        self._validate_unique_outputs(generated_images)
        prepared = PreparedProviderOutput(
            normalized=self._attach_resources(normalized, generated_images),
            materializer=self,
            generated_images=generated_images,
        )
        uploaded = False
        try:
            await self._upload(generated_images)
            uploaded = True
            return prepared
        finally:
            if not uploaded:
                await self.cleanup(generated_images)

    async def persist(
        self,
        session: AsyncSession,
        generated_images: tuple[_PreparedGeneratedImage, ...],
    ) -> None:
        """Revalidate ownership and persist all prepared metadata."""
        if not generated_images:
            return
        await self._validate_scope_in_session(session)
        for image in generated_images:
            await self.exchange_file_service.exchange_file_repository.create(
                session,
                image.exchange_source,
            )
            preview = image.exchange_preview
            if preview is not None:
                await self.exchange_file_service.exchange_file_repository.create(
                    session,
                    preview,
                )
                if (
                    image.preview_width is None
                    or image.preview_height is None
                    or image.preview_generated_at is None
                ):
                    raise ModelCallError(
                        "Generated image preview metadata is incomplete."
                    )
                repository = self.exchange_file_service.exchange_file_repository
                await repository.set_preview_thumbnail_file_id(
                    session,
                    file_id=image.exchange_source.id,
                    preview_thumbnail_file_id=preview.id,
                    preview_thumbnail_media_type=preview.media_type,
                    preview_thumbnail_width=image.preview_width,
                    preview_thumbnail_height=image.preview_height,
                    preview_generated_at=image.preview_generated_at,
                )
            await self.model_file_service.model_file_repository.create(
                session,
                image.model_file,
            )

    async def cleanup(
        self,
        generated_images: tuple[_PreparedGeneratedImage, ...],
    ) -> None:
        """Delete every prepared object key after failed admission."""
        keys = {
            upload.key
            for generated_image in generated_images
            for upload in generated_image.uploads
        }
        for key in sorted(keys):
            await self.model_file_service.s3_service.delete(
                bucket=self.model_file_service.config.workspace_s3.bucket,
                key=key,
            )

    async def _validate_scope(self) -> None:
        """Validate provider output ownership before object upload."""
        async with self.model_file_service.session_manager() as session:
            await self._validate_scope_in_session(session)

    async def _validate_scope_in_session(self, session: AsyncSession) -> None:
        """Validate Session, Agent, Workspace, and actor ownership."""
        agent_session = (
            await self.model_file_service.agent_session_repository.get_by_id(
                session,
                self.session_id,
            )
        )
        if (
            agent_session is None
            or agent_session.workspace_id != self.workspace_id
            or agent_session.agent_id != self.agent_id
        ):
            raise ModelCallError("Generated image output scope is unavailable.")
        user_id = self._required_user_id()
        repository = self.model_file_service.workspace_user_repository
        workspace_user = await repository.get_by_workspace_and_user(
            session,
            workspace_id=self.workspace_id,
            user_id=user_id,
        )
        if workspace_user is None:
            raise ModelCallError("Generated image output scope is unavailable.")

    def _required_user_id(self) -> str:
        """Return the actor required for user-owned file metadata."""
        if self.user_id is None:
            raise ModelCallError(
                "Generated image output requires an authenticated user."
            )
        return self.user_id

    def _prepare_generated_image(
        self,
        pending: PendingProviderFileOutput,
    ) -> _PreparedGeneratedImage:
        """Prepare dual resource metadata and bytes for one pending image."""
        user_id = self._required_user_id()
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
            created_by_user_id=user_id,
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
                created_by_user_id=user_id,
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
            "source_kind": "provider_tool",
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
            created_run_index=self.run_index,
            normalized_format=normalized.normalized_format,
            sha256=hashlib.sha256(normalized.body).hexdigest(),
            metadata=model_metadata,
        )
        attachment = Attachment(
            attachment_id=exchange_id,
            uri=f"exchange://{exchange_key}",
            name=filename,
            media_type=pending.media_type,
            size=len(pending.body),
            created_at=now,
            source="provider_tool",
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
            attachment=attachment,
            file_part=file_part,
        )

    def _attach_resources(
        self,
        normalized: NormalizedAdapterOutput,
        generated_images: tuple[_PreparedGeneratedImage, ...],
    ) -> NormalizedAdapterOutput:
        """Replace provider result skeletons with durable file references."""
        by_call_id = {image.call_id: image for image in generated_images}
        updated_events: list[Event] = []
        attached_call_ids: set[str] = set()
        for event in normalized.events:
            payload = event.payload
            if not (
                isinstance(payload, ProviderToolResultPayload)
                and payload.name == "image_generation"
                and payload.call_id in by_call_id
            ):
                updated_events.append(event)
                continue
            image = by_call_id[payload.call_id]
            updated_payload = payload.model_copy(
                update={
                    "output": [image.file_part],
                    "attachments": [image.attachment],
                }
            )
            updated_events.append(event.model_copy(update={"payload": updated_payload}))
            attached_call_ids.add(payload.call_id)
        if attached_call_ids != set(by_call_id):
            raise ModelCallError("Generated image result event is missing.")
        return normalized.model_copy(
            update={
                "events": updated_events,
                "pending_provider_files": [],
            }
        )

    async def _upload(
        self,
        generated_images: tuple[_PreparedGeneratedImage, ...],
    ) -> None:
        """Upload prepared Exchange, preview, and ModelFile objects."""
        for image in generated_images:
            for upload in image.uploads:
                await self.model_file_service.s3_service.upload(
                    bucket=self.model_file_service.config.workspace_s3.bucket,
                    key=upload.key,
                    body=upload.body,
                    content_type=upload.media_type,
                )

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
) -> PendingProviderFileOutput:
    """Decode and validate one provider image generation result."""
    call_id = output_item.get("call_id") or output_item.get("id")
    if not isinstance(call_id, str) or not call_id:
        raise ModelCallError("Generated image result is missing its call identity.")
    result = output_item.get("result")
    if not isinstance(result, str) or not result:
        raise ModelCallError("Generated image result is missing.")
    encoded, media_hint = _split_image_data_url(result)
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
    return PendingProviderFileOutput(
        call_id=call_id,
        tool_name="image_generation",
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
        with Image.open(BytesIO(body)) as image:
            image.verify()
            image_format = image.format
    except (OSError, UnidentifiedImageError, ValueError) as exc:
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
