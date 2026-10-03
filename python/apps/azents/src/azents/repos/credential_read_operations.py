"""Repository-owned ordered Credential read groups."""

import dataclasses
from typing import Annotated, assert_never

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credential_read import (
    CredentialReadFact,
    CredentialReadKind,
    CredentialReadSnapshot,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.user import UserRepository
from azents.repos.user_email import UserEmailRepository


@dataclasses.dataclass(frozen=True)
class CredentialReadOperationRepository:
    """Complete the original database-only groups before application projection."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    user_repository: Annotated[UserRepository, Depends(UserRepository)]
    user_email_repository: Annotated[UserEmailRepository, Depends(UserEmailRepository)]
    password_login_repository: Annotated[
        PasswordLoginRepository, Depends(PasswordLoginRepository)
    ]

    async def read_user_snapshot(
        self, *, user_id: str, kinds: tuple[CredentialReadKind, ...]
    ) -> CredentialReadSnapshot | None:
        """Read initial User eligibility and each ordered query in one group."""
        async with self.session_manager() as session:
            user = await self.user_repository.get(session, user_id)
            if user is None:
                return None
            facts: list[CredentialReadFact] = []
            for kind in kinds:
                match kind:
                    case CredentialReadKind.PASSWORD:
                        configured = (
                            await self.password_login_repository.exists_for_user(
                                session, user_id
                            )
                        )
                    case CredentialReadKind.EMAIL:
                        current_user = await self.user_repository.get(session, user_id)
                        if current_user is None:
                            configured = False
                        else:
                            emails = await self.user_email_repository.list_by_user(
                                session, user_id
                            )
                            configured = any(
                                email.verified_at is not None for email in emails
                            )
                    case _:
                        assert_never(kind)
                facts.append(CredentialReadFact(kind=kind, configured=configured))
            return CredentialReadSnapshot(facts=tuple(facts))

    async def read_login_snapshot(
        self, *, email: str, kinds: tuple[CredentialReadKind, ...]
    ) -> CredentialReadSnapshot:
        """Read each ordered login query, including empty and unknown-address groups."""
        async with self.session_manager() as session:
            facts: list[CredentialReadFact] = []
            for kind in kinds:
                match kind:
                    case CredentialReadKind.PASSWORD:
                        user = await self.user_repository.get_by_email(session, email)
                        configured = (
                            await self.password_login_repository.exists_for_user(
                                session, user.id
                            )
                            if user is not None
                            else False
                        )
                    case CredentialReadKind.EMAIL:
                        user_email = await self.user_email_repository.get_by_email(
                            session, email
                        )
                        configured = (
                            user_email is not None
                            and user_email.verified_at is not None
                        )
                    case _:
                        assert_never(kind)
                facts.append(CredentialReadFact(kind=kind, configured=configured))
            return CredentialReadSnapshot(facts=tuple(facts))
