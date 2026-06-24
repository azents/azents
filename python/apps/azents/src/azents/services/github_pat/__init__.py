"""GitHub PAT service.

Handles GitHub PAT register/fetch/delete/validate business logic.
"""

import dataclasses
import logging
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_config, get_credential_cipher
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.github_pat import GitHubPATRepository
from azents.repos.github_pat.data import GitHubPAT, GitHubPATStatus

logger = logging.getLogger(__name__)

_GITHUB_API_URL = "https://api.github.com"


def _get_pat_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> GitHubPATRepository:
    """GitHubPATRepository dependency."""
    return GitHubPATRepository(cipher)


@dataclasses.dataclass
class GitHubPATService:
    """GitHub PAT service.

    Handles PAT validation, registration, fetch, and deletion.
    GitHub API calls go through proxy.
    """

    pat_repo: Annotated[GitHubPATRepository, Depends(_get_pat_repo)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    config: Annotated[Config, Depends(get_config)]

    async def verify_and_register(
        self,
        *,
        workspace_id: str,
        user_id: str,
        token: str,
    ) -> GitHubPAT | None:
        """Validate and register GitHub PAT.

        Check token validity with GitHub GET /user, then encrypt and store it.

        :param workspace_id: Workspace ID
        :param user_id: User ID
        :param token: GitHub PAT (plaintext)
        :return: Registered GitHubPAT or None (invalid token)
        """
        github_username = await self._verify_token(token)
        if github_username is None:
            return None

        display_hint = token[:8] if len(token) >= 8 else token

        async with self.session_manager() as session:
            return await self.pat_repo.upsert(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
                token=token,
                github_username=github_username,
                display_hint=display_hint,
            )

    async def get_status(
        self,
        workspace_id: str,
        user_id: str,
    ) -> GitHubPATStatus:
        """Fetch PAT status.

        :param workspace_id: Workspace ID
        :param user_id: User ID
        :return: PAT status
        """
        async with self.session_manager() as session:
            return await self.pat_repo.get_status_by_workspace_and_user(
                session, workspace_id, user_id
            )

    async def delete(
        self,
        workspace_id: str,
        user_id: str,
    ) -> None:
        """Delete PAT.

        :param workspace_id: Workspace ID
        :param user_id: User ID
        """
        async with self.session_manager() as session:
            await self.pat_repo.delete_by_workspace_and_user(
                session, workspace_id, user_id
            )

    async def _verify_token(self, token: str) -> str | None:
        """Validate GitHub PAT validity.

        Check token validity and username by calling GET /user.
        Use proxy when proxy is configured.

        :param token: GitHub PAT
        :return: GitHub username or None (invalid token)
        """
        proxy_url = self.config.mcp_proxy_url
        async with httpx.AsyncClient(proxy=proxy_url) as client:
            try:
                response = await client.get(
                    f"{_GITHUB_API_URL}/user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    timeout=10.0,
                )
            except httpx.HTTPError:
                logger.exception("Failed to call GitHub API")
                return None

        if response.status_code != 200:
            return None

        data = response.json()
        login: str | None = data.get("login")
        return login
