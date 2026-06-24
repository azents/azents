"""S3 module dependency injection.

Replicates the aioboto3 session pattern from ``core/email/deps.py``.
"""

from typing import Annotated, Any, AsyncIterator

from aioboto3.session import Session
from azcommon.infra.s3.service import S3Service
from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.core.email.deps import get_aws_session
from azents.utils.appctx import AppContext


async def get_s3_service(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    session: Annotated[Session, Depends(get_aws_session)],
) -> S3Service:
    """Workspace S3Service dependency.

    When ``workspace_s3.endpoint_url`` is set, use RustFS or a custom S3-compatible
    endpoint. When ``credentials`` is set, inject explicit credentials. Production
    leaves both as None and uses the ambient AWS session plus IAM role.
    """
    s3_config = appctx.config.workspace_s3

    async def get_s3_service_variable() -> AsyncIterator[S3Service]:
        client_kwargs: dict[str, Any] = {}
        if s3_config.endpoint_url is not None:
            client_kwargs["endpoint_url"] = s3_config.endpoint_url
        if s3_config.credentials is not None:
            client_kwargs["aws_access_key_id"] = s3_config.credentials.access_key_id
            client_kwargs["aws_secret_access_key"] = (
                s3_config.credentials.secret_access_key
            )

        async with session.client("s3", **client_kwargs) as client:
            yield S3Service(s3_client=client)

    return await appctx.get_variable(
        f"{__name__}.get_s3_service", get_s3_service_variable
    )
