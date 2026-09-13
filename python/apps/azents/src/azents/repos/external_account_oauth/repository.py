"""Provider identity OAuth attempt repository."""

import datetime
import json
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import (
    ExternalAccountOAuthAttemptStatus,
    ExternalChannelProvider,
)
from azents.core.system_setting import (
    SystemSettingEnvironment,
    SystemSettingGenerationHasher,
    SystemSettingRegistry,
    SystemSettingSection,
)
from azents.core.system_setting_registry import get_system_setting_registry
from azents.rdb.deps import get_session_manager
from azents.rdb.models.external_account_oauth import RDBExternalAccountOAuthAttempt
from azents.rdb.models.session import RDBSession
from azents.rdb.models.user import RDBUser
from azents.rdb.session import SessionManager
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.services.system_setting.service import (
    get_system_setting_environment,
    get_system_setting_generation_hasher,
)

from .data import (
    ExternalAccountOAuthAttempt,
    ExternalAccountOAuthAttemptCleanupSummary,
    ExternalAccountOAuthAttemptCreate,
)


class ExternalAccountOAuthAttemptRepository:
    """Persist and claim one-time provider OAuth attempts."""

    def __init__(
        self,
        session_manager: Annotated[
            SessionManager[AsyncSession],
            Depends(get_session_manager),
        ],
        system_setting_repository: Annotated[
            SystemSettingRepository,
            Depends(SystemSettingRepository),
        ],
        registry: Annotated[
            SystemSettingRegistry,
            Depends(get_system_setting_registry),
        ],
        cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
        environment: Annotated[
            SystemSettingEnvironment,
            Depends(get_system_setting_environment),
        ],
        generation_hasher: Annotated[
            SystemSettingGenerationHasher,
            Depends(get_system_setting_generation_hasher),
        ],
    ) -> None:
        self.session_manager = session_manager
        self.system_setting_repository = system_setting_repository
        self.registry = registry
        self.cipher = cipher
        self.environment = environment
        self.generation_hasher = generation_hasher

    async def create(
        self,
        *,
        create: ExternalAccountOAuthAttemptCreate,
    ) -> ExternalAccountOAuthAttempt:
        """Insert one open attempt in a repository-owned transaction."""
        async with self.session_manager() as session:
            row = RDBExternalAccountOAuthAttempt(
                state_hash=create.state_hash,
                user_id=create.user_id,
                auth_session_id=create.auth_session_id,
                provider=create.provider,
                setting_generation=create.setting_generation,
                redirect_uri=create.redirect_uri,
                encrypted_pkce_verifier=create.encrypted_pkce_verifier,
                status=ExternalAccountOAuthAttemptStatus.OPEN,
                expires_at=create.expires_at,
                claimed_at=None,
                completed_at=None,
                failed_at=None,
                failure_code=None,
            )
            row.id = create.id
            session.add(row)
            await session.flush()
            return _build(row)

    async def claim_open(
        self,
        *,
        state_hash: str,
        user_id: str,
        auth_session_id: str,
        provider: ExternalChannelProvider,
        setting_generation: str,
        redirect_uri: str,
        now: datetime.datetime,
    ) -> ExternalAccountOAuthAttempt | None:
        """Atomically validate live authority and claim one exact attempt."""
        section = _setting_section(provider)
        async with self.session_manager() as session:
            await self.system_setting_repository.acquire_section_lock(
                session,
                section=section,
            )
            current_generation = await self._current_setting_generation(
                session,
                section=section,
            )
            user = await session.scalar(
                sa.select(RDBUser)
                .where(RDBUser.id == user_id)
                .with_for_update(nowait=True)
            )
            auth_session = await session.scalar(
                sa.select(RDBSession)
                .where(
                    RDBSession.id == auth_session_id,
                    RDBSession.user_id == user_id,
                )
                .with_for_update(nowait=True)
            )
            if (
                user is None
                or user.access_disabled_at is not None
                or auth_session is None
                or auth_session.revoked_at is not None
                or auth_session.expires_at <= now
                or current_generation != setting_generation
            ):
                return None
            row = await session.scalar(
                sa.select(RDBExternalAccountOAuthAttempt)
                .where(
                    RDBExternalAccountOAuthAttempt.state_hash == state_hash,
                    RDBExternalAccountOAuthAttempt.user_id == user_id,
                    RDBExternalAccountOAuthAttempt.auth_session_id == auth_session_id,
                    RDBExternalAccountOAuthAttempt.provider == provider,
                    RDBExternalAccountOAuthAttempt.setting_generation
                    == setting_generation,
                    RDBExternalAccountOAuthAttempt.redirect_uri == redirect_uri,
                    RDBExternalAccountOAuthAttempt.status
                    == ExternalAccountOAuthAttemptStatus.OPEN,
                    RDBExternalAccountOAuthAttempt.expires_at > now,
                )
                .with_for_update(nowait=True)
            )
            if row is None:
                return None
            row.status = ExternalAccountOAuthAttemptStatus.CLAIMED
            row.claimed_at = now
            await session.flush()
            return _build(row)

    async def complete(
        self,
        *,
        attempt_id: str,
        now: datetime.datetime,
    ) -> bool:
        """Mark one claimed attempt complete."""
        async with self.session_manager() as session:
            result = await session.execute(
                sa.update(RDBExternalAccountOAuthAttempt)
                .where(
                    RDBExternalAccountOAuthAttempt.id == attempt_id,
                    RDBExternalAccountOAuthAttempt.status
                    == ExternalAccountOAuthAttemptStatus.CLAIMED,
                )
                .values(
                    status=ExternalAccountOAuthAttemptStatus.COMPLETED,
                    completed_at=now,
                )
                .returning(RDBExternalAccountOAuthAttempt.id)
            )
            return result.scalar_one_or_none() is not None

    async def fail(
        self,
        *,
        attempt_id: str,
        failure_code: str,
        now: datetime.datetime,
    ) -> bool:
        """Mark one claimed attempt failed with a sanitized code."""
        async with self.session_manager() as session:
            result = await session.execute(
                sa.update(RDBExternalAccountOAuthAttempt)
                .where(
                    RDBExternalAccountOAuthAttempt.id == attempt_id,
                    RDBExternalAccountOAuthAttempt.status
                    == ExternalAccountOAuthAttemptStatus.CLAIMED,
                )
                .values(
                    status=ExternalAccountOAuthAttemptStatus.FAILED,
                    failed_at=now,
                    failure_code=failure_code[:120],
                )
                .returning(RDBExternalAccountOAuthAttempt.id)
            )
            return result.scalar_one_or_none() is not None

    async def classify_claim_failure(
        self,
        *,
        state_hash: str,
        user_id: str,
        auth_session_id: str,
        provider: ExternalChannelProvider,
        setting_generation: str,
        redirect_uri: str,
        now: datetime.datetime,
    ) -> str:
        """Classify a rejected callback without disclosing durable attempt data."""
        async with self.session_manager() as session:
            row = await session.scalar(
                sa.select(RDBExternalAccountOAuthAttempt).where(
                    RDBExternalAccountOAuthAttempt.state_hash == state_hash,
                )
            )
            if row is None:
                return "invalid_attempt"
            if row.provider is not provider:
                return "provider_mismatch"
            if row.user_id != user_id or row.auth_session_id != auth_session_id:
                return "auth_session_mismatch"
            if row.redirect_uri != redirect_uri:
                return "invalid_callback"
            if row.setting_generation != setting_generation:
                return "configuration_changed"
            user = await session.scalar(sa.select(RDBUser).where(RDBUser.id == user_id))
            auth_session = await session.scalar(
                sa.select(RDBSession).where(
                    RDBSession.id == auth_session_id,
                    RDBSession.user_id == user_id,
                )
            )
            if (
                user is None
                or user.access_disabled_at is not None
                or auth_session is None
                or auth_session.revoked_at is not None
                or auth_session.expires_at <= now
            ):
                return "auth_session_mismatch"
            if row.expires_at <= now:
                return "expired"
            if row.status is not ExternalAccountOAuthAttemptStatus.OPEN:
                return "already_consumed"
            return "invalid_attempt"

    async def cleanup(
        self,
        *,
        cutoff: datetime.datetime,
        limit: int,
    ) -> ExternalAccountOAuthAttemptCleanupSummary:
        """Delete bounded terminal and expired attempt rows."""
        if limit <= 0:
            return ExternalAccountOAuthAttemptCleanupSummary(deleted_count=0)
        async with self.session_manager() as session:
            rows = (
                await session.scalars(
                    sa.select(RDBExternalAccountOAuthAttempt.id)
                    .where(
                        sa.or_(
                            RDBExternalAccountOAuthAttempt.created_at <= cutoff,
                            RDBExternalAccountOAuthAttempt.expires_at <= cutoff,
                        )
                    )
                    .order_by(
                        RDBExternalAccountOAuthAttempt.created_at,
                        RDBExternalAccountOAuthAttempt.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            ).all()
            if not rows:
                return ExternalAccountOAuthAttemptCleanupSummary(deleted_count=0)
            result = await session.execute(
                sa.delete(RDBExternalAccountOAuthAttempt)
                .where(RDBExternalAccountOAuthAttempt.id.in_(rows))
                .returning(RDBExternalAccountOAuthAttempt.id)
            )
            return ExternalAccountOAuthAttemptCleanupSummary(
                deleted_count=len(result.scalars().all())
            )

    async def _current_setting_generation(
        self,
        session: AsyncSession,
        *,
        section: SystemSettingSection,
    ) -> str:
        """Resolve a Section generation inside the claim transaction."""
        definition = self.registry.get(section)
        current = await self.system_setting_repository.get_current(
            session,
            section=section,
        )
        if current is None:
            config_data: dict[str, object] = {}
            secret_data: dict[str, object] = {}
            schema_version = definition.schema_version
        else:
            config_data = dict(current.config)
            secret_data = (
                {}
                if current.encrypted_secrets is None
                else json.loads(self.cipher.decrypt(current.encrypted_secrets))
            )
            schema_version = current.schema_version
        config_data, secret_data = definition.migrate_payload(
            schema_version=schema_version,
            config=config_data,
            secrets=secret_data,
        )
        for binding in definition.environment_bindings:
            if not self.environment.contains(binding.environment_variable):
                continue
            value = self.environment.get_present(binding.environment_variable)
            if binding.target.value == "config":
                config_data[binding.field_name] = value
            else:
                secret_data[binding.field_name] = value
        config = definition.config_model.model_validate(config_data)
        secrets = definition.secret_model.model_validate(secret_data)
        return self.generation_hasher.generate(
            section=section,
            schema_version=definition.schema_version,
            config=config,
            secrets=secrets,
        )


def _setting_section(provider: ExternalChannelProvider) -> SystemSettingSection:
    if provider is ExternalChannelProvider.SLACK:
        return SystemSettingSection.SLACK_IDENTITY_OAUTH
    return SystemSettingSection.DISCORD_IDENTITY_OAUTH


def _build(row: RDBExternalAccountOAuthAttempt) -> ExternalAccountOAuthAttempt:
    return ExternalAccountOAuthAttempt(
        id=row.id,
        state_hash=row.state_hash,
        user_id=row.user_id,
        auth_session_id=row.auth_session_id,
        provider=row.provider,
        setting_generation=row.setting_generation,
        redirect_uri=row.redirect_uri,
        encrypted_pkce_verifier=row.encrypted_pkce_verifier,
        status=row.status,
        expires_at=row.expires_at,
        claimed_at=row.claimed_at,
        completed_at=row.completed_at,
        failed_at=row.failed_at,
        failure_code=row.failure_code,
        created_at=row.created_at,
    )
