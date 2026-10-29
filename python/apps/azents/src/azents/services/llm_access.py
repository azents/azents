"""Privileged system token lifecycle; Agent bearers cannot invoke this service."""

from dataclasses import dataclass
from typing import Annotated

from azents_llm_contract.authority import IssuedToken
from fastapi import Depends
from pydantic import SecretStr

from azents.core.llm_access import SupplyState, generate_token
from azents.repos.llm_access import LLMAccessRepository


@dataclass
class LLMAccessService:
    repository: Annotated[LLMAccessRepository, Depends(LLMAccessRepository)]

    async def issue(self, *, agent_id: str, subject: str, issuer: str) -> IssuedToken:
        secret = generate_token()
        created = await self.repository.issue(
            agent_id=agent_id, subject=subject, issuer=issuer, digest=secret.digest
        )
        return IssuedToken(
            supply_id=created.supply_id,
            token_id=created.token_id,
            agent_token=SecretStr(secret.value),
            expires_at=created.expires_at,
            predecessor_expires_at=None,
        )

    async def rotate(self, *, supply_id: str, expected_token_id: str) -> IssuedToken:
        secret = generate_token()
        created = await self.repository.rotate(
            supply_id=supply_id,
            expected_token_id=expected_token_id,
            digest=secret.digest,
        )
        return IssuedToken(
            supply_id=created.supply_id,
            token_id=created.token_id,
            agent_token=SecretStr(secret.value),
            expires_at=created.expires_at,
            predecessor_expires_at=created.predecessor_expires_at,
        )

    async def revoke(self, *, supply_id: str, token_id: str | None) -> None:
        await self.repository.revoke(supply_id=supply_id, token_id=token_id)

    async def inspect(self, *, supply_id: str) -> SupplyState:
        return await self.repository.inspect(supply_id=supply_id)

    async def inspect_subject(self, *, agent_id: str, subject: str) -> SupplyState:
        supply_id = await self.repository.find_supply(
            agent_id=agent_id, subject=subject
        )
        return await self.repository.inspect(supply_id=supply_id)
