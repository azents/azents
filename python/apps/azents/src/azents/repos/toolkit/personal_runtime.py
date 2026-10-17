"""Current personal source projection and short parent-serialized effect admission."""

import dataclasses

import sqlalchemy as sa
from pydantic import ValidationError

from azents.core.enums import (
    AgentSessionProductMode,
    MCPOAuthConnectionStatus,
)
from azents.core.github_credentials import GitHubSecretsAppPlatform
from azents.core.github_system_setting import (
    PlatformGitHubAppConfig,
    PlatformGitHubAppSecrets,
)
from azents.core.github_user_oauth import GitHubUserConnectionStatus
from azents.core.google_oauth import GoogleConnectionStatus
from azents.core.personal_toolkit import PersonalToolkitNotFound
from azents.core.personal_toolkit_runtime import (
    PersonalToolkitDenialReason as Reason,
)
from azents.core.personal_toolkit_runtime import (
    PersonalToolkitExecutionDenied,
    PersonalToolkitExecutionTarget,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.system_setting import SystemSettingSection
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.toolkit_ownership import PersonalToolkitAccessMode
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.github_user_oauth import RDBGitHubUserConnection
from azents.rdb.models.google_oauth import RDBGoogleConnection
from azents.rdb.models.toolkit import (
    RDBMCPOAuthConnection,
    RDBPersonalToolkitAgent,
    RDBToolkitConfig,
)
from azents.rdb.models.user import RDBUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.session_execution import (
    CanonicalExecutionSnapshotError,
    SessionExecutionRepository,
)
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit.data import EffectiveToolkitSource, PersonalToolkitConfig
from azents.repos.toolkit.personal import (
    PersonalToolkitRepository,
    active_owner_predicate,
    eligible_personal_agent_ids,
)
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository


@dataclasses.dataclass(frozen=True)
class PersonalExecutionSubject:
    """Repository-local canonical root association."""

    root_session_id: str
    user_id: str


@dataclasses.dataclass(frozen=True)
class PersonalEffectiveToolkitConfig:
    """An already admitted personal source with existing durable namespace identity."""

    toolkit: PersonalToolkitConfig = dataclasses.field(repr=False)
    namespace: str
    target: PersonalToolkitExecutionTarget

    @property
    def source(self) -> EffectiveToolkitSource:
        """Keep the common registered-source discriminator explicit."""
        return EffectiveToolkitSource.USER_OWNED


@dataclasses.dataclass(frozen=True)
class PersonalToolkitRuntimeRepository:
    """Complete exact personal database operations before Provider or Runtime I/O."""

    session_manager: SessionManager[WriteSession]
    toolkits: PersonalToolkitRepository
    namespaces: ToolkitNamespaceRepository
    platform_settings: SystemSettingPayloadResolver | None

    async def _subject(
        self,
        session: WriteSession,
        *,
        owner: SessionExecutionOwner,
        workspace_id: str,
        agent_id: str,
    ) -> PersonalExecutionSubject:
        try:
            canonical = await SessionExecutionRepository().load_canonical_snapshot(
                session,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            )
        except CanonicalExecutionSnapshotError:
            raise PersonalToolkitExecutionDenied(Reason.ROOT_UNAVAILABLE) from None
        if canonical.workspace_id != workspace_id or canonical.agent_id != agent_id:
            raise PersonalToolkitExecutionDenied(Reason.ROOT_UNAVAILABLE)
        root = await session.read_session.get(
            RDBConversation, canonical.root_session_id
        )
        if (
            root is None
            or root.product_mode is not AgentSessionProductMode.USER
            or root.associated_user_id is None
        ):
            raise PersonalToolkitExecutionDenied(Reason.ROOT_UNAVAILABLE)
        active_user = await session.read_session.scalar(
            sa.select(RDBUser.id).where(
                RDBUser.id == root.associated_user_id,
                RDBUser.access_disabled_at.is_(None),
            )
        )
        if active_user is None:
            raise PersonalToolkitExecutionDenied(Reason.OWNER_UNAVAILABLE)
        # The complete eligibility query is narrowed to the canonical workload Agent.
        accessible = await session.read_session.scalar(
            eligible_personal_agent_ids(active_user).where(RDBAgent.id == agent_id)
        )
        if accessible is None:
            raise PersonalToolkitExecutionDenied(Reason.AGENT_ACCESS_DENIED)
        return PersonalExecutionSubject(canonical.root_session_id, active_user)

    async def admit_in_session(
        self,
        session: WriteSession,
        target: PersonalToolkitExecutionTarget,
    ) -> PersonalToolkitConfig:
        """Serialize the exact parent and recheck live canonical authority."""
        try:
            row = await self.toolkits.lock_personal(
                session, user_id=target.owner_user_id, toolkit_id=target.toolkit_id
            )
        except PersonalToolkitNotFound:
            raise PersonalToolkitExecutionDenied(Reason.SOURCE_UNAVAILABLE) from None
        subject = await self._subject(
            session,
            owner=target.execution_owner,
            workspace_id=target.workspace_id,
            agent_id=target.agent_id,
        )
        if (
            subject.user_id != target.owner_user_id
            or subject.root_session_id != target.root_session_id
        ):
            raise PersonalToolkitExecutionDenied(Reason.ROOT_UNAVAILABLE)
        if not row.enabled:
            raise PersonalToolkitExecutionDenied(Reason.SOURCE_UNAVAILABLE)
        if row.revision != target.source_revision:
            raise PersonalToolkitExecutionDenied(Reason.SOURCE_CHANGED)
        if row.personal_access_mode is PersonalToolkitAccessMode.SELECTED:
            selected = await session.read_session.scalar(
                sa.select(RDBPersonalToolkitAgent.toolkit_id).where(
                    RDBPersonalToolkitAgent.toolkit_id == row.id,
                    RDBPersonalToolkitAgent.owner_user_id == subject.user_id,
                    RDBPersonalToolkitAgent.agent_id == target.agent_id,
                )
            )
            if selected is None:
                raise PersonalToolkitExecutionDenied(Reason.AGENT_ACCESS_DENIED)
        if not await self._provider_ready(session, row, target.owner_user_id):
            raise PersonalToolkitExecutionDenied(Reason.PROVIDER_AUTHORIZATION_REQUIRED)
        toolkit = await self.toolkits.get_personal(
            session, user_id=subject.user_id, toolkit_id=row.id
        )
        if toolkit is None:
            raise PersonalToolkitExecutionDenied(Reason.SOURCE_UNAVAILABLE)
        return toolkit

    async def admit(self, target: PersonalToolkitExecutionTarget) -> None:
        """Admit one new effect and release every database lock before external work."""
        async with self.session_manager() as session:
            await self.admit_in_session(session, target)

    async def list_effective(
        self,
        *,
        owner: SessionExecutionOwner,
        workspace_id: str,
        agent_id: str,
    ) -> list[PersonalEffectiveToolkitConfig]:
        """Allocate lazily for this User root; Team roots read no credentials."""
        async with self.session_manager() as session:
            try:
                subject = await self._subject(
                    session, owner=owner, workspace_id=workspace_id, agent_id=agent_id
                )
            except PersonalToolkitExecutionDenied:
                return []
            candidates = list(
                (
                    await session.read_session.execute(
                        sa.select(RDBToolkitConfig.id, RDBToolkitConfig.revision)
                        .where(
                            active_owner_predicate(subject.user_id),
                            RDBToolkitConfig.enabled.is_(True),
                        )
                        .order_by(RDBToolkitConfig.created_at, RDBToolkitConfig.id)
                    )
                ).all()
            )
        result: list[PersonalEffectiveToolkitConfig] = []
        for toolkit_id, revision in candidates:
            target = PersonalToolkitExecutionTarget(
                owner,
                workspace_id,
                agent_id,
                subject.root_session_id,
                subject.user_id,
                toolkit_id,
                revision,
            )
            try:
                async with self.session_manager() as session:
                    toolkit = await self.admit_in_session(session, target)
                    reservation = await self.namespaces.ensure_active(
                        session,
                        agent_id=agent_id,
                        toolkit_id=toolkit.id,
                        base_slug=toolkit.slug,
                    )
                    result.append(
                        PersonalEffectiveToolkitConfig(
                            toolkit, reservation.namespace, target
                        )
                    )
            except PersonalToolkitExecutionDenied:
                continue
        return result

    async def _provider_ready(
        self, session: WriteSession, row: RDBToolkitConfig, user_id: str
    ) -> bool:
        """Check persisted grants; Provider-specific current binding stays guarded."""
        if (
            row.toolkit_type == "github"
            and row.config.get("github_auth_type") == "github_app_platform"
        ):
            if self.platform_settings is None:
                raise RuntimeError(
                    "Platform Toolkit admission requires current settings"
                )
            toolkit = await self.toolkits.get_personal(
                session, user_id=user_id, toolkit_id=row.id
            )
            if toolkit is None or toolkit.credentials is None:
                return False
            try:
                credentials = GitHubSecretsAppPlatform.model_validate_json(
                    toolkit.credentials
                )
                selected = frozenset(
                    int(item.installation_id) for item in credentials.installations
                )
            except ValueError, ValidationError:
                return False
            current = await SystemSettingRepository().get_current(
                session, section=SystemSettingSection.PLATFORM_GITHUB_APP
            )
            registration = self.platform_settings.resolve_current(
                definition=self.platform_settings.registry.get(
                    SystemSettingSection.PLATFORM_GITHUB_APP
                ),
                current=current,
            )
            if not isinstance(
                registration.config, PlatformGitHubAppConfig
            ) or not isinstance(registration.secrets, PlatformGitHubAppSecrets):
                raise TypeError("Unexpected Platform GitHub admission settings")
            if (
                registration.config.app_id != credentials.app_id
                or registration.secrets.private_key is None
            ):
                return False
            inventory = GithubUserInstallationRepository()
            accessible = await inventory.list_accessible_installation_ids(
                session,
                user_id=user_id,
                platform_app_id=credentials.app_id,
                installation_ids=selected,
            )
            return accessible == selected
        if row.toolkit_type == "google":
            return (
                await session.read_session.scalar(
                    sa.select(RDBGoogleConnection.id).where(
                        RDBGoogleConnection.toolkit_id == row.id,
                        RDBGoogleConnection.status == GoogleConnectionStatus.CONNECTED,
                    )
                )
                is not None
            )
        if row.toolkit_type == "github" and row.config.get("github_auth_type") in (
            "github_app_user",
            "github_app_platform_user",
        ):
            return (
                await session.read_session.scalar(
                    sa.select(RDBGitHubUserConnection.id).where(
                        RDBGitHubUserConnection.toolkit_id == row.id,
                        RDBGitHubUserConnection.status
                        == GitHubUserConnectionStatus.CONNECTED,
                    )
                )
                is not None
            )
        if row.toolkit_type in ("notion", "sentry") or (
            row.toolkit_type == "mcp" and row.config.get("auth_type") == "oauth2"
        ):
            return (
                await session.read_session.scalar(
                    sa.select(RDBMCPOAuthConnection.id).where(
                        RDBMCPOAuthConnection.toolkit_id == row.id,
                        RDBMCPOAuthConnection.status
                        == MCPOAuthConnectionStatus.CONNECTED,
                        sa.or_(
                            RDBMCPOAuthConnection.encrypted_access_token.is_not(None),
                            RDBMCPOAuthConnection.encrypted_refresh_token.is_not(None),
                        ),
                    )
                )
                is not None
            )
        return True
