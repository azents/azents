"""GitHub per-user Installation Repository."""

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.github_user_installation import RDBGithubUserInstallation


class GithubUserInstallationRepository:
    """GitHub per-user Installation store."""

    async def sync(
        self,
        session: AsyncSession,
        user_id: str,
        platform_app_id: str,
        installations: list[dict[str, object]],
    ) -> None:
        """Synchronize one user's installation list for one Platform App."""
        if not platform_app_id:
            raise ValueError("Platform GitHub App ID is required.")

        api_installation_ids: set[int] = set()

        for inst in installations:
            inst_id = inst.get("id")
            if not isinstance(inst_id, int):
                continue

            account = inst.get("account")
            if not isinstance(account, dict):
                continue

            login = account.get("login")
            account_type = account.get("type")
            avatar_url = account.get("avatar_url", "")

            if not isinstance(login, str) or not isinstance(account_type, str):
                continue
            if not isinstance(avatar_url, str):
                avatar_url = ""

            api_installation_ids.add(inst_id)
            stmt = insert(RDBGithubUserInstallation).values(
                id=uuid7().hex,
                user_id=user_id,
                platform_app_id=platform_app_id,
                installation_id=inst_id,
                account_login=login,
                account_type=account_type,
                account_avatar_url=avatar_url,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    RDBGithubUserInstallation.user_id,
                    RDBGithubUserInstallation.platform_app_id,
                    RDBGithubUserInstallation.installation_id,
                ],
                set_={
                    "account_login": login,
                    "account_type": account_type,
                    "account_avatar_url": avatar_url,
                    "updated_at": sa.func.now(),
                },
            )
            await session.execute(stmt)

        if api_installation_ids:
            await session.execute(
                delete(RDBGithubUserInstallation).where(
                    RDBGithubUserInstallation.user_id == user_id,
                    RDBGithubUserInstallation.platform_app_id == platform_app_id,
                    RDBGithubUserInstallation.installation_id.notin_(
                        api_installation_ids
                    ),
                )
            )
        else:
            await session.execute(
                delete(RDBGithubUserInstallation).where(
                    RDBGithubUserInstallation.user_id == user_id,
                    RDBGithubUserInstallation.platform_app_id == platform_app_id,
                )
            )

    async def has_access(
        self,
        session: AsyncSession,
        user_id: str,
        platform_app_id: str,
        installation_id: int,
    ) -> bool:
        """Check App-scoped installation ownership."""
        result = await session.execute(
            select(RDBGithubUserInstallation.id).where(
                RDBGithubUserInstallation.user_id == user_id,
                RDBGithubUserInstallation.platform_app_id == platform_app_id,
                RDBGithubUserInstallation.installation_id == installation_id,
            )
        )
        return result.scalar_one_or_none() is not None
