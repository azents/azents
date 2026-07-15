"""ModelFile request-local materialization."""

import logging
from collections.abc import Sequence
from typing import Protocol

from azcommon.result import Failure, Result

from azents.engine.events.file_parts import (
    ModelFileLoweringContent,
    RequestLocalModelFileResolver,
    make_model_file_data_url,
)
from azents.engine.events.model_file_refs import unique_model_file_ids
from azents.engine.events.types import Event
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
        self.model_file_service = model_file_service
        self.resolver = resolver
        self._user_id = user_id
        self._agent_id = agent_id

    async def materialize(
        self,
        *,
        transcript: Sequence[Event],
    ) -> None:
        """Make Transcript FilePart blobs available only within current request."""
        self.resolver.clear()
        if self._user_id is None:
            return
        for model_file_id in unique_model_file_ids(transcript):
            resolved = await self.model_file_service.download_for_agent(
                model_file_id=model_file_id,
                agent_id=self._agent_id,
                user_id=self._user_id,
            )
            if isinstance(resolved, Failure):
                _log_unavailable_model_file(model_file_id, resolved.error)
                continue
            download = resolved.value
            self.resolver.put(
                model_file_id=model_file_id,
                content=ModelFileLoweringContent(
                    data_url=make_model_file_data_url(
                        media_type=download.model_file.media_type,
                        body=download.body,
                    ),
                ),
            )


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
