"""Common current-file transactions guarded by one common Session owner."""

from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.dialects.postgresql import insert

from azents.core.enums import AgentSessionRunState, AgentSessionStatus
from azents.core.session_execution_file import (
    CurrentExecutionFile,
    ExecutionFileChange,
    ExecutionFileConflict,
    require_execution_path,
    require_execution_text,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.deps import get_session_manager
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.hierarchy_contention import retry_hierarchy_operation
from azents.repos.session_execution_record import SessionExecutionRecordRepository


@dataclass(frozen=True)
class SessionExecutionFileRepository:
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    @staticmethod
    async def _owner(
        session: WriteSession, owner: SessionExecutionOwner, *, mutation: bool
    ) -> None:
        repository = SessionExecutionRecordRepository()
        current = (
            await repository.fence_owner(session, owner)
            if mutation
            else await repository.get_by_id(session, owner.session_id)
        )
        if (
            current is None
            or current.owner_generation != owner.owner_generation
            or current.status is not AgentSessionStatus.ACTIVE
            or current.run_state is not AgentSessionRunState.RUNNING
            or current.stop_requested_at is not None
        ):
            raise PermissionError("Private execution file owner is unavailable.")

    async def read(
        self, owner: SessionExecutionOwner, path: str
    ) -> CurrentExecutionFile | None:
        require_execution_path(path)
        async with self.session_manager() as session:
            await self._owner(session, owner, mutation=False)
            row = await session.read_session.get(
                RDBSessionExecutionFile, (owner.session_id, path)
            )
            return (
                None
                if row is None
                else CurrentExecutionFile(row.path, row.content, row.writable)
            )

    async def list_files(
        self, owner: SessionExecutionOwner
    ) -> tuple[CurrentExecutionFile, ...]:
        async with self.session_manager() as session:
            await self._owner(session, owner, mutation=False)
            rows = await session.read_session.scalars(
                sa.select(RDBSessionExecutionFile)
                .where(RDBSessionExecutionFile.session_id == owner.session_id)
                .order_by(RDBSessionExecutionFile.path)
            )
            return tuple(
                CurrentExecutionFile(row.path, row.content, row.writable)
                for row in rows
            )

    @retry_hierarchy_operation
    async def write(
        self,
        owner: SessionExecutionOwner,
        path: str,
        content: str,
        expected_content: str | None,
        require_observation: bool,
        *,
        overwrite: bool,
    ) -> CurrentExecutionFile:
        require_execution_path(path)
        require_execution_text(content)
        if path == "README.md" or path == "inputs" or path.startswith("inputs/"):
            raise PermissionError("Provided execution input paths are read-only.")
        async with self.session_manager() as session:
            await self._owner(session, owner, mutation=True)
            row = await session.write_session.get(
                RDBSessionExecutionFile, (owner.session_id, path), with_for_update=True
            )
            if row is not None and not row.writable:
                raise PermissionError("Provided execution inputs are read-only.")
            if row is not None and not overwrite:
                raise FileExistsError("File already exists; set overwrite=true.")
            if row is not None and not require_observation:
                raise ExecutionFileConflict(
                    "Read an existing file before replacing it."
                )
            if (
                require_observation
                and (None if row is None else row.content) != expected_content
            ):
                raise ExecutionFileConflict(
                    "Current file content does not match its observation."
                )
            statement = insert(RDBSessionExecutionFile).values(
                session_id=owner.session_id,
                path=path,
                content=content,
                writable=True,
            )
            if overwrite:
                await session.write_session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[
                            RDBSessionExecutionFile.session_id,
                            RDBSessionExecutionFile.path,
                        ],
                        set_={"content": content},
                    )
                )
            else:
                created = await session.write_session.scalar(
                    statement.on_conflict_do_nothing(
                        index_elements=[
                            RDBSessionExecutionFile.session_id,
                            RDBSessionExecutionFile.path,
                        ]
                    ).returning(RDBSessionExecutionFile.path)
                )
                if created is None:
                    raise FileExistsError("File already exists; set overwrite=true.")
            return CurrentExecutionFile(path, content, True)

    async def delete(
        self, owner: SessionExecutionOwner, path: str, expected_content: str | None
    ) -> None:
        await self.atomic_patch(
            owner, (ExecutionFileChange(path, expected_content, None),)
        )

    @retry_hierarchy_operation
    async def atomic_patch(
        self, owner: SessionExecutionOwner, changes: tuple[ExecutionFileChange, ...]
    ) -> tuple[CurrentExecutionFile, ...]:
        if len({change.path for change in changes}) != len(changes):
            raise ValueError("An atomic file patch repeats a path.")
        for change in changes:
            require_execution_path(change.path)
            if (
                change.path == "README.md"
                or change.path == "inputs"
                or change.path.startswith("inputs/")
            ):
                raise PermissionError("Provided execution input paths are read-only.")
            if change.after is not None:
                require_execution_text(change.after)
        async with self.session_manager() as session:
            await self._owner(session, owner, mutation=True)
            rows = {
                row.path: row
                for row in await session.write_session.scalars(
                    sa.select(RDBSessionExecutionFile)
                    .where(
                        RDBSessionExecutionFile.session_id == owner.session_id,
                        RDBSessionExecutionFile.path.in_(
                            tuple(change.path for change in changes)
                        ),
                    )
                    .order_by(RDBSessionExecutionFile.path)
                    .with_for_update()
                )
            }
            for change in changes:
                row = rows.get(change.path)
                if row is not None and not row.writable:
                    raise PermissionError("Provided execution inputs are read-only.")
                if (None if row is None else row.content) != change.before:
                    raise ExecutionFileConflict(
                        "Atomic patch applicability has changed."
                    )
            result = []
            for change in changes:
                if change.after is None:
                    await session.write_session.execute(
                        sa.delete(RDBSessionExecutionFile).where(
                            RDBSessionExecutionFile.session_id == owner.session_id,
                            RDBSessionExecutionFile.path == change.path,
                        )
                    )
                else:
                    await session.write_session.execute(
                        insert(RDBSessionExecutionFile)
                        .values(
                            session_id=owner.session_id,
                            path=change.path,
                            content=change.after,
                            writable=True,
                        )
                        .on_conflict_do_update(
                            index_elements=[
                                RDBSessionExecutionFile.session_id,
                                RDBSessionExecutionFile.path,
                            ],
                            set_={"content": change.after},
                        )
                    )
                    result.append(CurrentExecutionFile(change.path, change.after, True))
            return tuple(result)
