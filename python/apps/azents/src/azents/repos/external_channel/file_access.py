"""Completed database reads for External Channel file transfer authority."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import ExternalChannelFileAccessTarget


@dataclasses.dataclass
class ExternalChannelFileAccessRepository:
    """Own completed binding-scoped file authority reads."""

    work_repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository.create),
    ]
    session_manager: Annotated[
        SessionManager[WriteSession],
        Depends(get_session_manager),
    ]

    async def get_active_target(
        self,
        *,
        session_id: str,
        agent_id: str,
        binding_id: str,
    ) -> ExternalChannelFileAccessTarget | None:
        """Return one detached active file-access target."""
        async with self.session_manager() as session:
            return await self.work_repository.get_active_file_access_target(
                session,
                session_id=session_id,
                agent_id=agent_id,
                binding_id=binding_id,
            )
