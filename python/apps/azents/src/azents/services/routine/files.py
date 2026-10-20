"""Prepare Routine notification files with existing publication authority."""

import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import Depends

from azents.core.external_channel_file import ExternalChannelOutboundFileManifest
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.engine.events.types import Attachment
from azents.engine.tools.runtime_instruction_context import RuntimeInstructionContext
from azents.runtime.transfer.present_file_publication import (
    PresentFilePublicationRequest,
)
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileTransferService,
)
from azents.services.session_storage import guess_media_type


@dataclass(frozen=True)
class RoutineNotificationFiles:
    """Validated files bound to the destination observed before completion."""

    binding_id: str | None
    manifests: tuple[ExternalChannelOutboundFileManifest, ...]
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True)
class RoutineFileService:
    """Reuse Runtime/Exchange validation without provider I/O in transactions."""

    transfers: Annotated[ExternalChannelFileTransferService, Depends()]

    async def prepare(
        self,
        *,
        paths: list[str],
        binding_id: str | None,
        execution_id: str,
        authority: SessionResourceAuthority,
        runtime: RuntimeInstructionContext | None,
    ) -> RoutineNotificationFiles:
        """Validate all requested sources before canonical completion."""
        if binding_id is not None:
            manifests = await self.transfers.prepare_outbound(
                session_id=authority.session_id,
                agent_id=authority.agent_id,
                binding_id=binding_id,
                paths=paths,
                file_storage=None if runtime is None else runtime.file_storage,
                authority=authority,
            )
            return RoutineNotificationFiles(
                binding_id=binding_id, manifests=manifests, attachments=()
            )
        attachments: list[Attachment] = []
        for path in paths:
            if path.startswith("exchange://"):
                exchange = self.transfers.exchange_file_service
                resolved = await exchange.resolve_transfer_source_for_authority(
                    uri=path, authority=authority
                )
                if resolved.failure:
                    raise ValueError(
                        "Routine attachment is unavailable or access is denied."
                    )
                file = resolved.value.file
            else:
                if "://" in path or not PurePosixPath(path).is_absolute():
                    raise ValueError(
                        "Routine files require absolute Runtime paths "
                        "or exchange:// URIs."
                    )
                if runtime is None:
                    raise ValueError(
                        "Routine Runtime files require Runtime file storage."
                    )
                try:
                    metadata = await runtime.file_storage.stat(
                        path, agent_id=authority.agent_id
                    )
                except FileNotFoundError:
                    raise ValueError("Routine attachment file was not found.") from None
                size = metadata.get("size")
                if (
                    metadata.get("is_file") is not True
                    or isinstance(size, bool)
                    or not isinstance(size, int)
                    or size <= 0
                ):
                    raise ValueError(
                        "Routine attachment must be a nonempty regular file."
                    )
                target = await runtime.resolve_runtime_target()
                file = await runtime.publication_service.publish(
                    PresentFilePublicationRequest(
                        runtime_path=path,
                        filename=PurePosixPath(path).name,
                        media_type=guess_media_type(path),
                        expected_size=size,
                        authority=authority,
                        target=target,
                        publication_id=uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"routine:{execution_id}:{uuid.uuid4().hex}:{path}",
                        ).hex,
                    )
                )
            attachments.append(
                Attachment(
                    attachment_id=file.id,
                    uri=file.uri,
                    name=file.filename,
                    media_type=file.media_type,
                    size=file.size_bytes,
                    created_at=file.created_at,
                    source="record_routine_result",
                )
            )
        return RoutineNotificationFiles(
            binding_id=None, manifests=(), attachments=tuple(attachments)
        )
