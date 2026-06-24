"""ModelFile request-local materialization."""

import logging
from collections.abc import Sequence
from typing import Protocol

from azcommon.result import Failure, Result

from azents.core.enums import EventKind
from azents.engine.events.file_parts import (
    ModelFileLoweringContent,
    RequestLocalModelFileResolver,
    make_model_file_data_url,
)
from azents.engine.events.output_parts import iter_output_parts
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolResultPayload,
    Event,
    FileOutputPart,
    ProviderToolResultPayload,
    UserMessagePayload,
)
from azents.services.model_file import (
    ModelFileAccessDenied,
    ModelFileDownload,
    ModelFileNotFound,
    ModelFileResolveError,
    ModelFileUnavailable,
)

logger = logging.getLogger(__name__)


class ModelFileDownloader(Protocol):
    """ModelFile blob download dependency."""

    async def download_for_agent(
        self,
        *,
        model_file_id: str,
        agent_id: str,
        user_id: str,
    ) -> Result[ModelFileDownload, ModelFileResolveError]:
        """Fetch ModelFile normalized blob within current Agent namespace."""
        ...


class ModelFileMaterializer:
    """Materialize FileParts in transcript into request-local resolver."""

    def __init__(
        self,
        *,
        model_file_service: ModelFileDownloader,
        resolver: RequestLocalModelFileResolver,
        user_id: str | None,
        agent_id: str,
    ) -> None:
        """Store ModelFileService and resolver."""
        self._model_file_service = model_file_service
        self._resolver = resolver
        self._user_id = user_id
        self._agent_id = agent_id

    async def materialize(
        self,
        *,
        transcript: Sequence[Event],
    ) -> None:
        """Make Transcript FilePart blobs available only within current request."""
        self._resolver.clear()
        if self._user_id is None:
            return
        for model_file_id in _model_file_ids(transcript):
            resolved = await self._model_file_service.download_for_agent(
                model_file_id=model_file_id,
                agent_id=self._agent_id,
                user_id=self._user_id,
            )
            if isinstance(resolved, Failure):
                _log_unavailable_model_file(model_file_id, resolved.error)
                continue
            download = resolved.value
            self._resolver.put(
                model_file_id=model_file_id,
                content=ModelFileLoweringContent(
                    data_url=make_model_file_data_url(
                        media_type=download.model_file.media_type,
                        body=download.body,
                    ),
                ),
            )


def _model_file_ids(transcript: Sequence[Event]) -> list[str]:
    """Return ModelFile IDs with order-preserving deduplication."""
    seen: set[str] = set()
    ordered: list[str] = []
    for event in transcript:
        for part in _file_parts(event):
            if part.model_file_id in seen:
                continue
            seen.add(part.model_file_id)
            ordered.append(part.model_file_id)
    return ordered


def _file_parts(event: Event) -> list[FileOutputPart]:
    """Extract FileOutputPart from one Event."""
    payload = event.payload
    if event.kind == EventKind.USER_MESSAGE and isinstance(payload, UserMessagePayload):
        if isinstance(payload.content, str):
            return []
        return [part for part in payload.content if isinstance(part, FileOutputPart)]
    if event.kind == EventKind.ASSISTANT_MESSAGE and isinstance(
        payload, AssistantMessagePayload
    ):
        if isinstance(payload.content, str):
            return []
        return [part for part in payload.content if isinstance(part, FileOutputPart)]
    if isinstance(payload, ClientToolResultPayload | ProviderToolResultPayload):
        return [
            part
            for part in iter_output_parts(payload.output)
            if isinstance(part, FileOutputPart)
        ]
    return []


def _log_unavailable_model_file(
    model_file_id: str,
    error: ModelFileNotFound | ModelFileAccessDenied | ModelFileUnavailable,
) -> None:
    """Log ModelFile that cannot be materialized for diagnostics."""
    logger.info(
        "ModelFile is unavailable for request-local materialization",
        extra={
            "model_file_id": model_file_id,
            "error": error.__class__.__name__,
        },
    )
