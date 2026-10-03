"""Atomic input attachment retention-claim primitive for repository composition."""

import dataclasses
import datetime
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.exchange_file_errors import (
    ExchangeFileInputClaimError,
    FileAccessDenied,
    FileExpired,
    FileNotFound,
    FileRetentionOwnerConflict,
    FileUnavailable,
    exchange_object_key_from_uri,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.data import (
    ExchangeFileClaimExpired,
    ExchangeFileClaimNotFound,
    ExchangeFileClaimOwnerConflict,
    ExchangeFileClaimUnavailable,
    ExchangeFileClaimWrongScope,
)
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclasses.dataclass
class InputAttachmentClaimRepository:
    """Preserve authority and retention binding in the acceptance transaction."""

    exchange_file_repository: Annotated[
        ExchangeFileRepository, Depends(ExchangeFileRepository)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]

    async def claim_input_attachments(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        attachment_uris: list[str],
    ) -> Result[None, ExchangeFileInputClaimError]:
        """Claim input ExchangeFiles in the composing repository transaction."""
        if not attachment_uris:
            return Success(None)
        object_keys: list[str] = []
        for uri in attachment_uris:
            object_key = exchange_object_key_from_uri(uri)
            if object_key is None:
                return Failure(FileNotFound())
            object_keys.append(object_key)

        agent_session = await self.agent_session_repository.get_by_id(
            session,
            session_id,
        )
        if agent_session is None or agent_session.agent_id != agent_id:
            return Failure(FileAccessDenied())
        if (
            await self.workspace_user_repository.get_by_workspace_and_user(
                session, workspace_id=agent_session.workspace_id, user_id=user_id
            )
            is None
        ):
            return Failure(FileAccessDenied())
        root = await self.agent_session_repository.get_root_session_agent_by_session_id(
            session,
            session_id,
        )
        if root is None:
            return Failure(FileAccessDenied())

        claim = await self.exchange_file_repository.claim_for_retention_root(
            session,
            object_keys=object_keys,
            workspace_id=agent_session.workspace_id,
            agent_id=agent_id,
            retention_root_session_id=root.agent_session_id,
            bound_at=datetime.datetime.now(datetime.UTC),
        )
        if claim.success:
            return Success(None)
        else:
            error = claim.error
            match error:
                case ExchangeFileClaimNotFound():
                    return Failure(FileNotFound())
                case ExchangeFileClaimWrongScope():
                    return Failure(FileAccessDenied())
                case ExchangeFileClaimExpired():
                    return Failure(FileExpired())
                case ExchangeFileClaimUnavailable():
                    return Failure(FileUnavailable())
                case ExchangeFileClaimOwnerConflict():
                    return Failure(FileRetentionOwnerConflict())
                case _:
                    assert_never(error)
