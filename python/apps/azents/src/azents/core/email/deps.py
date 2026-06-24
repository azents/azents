"""Email module dependency injection."""

from typing import Annotated, AsyncIterator

import aioboto3
from aioboto3.session import Session
from fastapi import Depends
from types_aiobotocore_ses.client import SESClient

from azents.core.config import Config, EmailConfig
from azents.core.deps import get_appctx, get_email_config
from azents.utils.appctx import AppContext


async def get_aws_session(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> Session:
    """AWS Session dependency."""

    async def get_aws_session_variable() -> AsyncIterator[Session]:
        yield aioboto3.Session()

    return await appctx.get_variable(
        f"{__name__}.get_aws_session", get_aws_session_variable
    )


async def get_ses_client(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    email_config: Annotated[EmailConfig | None, Depends(get_email_config)],
    session: Annotated[Session, Depends(get_aws_session)],
) -> SESClient | None:
    """SES Client dependency. Returns None when email settings are absent."""
    if email_config is None:
        return None

    async def get_ses_client_variable() -> AsyncIterator[SESClient]:
        async with session.client(
            "ses",
            region_name=email_config.ses_region,
            endpoint_url=email_config.ses_endpoint,
        ) as client:
            yield client

    return await appctx.get_variable(
        f"{__name__}.get_ses_client", get_ses_client_variable
    )
