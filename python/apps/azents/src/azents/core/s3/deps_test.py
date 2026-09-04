"""Workspace S3 dependency tests."""

from types import TracebackType
from unittest.mock import MagicMock, call

import pytest
from aioboto3.session import Session

from azents.core.config import Config, WorkspaceS3Config, WorkspaceS3Credentials
from azents.core.s3.deps import get_s3_service
from azents.utils.appctx import AppContext


class _ClientContext:
    """Track one async S3 client context."""

    def __init__(self, client: object) -> None:
        self.client = client
        self.exited = False

    async def __aenter__(self) -> object:
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True


@pytest.mark.asyncio
async def test_distinct_public_endpoint_uses_separate_presigning_client() -> None:
    """Presigned URLs use the browser endpoint without moving trusted S3 traffic."""
    internal_client = object()
    public_client = object()
    internal_context = _ClientContext(internal_client)
    public_context = _ClientContext(public_client)
    session = MagicMock(spec=Session)
    session.client.side_effect = [internal_context, public_context]
    config = Config.model_construct(
        workspace_s3=WorkspaceS3Config(
            bucket="workspace",
            endpoint_url="http://s3.internal",
            public_endpoint_url="https://s3.example.com",
            credentials=WorkspaceS3Credentials(
                access_key_id="access",
                secret_access_key="secret",
            ),
        )
    )

    async with AppContext(config) as appctx:
        service = await get_s3_service(appctx, session)

        assert service.s3_client is internal_client
        assert service.public_s3_client is public_client
        session.client.assert_has_calls(
            [
                call(
                    "s3",
                    endpoint_url="http://s3.internal",
                    aws_access_key_id="access",
                    aws_secret_access_key="secret",
                ),
                call(
                    "s3",
                    endpoint_url="https://s3.example.com",
                    aws_access_key_id="access",
                    aws_secret_access_key="secret",
                ),
            ]
        )

    assert internal_context.exited is True
    assert public_context.exited is True


@pytest.mark.asyncio
async def test_absent_public_endpoint_reuses_internal_client() -> None:
    """Deployments without a browser endpoint retain one S3 client."""
    internal_client = object()
    internal_context = _ClientContext(internal_client)
    session = MagicMock(spec=Session)
    session.client.return_value = internal_context
    config = Config.model_construct(
        workspace_s3=WorkspaceS3Config(
            bucket="workspace",
            endpoint_url=None,
        )
    )

    async with AppContext(config) as appctx:
        service = await get_s3_service(appctx, session)

        assert service.s3_client is internal_client
        assert service.public_s3_client is internal_client
        session.client.assert_called_once_with("s3")

    assert internal_context.exited is True
