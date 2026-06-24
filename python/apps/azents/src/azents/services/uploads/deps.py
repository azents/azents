"""UploadService dependency injection."""

from typing import Annotated

from azcommon.infra.s3.service import S3Service
from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.s3.deps import get_s3_service
from azents.services.uploads import UploadHandler, UploadService
from azents.services.uploads.handlers.avatar import AvatarUploadHandler


def get_avatar_handler() -> AvatarUploadHandler:
    """AvatarUploadHandler singleton (stateless)."""
    return AvatarUploadHandler()


async def get_upload_service(
    config: Annotated[Config, Depends(get_config)],
    s3: Annotated[S3Service, Depends(get_s3_service)],
    avatar_handler: Annotated[AvatarUploadHandler, Depends(get_avatar_handler)],
) -> UploadService:
    """UploadService dependency — avatar handler included by default.

    Future handlers (chat_attachment, etc.) are registered in this module.
    """
    handlers: dict[str, UploadHandler] = {
        AvatarUploadHandler.category: avatar_handler,
    }
    return UploadService(
        s3=s3,
        bucket=config.workspace_s3.bucket,
        handlers=handlers,
    )
