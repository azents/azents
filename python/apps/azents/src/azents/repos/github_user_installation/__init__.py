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
        installations: list[dict[str, object]],
    ) -> None:
        """Synchronize user installation list with DB.

        Perform upsert + delete based on list returned by API.

        :param session: DB session
        :param user_id: User ID
        :param installations: Installation list returned by GitHub API
        """
        # Collect installation_id from API result
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

            # Upsert (PostgreSQL ON CONFLICT)
            stmt = insert(RDBGithubUserInstallation).values(
                id=uuid7().hex,
                user_id=user_id,
                installation_id=inst_id,
                account_login=login,
                account_type=account_type,
                account_avatar_url=avatar_url,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_github_user_installations_user_installation",
                set_={
                    "account_login": login,
                    "account_type": account_type,
                    "account_avatar_url": avatar_url,
                    "updated_at": sa.func.now(),
                },
            )
            await session.execute(stmt)

        # Delete installation absent from API result, e.g. user left org
        if api_installation_ids:
            await session.execute(
                delete(RDBGithubUserInstallation).where(
                    RDBGithubUserInstallation.user_id == user_id,
                    RDBGithubUserInstallation.installation_id.notin_(
                        api_installation_ids
                    ),
                )
            )
        else:
            # If API result is empty, delete all installations for user
            await session.execute(
                delete(RDBGithubUserInstallation).where(
                    RDBGithubUserInstallation.user_id == user_id,
                )
            )

    async def has_access(
        self,
        session: AsyncSession,
        user_id: str,
        installation_id: int,
    ) -> bool:
        """Check whether user can access that installation.

        :param session: DB session
        :param user_id: User ID
        :param installation_id: GitHub Installation ID
        :return: Access availability
        """
        result = await session.execute(
            select(RDBGithubUserInstallation.id).where(
                RDBGithubUserInstallation.user_id == user_id,
                RDBGithubUserInstallation.installation_id == installation_id,
            )
        )
        return result.scalar_one_or_none() is not None
