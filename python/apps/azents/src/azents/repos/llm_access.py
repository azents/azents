"""Completed database operations for system inference credentials."""

import datetime
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from azents_llm_contract.authority import AuthenticatedIdentity
from fastapi import Depends

from azents.core.enums import AgentLifecycleStatus
from azents.core.llm_access import (
    TOKEN_LIFETIME,
    LLMAccessDenied,
    LLMTokenConflict,
    SupplyState,
    TokenState,
    handover_deadline,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_access import RDBLLMAccessSupply, RDBLLMAccessToken
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession


@dataclass(frozen=True)
class CreatedAccess:
    supply_id: str
    token_id: str
    expires_at: datetime.datetime
    predecessor_expires_at: datetime.datetime | None


async def _lock_agent(
    scope: WriteSession, agent_id: str, *, admission: bool
) -> RDBAgent:
    agent = await scope.write_session.scalar(
        sa.select(RDBAgent)
        .where(RDBAgent.id == agent_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if agent is None or (
        admission
        and (not agent.enabled or agent.lifecycle_status != AgentLifecycleStatus.ACTIVE)
    ):
        raise LLMAccessDenied("Agent is unavailable.")
    return agent


async def _lock_supply(
    scope: WriteSession, supply_id: str, *, admission: bool
) -> RDBLLMAccessSupply:
    """Always lock Agent -> supply -> token, including authentication."""
    agent_id = await scope.write_session.scalar(
        sa.select(RDBLLMAccessSupply.agent_id).where(RDBLLMAccessSupply.id == supply_id)
    )
    if agent_id is None:
        raise LLMAccessDenied("Supply is unavailable.")
    await _lock_agent(scope, agent_id, admission=admission)
    supply = await scope.write_session.scalar(
        sa.select(RDBLLMAccessSupply)
        .where(RDBLLMAccessSupply.id == supply_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if supply is None:
        raise LLMAccessDenied("Supply is unavailable.")
    return supply


async def _now(scope: WriteSession) -> datetime.datetime:
    # Evaluate after acquiring locks: a credential may expire during the wait.
    now = await scope.write_session.scalar(sa.select(sa.func.clock_timestamp()))
    assert isinstance(now, datetime.datetime)
    return now


@dataclass
class LLMAccessRepository:
    """Short DB-only transactions; no provider I/O or recoverable bearer storage."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    async def issue(
        self, *, agent_id: str, subject: str, issuer: str, digest: str
    ) -> CreatedAccess:
        async with self.session_manager() as scope:
            session = scope.write_session
            await _lock_agent(scope, agent_id, admission=True)
            existing = await session.scalar(
                sa.select(RDBLLMAccessSupply.id).where(
                    RDBLLMAccessSupply.agent_id == agent_id,
                    RDBLLMAccessSupply.subject == subject,
                )
            )
            if existing is not None:
                raise LLMTokenConflict(
                    "Supply already exists; inspect its current state."
                )
            now = await _now(scope)
            supply = RDBLLMAccessSupply(
                agent_id=agent_id,
                subject=subject,
                issuer=issuer,
                current_token_id=None,
                revoked_at=None,
                created_at=now,
            )
            session.add(supply)
            await session.flush()
            token = RDBLLMAccessToken(
                supply_id=supply.id,
                digest=digest,
                issued_at=now,
                expires_at=now + TOKEN_LIFETIME,
                handover_until=None,
                revoked_at=None,
            )
            session.add(token)
            await session.flush()
            supply.current_token_id = token.id
            return CreatedAccess(supply.id, token.id, token.expires_at, None)

    async def rotate(
        self, *, supply_id: str, expected_token_id: str, digest: str
    ) -> CreatedAccess:
        async with self.session_manager() as scope:
            session = scope.write_session
            supply = await _lock_supply(scope, supply_id, admission=True)
            if supply.revoked_at is not None:
                raise LLMAccessDenied("Supply is unavailable.")
            if supply.current_token_id != expected_token_id:
                raise LLMTokenConflict("Current token changed.")
            old = await session.scalar(
                sa.select(RDBLLMAccessToken)
                .where(
                    RDBLLMAccessToken.id == expected_token_id,
                    RDBLLMAccessToken.supply_id == supply.id,
                )
                .with_for_update()
            )
            if old is None:
                raise LLMTokenConflict("Current token changed.")
            now = await _now(scope)
            # Explicit privileged replacement also works after expiry/revocation;
            # it never revives the predecessor or extends its absolute lifetime.
            await session.execute(
                sa.update(RDBLLMAccessToken)
                .where(
                    RDBLLMAccessToken.supply_id == supply.id,
                    RDBLLMAccessToken.id != old.id,
                    RDBLLMAccessToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            old.handover_until = handover_deadline(
                original_expiry=old.expires_at, now=now
            )
            if old.revoked_at is not None:
                old.handover_until = min(now, old.expires_at)
            new = RDBLLMAccessToken(
                supply_id=supply.id,
                digest=digest,
                issued_at=now,
                expires_at=now + TOKEN_LIFETIME,
                handover_until=None,
                revoked_at=None,
            )
            session.add(new)
            await session.flush()
            supply.current_token_id = new.id
            return CreatedAccess(supply.id, new.id, new.expires_at, old.handover_until)

    async def revoke(self, *, supply_id: str, token_id: str | None) -> None:
        async with self.session_manager() as scope:
            supply = await _lock_supply(scope, supply_id, admission=False)
            now = await _now(scope)
            query = sa.update(RDBLLMAccessToken).where(
                RDBLLMAccessToken.supply_id == supply.id,
                RDBLLMAccessToken.revoked_at.is_(None),
            )
            if token_id is None:
                supply.revoked_at = now
            else:
                query = query.where(RDBLLMAccessToken.id == token_id)
            await scope.write_session.execute(query.values(revoked_at=now))

    async def inspect(self, *, supply_id: str) -> SupplyState:
        async with self.session_manager() as scope:
            supply = await _lock_supply(scope, supply_id, admission=False)
            tokens = (
                await scope.write_session.scalars(
                    sa.select(RDBLLMAccessToken)
                    .where(RDBLLMAccessToken.supply_id == supply_id)
                    .order_by(RDBLLMAccessToken.issued_at, RDBLLMAccessToken.id)
                )
            ).all()
            return SupplyState(
                supply.id,
                supply.agent_id,
                supply.subject,
                supply.issuer,
                supply.current_token_id,
                supply.revoked_at,
                tuple(
                    TokenState(
                        t.id, t.issued_at, t.expires_at, t.handover_until, t.revoked_at
                    )
                    for t in tokens
                ),
            )

    async def find_supply(self, *, agent_id: str, subject: str) -> str:
        """Recover a nonsecret supply ID after an uncertain issuance response."""
        async with self.session_manager() as scope:
            supply_id = await scope.write_session.scalar(
                sa.select(RDBLLMAccessSupply.id).where(
                    RDBLLMAccessSupply.agent_id == agent_id,
                    RDBLLMAccessSupply.subject == subject,
                )
            )
            if supply_id is None:
                raise LLMAccessDenied("Supply is unavailable.")
            return supply_id

    async def authenticate(self, *, digest: str) -> AuthenticatedIdentity:
        async with self.session_manager() as scope:
            return await self.authenticate_in_session(scope, digest=digest)

    @staticmethod
    async def authenticate_in_session(
        scope: WriteSession, *, digest: str
    ) -> AuthenticatedIdentity:
        supply_id = await scope.write_session.scalar(
            sa.select(RDBLLMAccessToken.supply_id).where(
                RDBLLMAccessToken.digest == digest
            )
        )
        if supply_id is None:
            raise LLMAccessDenied("Invalid inference credential.")
        supply = await _lock_supply(scope, supply_id, admission=True)
        token = await scope.write_session.scalar(
            sa.select(RDBLLMAccessToken)
            .where(
                RDBLLMAccessToken.digest == digest,
                RDBLLMAccessToken.supply_id == supply.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = await _now(scope)
        if (
            token is None
            or supply.revoked_at is not None
            or token.revoked_at is not None
            or token.expires_at <= now
            or (token.handover_until is not None and token.handover_until <= now)
            or (token.id != supply.current_token_id and token.handover_until is None)
        ):
            raise LLMAccessDenied("Invalid inference credential.")
        agent = await scope.write_session.get(RDBAgent, supply.agent_id)
        assert agent is not None  # Agent lock remains held until admission completes.
        return AuthenticatedIdentity(
            agent_id=agent.id,
            workspace_id=agent.workspace_id,
            supply_id=supply.id,
            token_id=token.id,
        )
