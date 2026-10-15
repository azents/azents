"""Atomic Workspace environment catalog and Agent opt-in persistence."""

from typing import assert_never

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success

from azents.core.enums import WorkspaceUserRole
from azents.core.runtime_environment import (
    InvalidRuntimeEnvironment,
    ReplacementRuntimeEnvironmentValue,
    RuntimeEnvironmentAccessError,
    StoredRuntimeEnvironmentValue,
    parse_runtime_environment,
    validate_runtime_environment,
)
from azents.core.workspace_environment import (
    AgentWorkspaceEnvironmentSettings,
    WorkspaceEnvironmentEntry,
    WorkspaceEnvironmentEntryEdit,
    WorkspaceEnvironmentSettings,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_environment import (
    RDBAgentWorkspaceEnvironmentSelection,
    RDBWorkspaceEnvironmentVariable,
)
from azents.rdb.session_capabilities import ReadSession
from azents.repos.agent_runtime_environment import AgentRuntimeEnvironmentRepository


class WorkspaceEnvironmentRepository:
    """Serialize Workspace then Agent; immutable IDs prevent stale re-opt-in."""

    def __init__(self, agent_environment: AgentRuntimeEnvironmentRepository) -> None:
        self.agent_environment = agent_environment

    async def _rows(
        self, session: ReadSession, workspace_id: str
    ) -> list[RDBWorkspaceEnvironmentVariable]:
        return list(
            (
                await session.read_session.scalars(
                    sa.select(RDBWorkspaceEnvironmentVariable)
                    .where(RDBWorkspaceEnvironmentVariable.workspace_id == workspace_id)
                    .order_by(RDBWorkspaceEnvironmentVariable.name)
                )
            ).all()
        )

    def _metadata(
        self, rows: list[RDBWorkspaceEnvironmentVariable]
    ) -> list[WorkspaceEnvironmentEntry]:
        return [
            WorkspaceEnvironmentEntry(id=row.id, name=row.name, has_value=True)
            for row in rows
        ]

    async def get(
        self, workspace_id: str, *, role: WorkspaceUserRole
    ) -> WorkspaceEnvironmentSettings:
        """Read names only, with the shared-setting write role matrix."""
        async with self.agent_environment.read_session_manager() as session:
            rows = await self._rows(session, workspace_id)
            return WorkspaceEnvironmentSettings(
                entries=self._metadata(rows),
                can_manage=role in {WorkspaceUserRole.OWNER, WorkspaceUserRole.MANAGER},
            )

    async def replace(
        self,
        workspace_id: str,
        *,
        edits: list[WorkspaceEnvironmentEntryEdit],
        role: WorkspaceUserRole,
    ) -> Result[WorkspaceEnvironmentSettings, RuntimeEnvironmentAccessError]:
        """Replace catalog atomically; renamed/deleted IDs cascade selections."""
        if len(edits) > 50:
            raise InvalidRuntimeEnvironment(
                "At most 50 environment variables are allowed."
            )
        if role not in {WorkspaceUserRole.OWNER, WorkspaceUserRole.MANAGER}:
            return Failure(RuntimeEnvironmentAccessError.DENIED)
        async with self.agent_environment.session_manager() as session:
            workspace = await session.write_session.scalar(
                sa.select(RDBWorkspace.id)
                .where(RDBWorkspace.id == workspace_id)
                .with_for_update()
            )
            if workspace is None:
                return Failure(RuntimeEnvironmentAccessError.NOT_FOUND)
            rows = await self._rows(session, workspace_id)
            by_id = {row.id: row for row in rows}
            seen: set[str] = set()
            values: dict[str, str] = {}
            retained: dict[str, str] = {}
            for entry in edits:
                if entry.name in values:
                    raise InvalidRuntimeEnvironment(
                        "Environment variable names must be unique."
                    )
                old = by_id.get(entry.id) if entry.id is not None else None
                if entry.id is not None:
                    if old is None or entry.id in seen:
                        raise InvalidRuntimeEnvironment(
                            "A Workspace variable is missing or repeated. "
                            "Reload the settings."
                        )
                    seen.add(entry.id)
                match entry.value:
                    case StoredRuntimeEnvironmentValue(name=name):
                        if old is None or old.name != name:
                            raise InvalidRuntimeEnvironment(
                                "A retained Workspace variable is unavailable. "
                                "Reload the settings."
                            )
                        values[entry.name] = self.agent_environment.cipher.decrypt(
                            old.encrypted_value
                        )
                    case ReplacementRuntimeEnvironmentValue(value=value):
                        values[entry.name] = value.get_secret_value()
                    case _:
                        assert_never(entry.value)
                if old is not None and old.name == entry.name:
                    retained[entry.name] = old.id
            validate_runtime_environment(values)
            removed = [row.id for row in rows if row.id not in retained.values()]
            if removed:
                await session.write_session.execute(
                    sa.delete(RDBWorkspaceEnvironmentVariable).where(
                        RDBWorkspaceEnvironmentVariable.id.in_(removed)
                    )
                )
            for name, value in values.items():
                encrypted = self.agent_environment.cipher.encrypt(value)
                if name in retained:
                    await session.write_session.execute(
                        sa.update(RDBWorkspaceEnvironmentVariable)
                        .where(RDBWorkspaceEnvironmentVariable.id == retained[name])
                        .values(encrypted_value=encrypted)
                    )
                else:
                    session.write_session.add(
                        RDBWorkspaceEnvironmentVariable(
                            workspace_id=workspace_id,
                            name=name,
                            encrypted_value=encrypted,
                        )
                    )
            await session.write_session.flush()
            return Success(
                WorkspaceEnvironmentSettings(
                    entries=self._metadata(await self._rows(session, workspace_id)),
                    can_manage=True,
                )
            )

    async def _projection(
        self, session: ReadSession, agent: RDBAgent, *, can_manage: bool
    ) -> AgentWorkspaceEnvironmentSettings:
        rows = await self._rows(session, agent.workspace_id)
        selected = set(
            (
                await session.read_session.scalars(
                    sa.select(RDBAgentWorkspaceEnvironmentSelection.variable_id).where(
                        RDBAgentWorkspaceEnvironmentSelection.agent_id == agent.id
                    )
                )
            ).all()
        )
        local = (
            {}
            if agent.encrypted_runtime_environment is None
            else parse_runtime_environment(
                self.agent_environment.cipher.decrypt(
                    agent.encrypted_runtime_environment
                )
            )
        )
        return AgentWorkspaceEnvironmentSettings(
            entries=self._metadata(rows),
            selected_ids=sorted(selected & {row.id for row in rows}),
            overridden_names=sorted(set(local) & {row.name for row in rows}),
            can_manage=can_manage,
        )

    async def agent_settings(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        selected_ids: list[str] | None,
    ) -> Result[AgentWorkspaceEnvironmentSettings, RuntimeEnvironmentAccessError]:
        """Read metadata or replace an explicitly requested opt-in set."""
        if selected_ids is None:
            async with self.agent_environment.read_session_manager() as session:
                agent = await session.read_session.get(RDBAgent, agent_id)
                access = await self.agent_environment.authorize(
                    session,
                    agent,
                    agent_id=agent_id,
                    workspace_id=workspace_id,
                    workspace_user_id=workspace_user_id,
                    role=role,
                    manage=False,
                )
                if isinstance(access, Failure):
                    return access
                assert agent is not None
                return Success(
                    await self._projection(session, agent, can_manage=access.value)
                )
        async with self.agent_environment.session_manager() as session:
            await session.write_session.execute(
                sa.select(RDBWorkspace.id)
                .where(RDBWorkspace.id == workspace_id)
                .with_for_update()
            )
            agent = await session.write_session.scalar(
                sa.select(RDBAgent).where(RDBAgent.id == agent_id).with_for_update()
            )
            access = await self.agent_environment.authorize(
                session,
                agent,
                agent_id=agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                manage=True,
            )
            if isinstance(access, Failure):
                return access
            assert agent is not None
            available = {row.id for row in await self._rows(session, workspace_id)}
            if (
                len(selected_ids) != len(set(selected_ids))
                or not set(selected_ids) <= available
            ):
                raise InvalidRuntimeEnvironment(
                    "Selected Workspace variables are unavailable or repeated. "
                    "Reload the settings."
                )
            await session.write_session.execute(
                sa.delete(RDBAgentWorkspaceEnvironmentSelection).where(
                    RDBAgentWorkspaceEnvironmentSelection.agent_id == agent_id
                )
            )
            session.write_session.add_all(
                [
                    RDBAgentWorkspaceEnvironmentSelection(
                        agent_id=agent_id, variable_id=variable_id
                    )
                    for variable_id in selected_ids
                ]
            )
            await session.write_session.flush()
            return Success(await self._projection(session, agent, can_manage=True))
