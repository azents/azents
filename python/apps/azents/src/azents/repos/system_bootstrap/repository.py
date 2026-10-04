"""System bootstrap state repository."""

import sqlalchemy as sa
from azcommon.datetime import tznow

from azents.rdb.models.system_user_role import RDBSystemBootstrapState
from azents.rdb.session_capabilities import ReadSession, WriteSession

from .data import SystemBootstrapState

_BOOTSTRAP_MUTATION_LOCK_ID = 0x617A656E7474


class SystemBootstrapRepository:
    """Manage the singleton initial-bootstrap state."""

    async def acquire_mutation_lock(self, session: WriteSession) -> None:
        """Serialize initialization and bootstrap attempts.

        :param session: Database session
        """
        await session.write_session.execute(
            sa.select(sa.func.pg_advisory_xact_lock(_BOOTSTRAP_MUTATION_LOCK_ID))
        )

    async def get(self, session: ReadSession) -> SystemBootstrapState | None:
        """Fetch the singleton state.

        :param session: Database session
        :return: Bootstrap state or None
        """
        state = await session.read_session.get(RDBSystemBootstrapState, 1)
        if state is None:
            return None
        return self._build(state)

    async def create(
        self,
        session: WriteSession,
        *,
        token_hash: str,
    ) -> SystemBootstrapState:
        """Create the singleton state.

        :param session: Database session
        :param token_hash: SHA-256 setup token hash
        :return: Created state
        """
        state = RDBSystemBootstrapState(token_hash=token_hash, consumed_at=None)
        session.write_session.add(state)
        await session.write_session.flush()
        await session.write_session.refresh(state)
        return self._build(state)

    async def replace_token(
        self,
        session: WriteSession,
        *,
        token_hash: str,
    ) -> SystemBootstrapState:
        """Replace an active token hash with an operator-configured token.

        :param session: Database session
        :param token_hash: Replacement SHA-256 setup token hash
        :return: Updated state
        """
        result = await session.write_session.execute(
            sa.update(RDBSystemBootstrapState)
            .where(
                RDBSystemBootstrapState.id == 1,
                RDBSystemBootstrapState.consumed_at.is_(None),
            )
            .values(token_hash=token_hash, created_at=tznow())
            .returning(RDBSystemBootstrapState)
        )
        state = result.scalar_one()
        return self._build(state)

    async def consume(self, session: WriteSession) -> None:
        """Mark the active token as consumed.

        :param session: Database session
        """
        result = await session.write_session.execute(
            sa.update(RDBSystemBootstrapState)
            .where(
                RDBSystemBootstrapState.id == 1,
                RDBSystemBootstrapState.consumed_at.is_(None),
            )
            .values(consumed_at=tznow())
            .returning(RDBSystemBootstrapState.id)
        )
        if result.scalar_one_or_none() is None:
            raise RuntimeError("Active system bootstrap state disappeared.")

    @staticmethod
    def _build(state: RDBSystemBootstrapState) -> SystemBootstrapState:
        return SystemBootstrapState.model_validate(state, from_attributes=True)
