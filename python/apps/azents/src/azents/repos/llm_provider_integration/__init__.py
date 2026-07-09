"""LLM Provider Integration repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import (
    ApiKeySecrets,
    AwsConfig,
    AwsSecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
    GcpConfig,
    GcpSecrets,
    XaiOAuthConfig,
    XaiOAuthSecrets,
)
from azents.core.crypto import CredentialCipher
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration

from .data import (
    LLMProviderIntegration,
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationList,
    LLMProviderIntegrationUpdate,
    LLMProviderIntegrationWithSecrets,
    NotFound,
)

_SecretsUnion = (
    ApiKeySecrets | AwsSecrets | GcpSecrets | ChatGPTOAuthSecrets | XaiOAuthSecrets
)
_secrets_adapter = TypeAdapter[_SecretsUnion](_SecretsUnion)

_ConfigUnion = AwsConfig | GcpConfig | ChatGPTOAuthConfig | XaiOAuthConfig
_config_adapter = TypeAdapter[_ConfigUnion](_ConfigUnion)


class LLMProviderIntegrationRepository:
    """LLM Provider Integration CRUD repository."""

    def __init__(self, cipher: CredentialCipher) -> None:
        """
        :param cipher: Credential encryption/decryption object
        """
        self._cipher = cipher

    async def create(
        self,
        session: AsyncSession,
        create: LLMProviderIntegrationCreate,
    ) -> LLMProviderIntegration:
        """Create LLM Provider Integration.

        :param session: Database session
        :param create: Create data
        :return: Created LLMProviderIntegration
        """
        encrypted = self._cipher.encrypt(create.secrets.model_dump_json())
        config_dict = (
            create.config.model_dump(mode="json") if create.config is not None else None
        )
        rdb_integration = RDBLLMProviderIntegration(
            workspace_id=create.workspace_id,
            provider=create.provider,
            name=create.name,
            encrypted_credentials=encrypted,
            config=config_dict,
            enabled=create.enabled,
        )
        session.add(rdb_integration)
        await session.flush()
        return self._build(rdb_integration)

    async def get_by_id(
        self, session: AsyncSession, integration_id: str
    ) -> LLMProviderIntegration | None:
        """Fetch LLM Provider Integration by ID, excluding secrets.

        :param session: Database session
        :param integration_id: Integration ID
        :return: LLMProviderIntegration or None
        """
        rdb = await session.get(RDBLLMProviderIntegration, integration_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_id_with_secrets(
        self, session: AsyncSession, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Fetch LLM Provider Integration by ID, including secrets.

        :param session: Database session
        :param integration_id: Integration ID
        :return: LLMProviderIntegrationWithSecrets or None
        """
        rdb = await session.get(RDBLLMProviderIntegration, integration_id)
        if rdb is None:
            return None
        return self._build_with_secrets(rdb)

    async def list_by_workspace(
        self, session: AsyncSession, workspace_id: str
    ) -> LLMProviderIntegrationList:
        """Fetch all integrations in workspace.

        :param session: Database session
        :param workspace_id: Workspace ID
        :return: LLMProviderIntegration list
        """
        result = await session.execute(
            sa.select(RDBLLMProviderIntegration)
            .where(RDBLLMProviderIntegration.workspace_id == workspace_id)
            .order_by(RDBLLMProviderIntegration.created_at.desc())
        )
        rdb_integrations = result.scalars().all()
        return LLMProviderIntegrationList(
            items=[self._build(i) for i in rdb_integrations]
        )

    async def update_by_id(
        self,
        session: AsyncSession,
        integration_id: str,
        update: LLMProviderIntegrationUpdate,
    ) -> Result[LLMProviderIntegration, NotFound]:
        """Update LLM Provider Integration by ID.

        :param session: Database session
        :param integration_id: Integration ID
        :param update: Update data
        :return: Updated LLMProviderIntegration or error
        """
        if not update:
            integration = await self.get_by_id(session, integration_id)
            if integration is None:
                return Failure(NotFound(integration_id=integration_id))
            return Success(integration)

        # Process secrets/config separately when included
        db_values: dict[str, object] = {}
        if "name" in update:
            db_values["name"] = update["name"]
        if "enabled" in update:
            db_values["enabled"] = update["enabled"]
        if "secrets" in update:
            db_values["encrypted_credentials"] = self._cipher.encrypt(
                update["secrets"].model_dump_json()
            )
        if "config" in update:
            config = update["config"]
            db_values["config"] = (
                config.model_dump(mode="json") if config is not None else None
            )

        result = await session.execute(
            sa.update(RDBLLMProviderIntegration)
            .where(RDBLLMProviderIntegration.id == integration_id)
            .values(**db_values)
            .returning(RDBLLMProviderIntegration)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return Failure(NotFound(integration_id=integration_id))
        return Success(self._build(rdb))

    async def delete_by_id(self, session: AsyncSession, integration_id: str) -> None:
        """Delete LLM Provider Integration by ID.

        :param session: Database session
        :param integration_id: Integration ID
        """
        await session.execute(
            sa.delete(RDBLLMProviderIntegration).where(
                RDBLLMProviderIntegration.id == integration_id
            )
        )

    def _build(self, rdb: RDBLLMProviderIntegration) -> LLMProviderIntegration:
        """Convert RDB model to domain model, excluding secrets."""
        config = (
            _config_adapter.validate_python(rdb.config)
            if rdb.config is not None
            else None
        )
        return LLMProviderIntegration(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            provider=rdb.provider,
            name=rdb.name,
            config=config,
            enabled=rdb.enabled,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    def _build_with_secrets(
        self, rdb: RDBLLMProviderIntegration
    ) -> LLMProviderIntegrationWithSecrets:
        """Convert RDB model to domain model, including secrets."""
        secrets = _secrets_adapter.validate_json(
            self._cipher.decrypt(rdb.encrypted_credentials)
        )
        config = (
            _config_adapter.validate_python(rdb.config)
            if rdb.config is not None
            else None
        )
        return LLMProviderIntegrationWithSecrets(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            provider=rdb.provider,
            name=rdb.name,
            config=config,
            enabled=rdb.enabled,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
            secrets=secrets,
        )
