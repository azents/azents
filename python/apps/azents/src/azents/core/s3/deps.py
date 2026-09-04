"""S3 module dependency injection."""

from contextlib import AsyncExitStack
from typing import Annotated, Any, AsyncIterator

from aioboto3.session import Session
from azcommon.infra.s3.service import S3Service
from fastapi import Depends

from azents.core.config import Config, WorkspaceS3Credentials
from azents.core.deps import get_appctx
from azents.core.email.deps import get_aws_session
from azents.utils.appctx import AppContext


async def get_s3_service(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    session: Annotated[Session, Depends(get_aws_session)],
) -> S3Service:
    """Workspace S3Service dependency.

    Trusted operations use ``workspace_s3.endpoint_url``. Presigned URLs use
    ``workspace_s3.public_endpoint_url`` when configured so browsers receive a
    reachable endpoint while server-side traffic stays on the internal endpoint.
    """
    s3_config = appctx.config.workspace_s3

    async def get_s3_service_variable() -> AsyncIterator[S3Service]:
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(
                session.client(
                    "s3",
                    **_client_kwargs(
                        endpoint_url=s3_config.endpoint_url,
                        credentials=s3_config.credentials,
                    ),
                )
            )
            public_client = client
            if s3_config.public_endpoint_url is not None:
                public_client = await stack.enter_async_context(
                    session.client(
                        "s3",
                        **_client_kwargs(
                            endpoint_url=s3_config.public_endpoint_url,
                            credentials=s3_config.credentials,
                        ),
                    )
                )
            yield S3Service(s3_client=client, public_s3_client=public_client)

    return await appctx.get_variable(
        f"{__name__}.get_s3_service", get_s3_service_variable
    )


def _client_kwargs(
    *,
    endpoint_url: str | None,
    credentials: WorkspaceS3Credentials | None,
) -> dict[str, Any]:
    """Build one S3 client configuration."""
    client_kwargs: dict[str, Any] = {}
    if endpoint_url is not None:
        client_kwargs["endpoint_url"] = endpoint_url
    if credentials is not None:
        client_kwargs["aws_access_key_id"] = credentials.access_key_id
        client_kwargs["aws_secret_access_key"] = credentials.secret_access_key
    return client_kwargs
