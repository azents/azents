"""Authorized read-only Historical Memory settings queries."""

import base64
import binascii
import dataclasses
import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
)
from azents.core.historical_memory_settings import HistoricalMemorySettingsScope
from azents.core.vfs import VFS_FILE_MAX_BYTES
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.historical_memory.settings_data import (
    HistoricalMemorySettingsCursorError,
    HistoricalMemorySettingsPage,
    HistoricalMemorySettingsRecord,
)


class _HistoricalMemorySettingsCursor(BaseModel):
    """Typed payload carried by the opaque settings cursor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_activity_through: datetime.datetime
    prepared_at: datetime.datetime
    source_session_id: str = Field(min_length=32, max_length=32)


@dataclasses.dataclass
class HistoricalMemorySettingsRepository:
    """Own current-scope Historical Memory settings SQL."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]

    async def list(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        scope: HistoricalMemorySettingsScope,
        query: str | None,
        cursor: str | None,
        limit: int,
    ) -> HistoricalMemorySettingsPage:
        """Return one authorized, stable settings page."""
        if limit < 1:
            raise ValueError("Historical Memory settings limit must be positive.")
        decoded_cursor = self._decode_cursor(cursor) if cursor is not None else None
        statement = self._visible_select(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
        ).where(self._scope_filter(scope=scope, user_id=user_id))
        normalized_query = query.strip() if query is not None else ""
        if normalized_query:
            statement = statement.where(
                sa.or_(
                    RDBAgentSession.title.icontains(
                        normalized_query,
                        autoescape=True,
                    ),
                    RDBHistoricalMemorySource.summary.icontains(
                        normalized_query,
                        autoescape=True,
                    ),
                )
            )
        if decoded_cursor is not None:
            statement = statement.where(self._after_cursor(decoded_cursor))
        statement = statement.order_by(
            RDBHistoricalMemorySource.completed_source_activity_at.desc(),
            RDBHistoricalMemorySource.prepared_at.desc(),
            RDBHistoricalMemorySource.source_session_id,
        ).limit(limit + 1)
        async with self.session_manager() as session:
            rows = list((await session.execute(statement)).all())
        records = tuple(
            self._record(
                source_session_id=source_session_id,
                product_mode=product_mode,
                source_title=source_title,
                source_activity_through=source_activity_through,
                prepared_at=prepared_at,
                summary=summary,
            )
            for (
                source_session_id,
                product_mode,
                source_title,
                source_activity_through,
                prepared_at,
                summary,
            ) in rows[:limit]
        )
        next_cursor = (
            self._encode_cursor(records[-1]) if len(rows) > limit and records else None
        )
        return HistoricalMemorySettingsPage(
            items=records,
            next_cursor=next_cursor,
        )

    async def get(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        source_session_id: str,
    ) -> HistoricalMemorySettingsRecord | None:
        """Return one currently visible Historical Memory settings record."""
        statement = self._visible_select(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
        ).where(
            RDBHistoricalMemorySource.source_session_id == source_session_id,
            sa.or_(
                self._scope_filter(
                    scope=HistoricalMemorySettingsScope.TEAM,
                    user_id=user_id,
                ),
                self._scope_filter(
                    scope=HistoricalMemorySettingsScope.USER,
                    user_id=user_id,
                ),
            ),
        )
        async with self.session_manager() as session:
            row = (await session.execute(statement)).one_or_none()
        if row is None:
            return None
        (
            source_session_id,
            product_mode,
            source_title,
            source_activity_through,
            prepared_at,
            summary,
        ) = row
        return self._record(
            source_session_id=source_session_id,
            product_mode=product_mode,
            source_title=source_title,
            source_activity_through=source_activity_through,
            prepared_at=prepared_at,
            summary=summary,
        )

    @staticmethod
    def _visible_select(
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
    ) -> sa.Select[
        tuple[
            str,
            AgentSessionProductMode | None,
            str | None,
            datetime.datetime | None,
            datetime.datetime | None,
            str | None,
        ]
    ]:
        """Build the lifecycle and membership-gated settings projection."""
        membership = sa.exists(
            sa.select(RDBWorkspaceUser.id).where(
                RDBWorkspaceUser.workspace_id == workspace_id,
                RDBWorkspaceUser.user_id == user_id,
            )
        )
        return (
            sa.select(
                RDBHistoricalMemorySource.source_session_id,
                RDBAgentSession.product_mode,
                RDBAgentSession.title,
                RDBHistoricalMemorySource.completed_source_activity_at,
                RDBHistoricalMemorySource.prepared_at,
                RDBHistoricalMemorySource.summary,
            )
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
            )
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.workspace_id == workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                membership,
                RDBHistoricalMemorySource.completed_source_activity_at.is_not(None),
                RDBHistoricalMemorySource.prepared_at.is_not(None),
                RDBHistoricalMemorySource.summary.is_not(None),
                RDBHistoricalMemorySource.summary != "",
                (
                    sa.func.octet_length(sa.func.coalesce(RDBAgentSession.title, ""))
                    + sa.func.octet_length(RDBHistoricalMemorySource.summary)
                )
                <= VFS_FILE_MAX_BYTES,
            )
        )

    @staticmethod
    def _scope_filter(
        *,
        scope: HistoricalMemorySettingsScope,
        user_id: str,
    ) -> sa.ColumnElement[bool]:
        """Return the exact Team or current-User source predicate."""
        if scope is HistoricalMemorySettingsScope.TEAM:
            return RDBAgentSession.product_mode == AgentSessionProductMode.TEAM
        return sa.and_(
            RDBAgentSession.product_mode == AgentSessionProductMode.USER,
            RDBAgentSession.associated_user_id == user_id,
        )

    @staticmethod
    def _after_cursor(
        cursor: _HistoricalMemorySettingsCursor,
    ) -> sa.ColumnElement[bool]:
        """Return the strict continuation predicate for the stable sort order."""
        activity = RDBHistoricalMemorySource.completed_source_activity_at
        prepared = RDBHistoricalMemorySource.prepared_at
        source_id = RDBHistoricalMemorySource.source_session_id
        return sa.or_(
            activity < cursor.source_activity_through,
            sa.and_(
                activity == cursor.source_activity_through,
                prepared < cursor.prepared_at,
            ),
            sa.and_(
                activity == cursor.source_activity_through,
                prepared == cursor.prepared_at,
                source_id > cursor.source_session_id,
            ),
        )

    @staticmethod
    def _record(
        *,
        source_session_id: str,
        product_mode: AgentSessionProductMode | None,
        source_title: str | None,
        source_activity_through: datetime.datetime | None,
        prepared_at: datetime.datetime | None,
        summary: str | None,
    ) -> HistoricalMemorySettingsRecord:
        """Convert one fully prepared SQL row to the settings contract."""
        if product_mode is AgentSessionProductMode.TEAM:
            scope = HistoricalMemorySettingsScope.TEAM
        elif product_mode is AgentSessionProductMode.USER:
            scope = HistoricalMemorySettingsScope.USER
        else:
            raise ValueError("Historical Memory settings source is not a root Session.")
        if source_activity_through is None or prepared_at is None or summary is None:
            raise ValueError("Historical Memory settings source is not prepared.")
        return HistoricalMemorySettingsRecord(
            source_session_id=source_session_id,
            scope=scope,
            source_title=source_title,
            source_activity_through=source_activity_through,
            prepared_at=prepared_at,
            summary=summary,
        )

    @staticmethod
    def _encode_cursor(record: HistoricalMemorySettingsRecord) -> str:
        payload = _HistoricalMemorySettingsCursor(
            source_activity_through=record.source_activity_through,
            prepared_at=record.prepared_at,
            source_session_id=record.source_session_id,
        ).model_dump_json()
        return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> _HistoricalMemorySettingsCursor:
        try:
            padded = value + "=" * (-len(value) % 4)
            payload = base64.b64decode(
                padded.encode("ascii"),
                altchars=b"-_",
                validate=True,
            ).decode()
            return _HistoricalMemorySettingsCursor.model_validate_json(payload)
        except (
            binascii.Error,
            UnicodeEncodeError,
            UnicodeDecodeError,
            ValidationError,
        ) as error:
            raise HistoricalMemorySettingsCursorError(
                "Historical Memory settings cursor is invalid."
            ) from error
