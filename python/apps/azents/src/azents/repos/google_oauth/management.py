"""Database-only Google creation, review and staged reconnect publication."""

import dataclasses
import datetime
import secrets
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from pydantic import TypeAdapter, ValidationError

from azents.core.account_access import ActiveAccountSubjectStatus
from azents.core.auth.permissions import Permissions, has_permission
from azents.core.auth.roles import get_permissions_for_role
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import WorkspaceUserRole
from azents.core.google_oauth import (
    GoogleAttempt,
    GoogleAttemptStatus,
    GoogleCandidate,
    GoogleConnection,
    GoogleConnectionStatus,
    GoogleFinalSettings,
    GoogleManager,
    GoogleOAuthError,
    GooglePersonalSubject,
    GooglePublication,
    GoogleReconnectSettings,
    GoogleSavedConnection,
    GoogleSavedTarget,
    GoogleSetup,
    google_manager_for_owner,
)
from azents.core.google_picker import GooglePickerState
from azents.core.google_policy import GoogleService, GoogleToolGroup
from azents.core.google_system_setting import (
    GoogleApplicationRegistration,
    GoogleApplicationUnavailable,
    GooglePickerApplication,
    resolve_google_registration,
)
from azents.core.google_tool_groups import group_operations
from azents.core.google_workspace_policy import (
    GOOGLE_PICKER_SCOPE,
    eligible_model_operations,
)
from azents.core.system_setting import SystemSettingSection
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.toolkit_identifiers import (
    IdentifierValidationError,
    resolve_create_identifiers,
)
from azents.core.toolkit_ownership import (
    toolkit_owner_from_fields,
)
from azents.core.tools import GoogleToolkitConfig
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.google_oauth import RDBGoogleAttempt, RDBGoogleConnection
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.account_access import evaluate_active_subject
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_mutation_guard import require_active_agent
from azents.repos.session import SessionRepository
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import ToolkitCreate, ToolkitCreation
from azents.repos.toolkit.personal import PersonalToolkitRepository
from azents.repos.toolkit.personal_management import get_personal_toolkit_repository
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository
from azents.repos.toolkit_operations import get_encrypted_toolkit_repository
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository

_FINAL_SETTINGS = TypeAdapter(GoogleFinalSettings | GoogleReconnectSettings)


def attempt_from(row: RDBGoogleAttempt, cipher: CredentialCipher) -> GoogleAttempt:
    """Return detached typed records, never an ORM instance across operation scope."""
    unpublished = row.status in {
        GoogleAttemptStatus.PENDING,
        GoogleAttemptStatus.EXCHANGING,
        GoogleAttemptStatus.REVIEW,
    }
    return GoogleAttempt(
        id=row.id,
        subject=google_manager_for_owner(
            row.user_id,
            row.session_id,
            toolkit_owner_from_fields(
                row.owner_kind,
                workspace_id=row.workspace_id,
                agent_id=row.agent_id,
                user_id=row.owner_user_id,
            ),
        ),
        status=row.status,
        expires_at=row.expires_at,
        setup=None
        if not unpublished or row.encrypted_setup is None
        else GoogleSetup.model_validate_json(cipher.decrypt(row.encrypted_setup)),
        candidate=None
        if not unpublished or row.encrypted_candidate is None
        else GoogleCandidate.model_validate_json(
            cipher.decrypt(row.encrypted_candidate)
        ),
        published_toolkit_id=row.published_toolkit_id,
        published_connection_id=row.published_connection_id,
        final_settings=None
        if row.status is not GoogleAttemptStatus.PUBLISHED or row.final_settings is None
        else _FINAL_SETTINGS.validate_python(row.final_settings),
    )


def expire_attempt(row: RDBGoogleAttempt) -> bool:
    """Erase expired unpublished ciphertext without changing published outcomes."""
    if row.status not in {
        GoogleAttemptStatus.PENDING,
        GoogleAttemptStatus.EXCHANGING,
        GoogleAttemptStatus.REVIEW,
    }:
        return False
    if row.expires_at > datetime.datetime.now(datetime.UTC):
        return False
    row.encrypted_setup = None
    row.encrypted_candidate = None
    row.status = GoogleAttemptStatus.FAILED
    return True


@dataclasses.dataclass(frozen=True)
class GoogleOAuthRepository:
    """Own exact authorization and publication transactions; never perform HTTP."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]
    users: Annotated[UserRepository, Depends()]
    sessions: Annotated[SessionRepository, Depends()]
    workspaces: Annotated[WorkspaceRepository, Depends()]
    members: Annotated[WorkspaceUserRepository, Depends()]
    agents: Annotated[AgentRepository, Depends()]
    agent_admins: Annotated[AgentAdminRepository, Depends()]
    settings: Annotated[SystemSettingRepository, Depends()]
    payloads: Annotated[SystemSettingPayloadResolver, Depends()]
    toolkits: Annotated[ToolkitRepository, Depends(get_encrypted_toolkit_repository)]
    namespaces: Annotated[ToolkitNamespaceRepository, Depends()]
    personal_toolkits: Annotated[
        PersonalToolkitRepository, Depends(get_personal_toolkit_repository)
    ]

    async def _scope(
        self, session: WriteSession, subject: GoogleManager, *, lock: bool
    ) -> None:
        active = await evaluate_active_subject(
            session,
            user_id=subject.user_id,
            session_id=subject.session_id,
            user_repository=self.users,
            session_repository=self.sessions,
        )
        if active is not ActiveAccountSubjectStatus.ACTIVE:
            raise GoogleOAuthError("not_authenticated", "Not authenticated.")
        if isinstance(subject, GooglePersonalSubject):
            if subject.owner.user_id != subject.user_id:
                raise GoogleOAuthError(
                    "forbidden", "Google setup owner does not match."
                )
            workspace = await self.workspaces.get_by_id(session, subject.workspace_id)
            member = await self.members.get_by_workspace_and_user(
                session, subject.workspace_id, subject.user_id
            )
            if workspace is None or member is None:
                raise GoogleOAuthError("not_found", "Google setup context not found.")
            return
        if lock:
            # Parent lifecycle locks precede candidate/Toolkit locks, including
            # FK-cascade deletion and owning-Agent namespace publication.
            await session.write_session.scalar(
                sa.select(RDBWorkspace.id)
                .where(RDBWorkspace.id == subject.workspace_id)
                .with_for_update()
            )
            if subject.agent_id is not None:
                await session.write_session.scalar(
                    sa.select(RDBAgent.id)
                    .where(RDBAgent.id == subject.agent_id)
                    .with_for_update()
                )
        workspace = await self.workspaces.get_by_id(session, subject.workspace_id)
        member = await self.members.get_by_workspace_and_user(
            session, subject.workspace_id, subject.user_id
        )
        if workspace is None or member is None:
            raise GoogleOAuthError("not_found", "Google setup context not found.")
        if subject.agent_id is None:
            if not has_permission(
                get_permissions_for_role(member.role), Permissions.TOOLKITS_WRITE
            ):
                raise GoogleOAuthError(
                    "forbidden", "Toolkit management permission required."
                )
        else:
            agent = await self.agents.get_by_id(session, subject.agent_id)
            if (
                agent is None
                or agent.workspace_id != subject.workspace_id
                or (
                    member.role is not WorkspaceUserRole.OWNER
                    and not await self.agent_admins.is_admin(
                        session, subject.agent_id, member.id
                    )
                )
            ):
                raise GoogleOAuthError("not_found", "Google setup context not found.")
            await require_active_agent(session, agent_id=subject.agent_id)

    async def authorize(self, subject: GoogleManager) -> None:
        """Completed current-manager admission before any provider work."""
        async with self.session_manager() as session:
            await self._scope(session, subject, lock=False)

    async def _registration(
        self,
        session: WriteSession,
        registration: GoogleApplicationRegistration,
    ) -> None:
        await self.settings.acquire_section_lock(
            session, section=SystemSettingSection.GOOGLE_OAUTH
        )
        current = await self.settings.get_current(
            session, section=SystemSettingSection.GOOGLE_OAUTH
        )
        try:
            resolved = self.payloads.resolve_current(
                definition=self.payloads.registry.get(
                    SystemSettingSection.GOOGLE_OAUTH
                ),
                current=current,
            )
            effective = resolve_google_registration(resolved, registration.redirect_uri)
        except GoogleApplicationUnavailable, ValidationError:
            raise GoogleOAuthError(
                "operator_setup_required", "Google operator preparation is invalid."
            ) from None
        if effective.client_id != registration.client_id or not secrets.compare_digest(
            effective.effective_generation, registration.effective_generation
        ):
            raise GoogleOAuthError(
                "stale", "Google operator configuration changed. Restart setup."
            )

    @staticmethod
    def _bound(setup: GoogleSetup, registration: GoogleApplicationRegistration) -> None:
        if (
            setup.client_id != registration.client_id
            or setup.redirect_uri != registration.redirect_uri
            or not secrets.compare_digest(
                setup.effective_generation, registration.effective_generation
            )
        ):
            raise GoogleOAuthError(
                "stale", "Google authorization configuration changed."
            )

    async def _row(
        self,
        session: WriteSession,
        subject: GoogleManager,
        attempt_id: str,
    ) -> RDBGoogleAttempt:
        await self._scope(session, subject, lock=True)
        # Saved Toolkit precedes its candidate in both disconnect and publish.
        target = await session.read_session.scalar(
            sa.select(RDBGoogleAttempt.target_toolkit_id).where(
                RDBGoogleAttempt.id == attempt_id,
                RDBGoogleAttempt.user_id == subject.user_id,
                RDBGoogleAttempt.session_id == subject.session_id,
                RDBGoogleAttempt.workspace_id == subject.workspace_id,
                RDBGoogleAttempt.agent_id == subject.agent_id,
                RDBGoogleAttempt.owner_kind == subject.owner.kind,
                RDBGoogleAttempt.owner_user_id
                == (
                    subject.user_id
                    if isinstance(subject, GooglePersonalSubject)
                    else None
                ),
            )
        )
        if target is not None:
            await session.write_session.scalar(
                sa.select(RDBToolkitConfig.id)
                .where(RDBToolkitConfig.id == target)
                .with_for_update()
            )
        row = await session.write_session.scalar(
            sa.select(RDBGoogleAttempt)
            .where(
                RDBGoogleAttempt.id == attempt_id,
                RDBGoogleAttempt.user_id == subject.user_id,
                RDBGoogleAttempt.session_id == subject.session_id,
                RDBGoogleAttempt.workspace_id == subject.workspace_id,
                RDBGoogleAttempt.agent_id == subject.agent_id,
                RDBGoogleAttempt.owner_kind == subject.owner.kind,
                RDBGoogleAttempt.owner_user_id
                == (
                    subject.user_id
                    if isinstance(subject, GooglePersonalSubject)
                    else None
                ),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise GoogleOAuthError("not_found", "Google setup attempt not found.")
        return row

    async def _toolkit(
        self,
        session: WriteSession,
        subject: GoogleManager,
        toolkit_id: str,
    ) -> RDBToolkitConfig:
        toolkit = await session.write_session.scalar(
            sa.select(RDBToolkitConfig)
            .where(
                RDBToolkitConfig.id == toolkit_id,
                RDBToolkitConfig.workspace_id == subject.workspace_id,
                RDBToolkitConfig.owner_agent_id == subject.agent_id,
                RDBToolkitConfig.owner_kind == subject.owner.kind,
                RDBToolkitConfig.owner_user_id
                == (
                    subject.user_id
                    if isinstance(subject, GooglePersonalSubject)
                    else None
                ),
                RDBToolkitConfig.toolkit_type == "google",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if toolkit is None:
            raise GoogleOAuthError("not_found", "Google connection not found.")
        return toolkit

    async def _target(
        self,
        session: WriteSession,
        subject: GoogleManager,
        toolkit_id: str,
    ) -> GoogleSavedTarget:
        toolkit = await self._toolkit(session, subject, toolkit_id)
        connection = await session.write_session.scalar(
            sa.select(RDBGoogleConnection)
            .where(RDBGoogleConnection.toolkit_id == toolkit_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        config = GoogleToolkitConfig.model_validate(toolkit.config)
        candidate = (
            None
            if connection is None
            else GoogleCandidate.model_validate_json(
                self.cipher.decrypt(connection.encrypted_payload)
            )
        )
        return GoogleSavedTarget(
            toolkit_id=toolkit_id,
            connection_id=None if connection is None else connection.id,
            client_id=None if connection is None else connection.client_id,
            subject=None if candidate is None else candidate.identity.subject,
            granted_scopes=None
            if candidate is None
            else candidate.tokens.granted_scopes,
            status=None if connection is None else connection.status,
            services=config.services,
            tool_groups=config.tool_groups,
            oauth_request_scopes=config.oauth_request_scopes,
            timeout=config.timeout,
        )

    async def start(
        self,
        subject: GoogleManager,
        *,
        registration: GoogleApplicationRegistration,
        setup: GoogleSetup,
        target_toolkit_id: str | None,
    ) -> GoogleAttempt:
        """Retain no app secret and capture exact saved identity for reconnect."""
        async with self.session_manager() as session:
            await self._registration(session, registration)
            await self._scope(session, subject, lock=True)
            self._bound(setup, registration)
            await session.write_session.execute(
                sa.update(RDBGoogleAttempt)
                .where(
                    RDBGoogleAttempt.user_id == subject.user_id,
                    RDBGoogleAttempt.session_id == subject.session_id,
                    RDBGoogleAttempt.workspace_id == subject.workspace_id,
                    RDBGoogleAttempt.agent_id == subject.agent_id,
                    RDBGoogleAttempt.owner_kind == subject.owner.kind,
                    RDBGoogleAttempt.owner_user_id
                    == (
                        subject.user_id
                        if isinstance(subject, GooglePersonalSubject)
                        else None
                    ),
                    RDBGoogleAttempt.status != GoogleAttemptStatus.PUBLISHED,
                    RDBGoogleAttempt.expires_at <= datetime.datetime.now(datetime.UTC),
                )
                .values(
                    encrypted_setup=None,
                    encrypted_candidate=None,
                    status=GoogleAttemptStatus.FAILED,
                )
            )
            target = (
                None
                if target_toolkit_id is None
                else await self._target(session, subject, target_toolkit_id)
            )
            prepared = setup.model_copy(update={"target": target})
            row = RDBGoogleAttempt(
                user_id=subject.user_id,
                session_id=subject.session_id,
                owner_kind=subject.owner.kind,
                owner_user_id=subject.user_id
                if isinstance(subject, GooglePersonalSubject)
                else None,
                workspace_id=subject.workspace_id,
                agent_id=subject.agent_id,
                target_toolkit_id=target_toolkit_id,
                encrypted_setup=self.cipher.encrypt(prepared.model_dump_json()),
                encrypted_candidate=None,
                status=GoogleAttemptStatus.PENDING,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(minutes=10),
                published_toolkit_id=None,
                published_connection_id=None,
                final_settings=None,
            )
            session.write_session.add(row)
            await session.write_session.flush()
            return attempt_from(row, self.cipher)

    async def saved(
        self,
        subject: GoogleManager,
        toolkit_id: str,
    ) -> GoogleSavedConnection:
        """Current projection uses exact ownership, not an unpublished attempt."""
        async with self.session_manager() as session:
            await self._scope(session, subject, lock=True)
            target = await self._target(session, subject, toolkit_id)
            row = await session.read_session.scalar(
                sa.select(RDBGoogleConnection).where(
                    RDBGoogleConnection.toolkit_id == toolkit_id
                )
            )
            connection = (
                None
                if row is None
                else GoogleConnection(
                    id=row.id,
                    toolkit_id=row.toolkit_id,
                    client_id=row.client_id,
                    candidate=GoogleCandidate.model_validate_json(
                        self.cipher.decrypt(row.encrypted_payload)
                    ),
                    status=row.status,
                    updated_at=row.updated_at,
                    encrypted_payload=row.encrypted_payload,
                )
            )
            revision = await session.read_session.scalar(
                sa.select(RDBToolkitConfig.revision).where(
                    RDBToolkitConfig.id == toolkit_id
                )
            )
            if revision is None:
                raise GoogleOAuthError("stale", "Google Toolkit is unavailable.")
            return GoogleSavedConnection(
                toolkit_id=toolkit_id,
                revision=revision,
                services=target.services,
                tool_groups=target.tool_groups,
                oauth_request_scopes=target.oauth_request_scopes,
                timeout=target.timeout,
                connection=connection,
            )

    async def update_services(
        self,
        subject: GoogleManager,
        *,
        toolkit_id: str,
        expected_revision: int,
        services: tuple[GoogleService, ...],
        tool_groups: tuple[GoogleToolGroup, ...],
    ) -> None:
        """Save only local switches while preserving credential and request intent."""
        async with self.session_manager() as session:
            await self._scope(session, subject, lock=True)
            toolkit = await self._toolkit(session, subject, toolkit_id)
            if toolkit.revision != expected_revision:
                raise GoogleOAuthError(
                    "stale", "Google settings changed. Reload current settings."
                )
            config = GoogleToolkitConfig.model_validate(toolkit.config)
            toolkit.config = config.model_copy(
                update={
                    "services": tuple(sorted(set(services))),
                    "tool_groups": tuple(sorted(set(tool_groups))),
                }
            ).model_dump(mode="json")
            toolkit.revision += 1

    async def admit_picker(
        self,
        subject: GoogleManager,
        *,
        toolkit_id: str,
        expected_revision: int,
        connection_id: str,
        application: GooglePickerApplication,
    ) -> GooglePickerState:
        """Admit the saved manager/Drive/file-scope snapshot before scoped renewal."""
        async with self.session_manager() as session:
            await self._scope(session, subject, lock=True)
            await self._registration(session, application.registration)
            toolkit = await self._toolkit(session, subject, toolkit_id)
            if toolkit.revision != expected_revision:
                raise GoogleOAuthError("stale", "Google settings changed. Reload them.")
            config = GoogleToolkitConfig.model_validate(toolkit.config)
            if GoogleService.DRIVE not in config.services:
                raise GoogleOAuthError(
                    "capability_unavailable",
                    "Enable Drive before opening Google Picker.",
                )
            row = await session.write_session.scalar(
                sa.select(RDBGoogleConnection)
                .where(RDBGoogleConnection.toolkit_id == toolkit_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None or row.status is not GoogleConnectionStatus.CONNECTED:
                raise GoogleOAuthError(
                    "reconnect_required", "Reconnect Google before opening Picker."
                )
            if row.id != connection_id:
                raise GoogleOAuthError("stale", "Google connection changed. Reload it.")
            if row.client_id != application.registration.client_id:
                raise GoogleOAuthError(
                    "client_changed",
                    "Google application changed. Reconnect this account.",
                )
            candidate = GoogleCandidate.model_validate_json(
                self.cipher.decrypt(row.encrypted_payload)
            )
            if GOOGLE_PICKER_SCOPE not in (candidate.tokens.granted_scopes or ()):
                raise GoogleOAuthError(
                    "picker_scope_required",
                    "Reconnect with actual app-file authorization to use Picker.",
                )
            if candidate.tokens.refresh_token is None:
                raise GoogleOAuthError(
                    "reconnect_required", "Google renewal authorization is missing."
                )
            return GooglePickerState(
                subject=subject,
                toolkit_id=toolkit_id,
                revision=toolkit.revision,
                config=config,
                connection=GoogleConnection(
                    row.id,
                    row.toolkit_id,
                    row.client_id,
                    candidate,
                    row.status,
                    row.updated_at,
                    row.encrypted_payload,
                ),
                application=application,
            )

    async def finalize_picker(
        self,
        snapshot: GooglePickerState,
        *,
        rotated_refresh: str | None,
        rejected: bool,
    ) -> None:
        """Recheck exact authority; retain only proven current rotation/rejection."""
        if rotated_refresh is not None and rejected:
            raise ValueError("Picker finalization cannot rotate a rejected receipt.")
        async with self.session_manager() as session:
            await self._scope(session, snapshot.subject, lock=True)
            await self._registration(session, snapshot.application.registration)
            toolkit = await self._toolkit(
                session, snapshot.subject, snapshot.toolkit_id
            )
            config = GoogleToolkitConfig.model_validate(toolkit.config)
            if toolkit.revision != snapshot.revision or config != snapshot.config:
                raise GoogleOAuthError(
                    "stale", "Google settings changed during Picker issuance."
                )
            row = await session.write_session.scalar(
                sa.select(RDBGoogleConnection)
                .where(RDBGoogleConnection.toolkit_id == snapshot.toolkit_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            old = snapshot.connection
            if (
                row is None
                or row.id != old.id
                or row.client_id != old.client_id
                or row.status is not GoogleConnectionStatus.CONNECTED
                or row.encrypted_payload != old.encrypted_payload
                or row.updated_at != old.updated_at
            ):
                raise GoogleOAuthError(
                    "stale", "Google credential changed during Picker issuance."
                )
            if rotated_refresh is not None:
                candidate = old.candidate.model_copy(
                    update={
                        "tokens": old.candidate.tokens.model_copy(
                            update={"refresh_token": rotated_refresh}
                        )
                    }
                )
                row.encrypted_payload = self.cipher.encrypt(candidate.model_dump_json())
            if rotated_refresh is not None or rejected:
                row.status = GoogleConnectionStatus.RECONNECT_REQUIRED
                row.updated_at = datetime.datetime.now(datetime.UTC)

    async def load(self, subject: GoogleManager, attempt_id: str) -> GoogleAttempt:
        """Commit expired-secret cleanup before reporting expiry to the service."""
        result: GoogleAttempt | None = None
        async with self.session_manager() as session:
            row = await self._row(session, subject, attempt_id)
            if not expire_attempt(row):
                result = attempt_from(row, self.cipher)
        if result is None:
            raise GoogleOAuthError("expired", "Google setup authorization expired.")
        return result

    async def claim(
        self,
        subject: GoogleManager,
        *,
        attempt_id: str,
        nonce: str,
        registration: GoogleApplicationRegistration,
    ) -> GoogleAttempt:
        """Consume callback once before external exchange; no token I/O in scope."""
        result: GoogleAttempt | None = None
        async with self.session_manager() as session:
            await self._registration(session, registration)
            row = await self._row(session, subject, attempt_id)
            if not expire_attempt(row):
                attempt = attempt_from(row, self.cipher)
                setup = attempt.setup
                if setup is None or row.status is not GoogleAttemptStatus.PENDING:
                    raise GoogleOAuthError(
                        "stale", "Google callback was already consumed."
                    )
                self._bound(setup, registration)
                if not secrets.compare_digest(setup.state_nonce, nonce):
                    raise GoogleOAuthError(
                        "invalid_state", "Google callback state is invalid."
                    )
                row.status = GoogleAttemptStatus.EXCHANGING
                result = attempt_from(row, self.cipher)
        if result is None:
            raise GoogleOAuthError("expired", "Google setup authorization expired.")
        return result

    async def stage(
        self,
        subject: GoogleManager,
        *,
        attempt_id: str,
        registration: GoogleApplicationRegistration,
        candidate: GoogleCandidate,
    ) -> GoogleAttempt:
        """Repeat exact manager/client/attempt fences after provider I/O."""
        result: GoogleAttempt | None = None
        async with self.session_manager() as session:
            await self._registration(session, registration)
            row = await self._row(session, subject, attempt_id)
            if not expire_attempt(row):
                attempt = attempt_from(row, self.cipher)
                setup = attempt.setup
                if setup is None or row.status is not GoogleAttemptStatus.EXCHANGING:
                    raise GoogleOAuthError("stale", "Google setup attempt changed.")
                self._bound(setup, registration)
                if setup.target is not None and setup.target != await self._target(
                    session, subject, setup.target.toolkit_id
                ):
                    raise GoogleOAuthError(
                        "stale", "Saved Google authorization changed."
                    )
                row.encrypted_candidate = self.cipher.encrypt(
                    candidate.model_dump_json()
                )
                row.status = GoogleAttemptStatus.REVIEW
                result = attempt_from(row, self.cipher)
        if result is None:
            raise GoogleOAuthError("expired", "Google setup authorization expired.")
        return result

    async def discard_claimed(self, attempt_id: str) -> None:
        """Erase only this operation's still-unpublished failed receipt."""
        async with self.session_manager() as session:
            await session.write_session.execute(
                sa.update(RDBGoogleAttempt)
                .where(
                    RDBGoogleAttempt.id == attempt_id,
                    RDBGoogleAttempt.status == GoogleAttemptStatus.EXCHANGING,
                )
                .values(
                    encrypted_setup=None,
                    encrypted_candidate=None,
                    status=GoogleAttemptStatus.FAILED,
                )
            )

    async def _outcome(
        self, session: WriteSession, row: RDBGoogleAttempt
    ) -> GooglePublication:
        if row.published_toolkit_id is None or row.published_connection_id is None:
            raise AssertionError("Google publication outcome is incomplete.")
        current = await session.read_session.scalar(
            sa.select(RDBGoogleConnection.id)
            .join(
                RDBToolkitConfig, RDBToolkitConfig.id == RDBGoogleConnection.toolkit_id
            )
            .where(
                RDBGoogleConnection.toolkit_id == row.published_toolkit_id,
                RDBToolkitConfig.workspace_id == row.workspace_id,
                RDBToolkitConfig.owner_agent_id == row.agent_id,
                RDBToolkitConfig.owner_kind == row.owner_kind,
                RDBToolkitConfig.owner_user_id == row.owner_user_id,
                RDBToolkitConfig.toolkit_type == "google",
            )
        )
        return GooglePublication(
            row.published_toolkit_id,
            row.published_connection_id,
            current == row.published_connection_id,
        )

    async def confirm(
        self,
        subject: GoogleManager,
        *,
        attempt_id: str,
        registration: GoogleApplicationRegistration | None,
        settings: GoogleFinalSettings | GoogleReconnectSettings,
    ) -> GooglePublication:
        """Publish exactly once; historical replay never restores old credentials."""
        result: GooglePublication | None = None
        async with self.session_manager() as session:
            await self.settings.acquire_section_lock(
                session, section=SystemSettingSection.GOOGLE_OAUTH
            )
            row = await self._row(session, subject, attempt_id)
            if row.status is GoogleAttemptStatus.PUBLISHED:
                if row.final_settings != settings.model_dump(mode="json"):
                    raise GoogleOAuthError(
                        "stale", "Google confirmation settings changed."
                    )
                return await self._outcome(session, row)
            if registration is None:
                raise GoogleOAuthError(
                    "operator_setup_required",
                    "Google operator preparation is required.",
                )
            await self._registration(session, registration)
            if not expire_attempt(row):
                attempt = attempt_from(row, self.cipher)
                setup, candidate = attempt.setup, attempt.candidate
                if (
                    setup is None
                    or candidate is None
                    or row.status is not GoogleAttemptStatus.REVIEW
                ):
                    raise GoogleOAuthError(
                        "stale", "Google account is not ready for confirmation."
                    )
                self._bound(setup, registration)
                if (
                    not settings.services
                    or not set(settings.tool_groups) <= set(setup.tool_groups)
                    or not set(settings.services) <= set(setup.services)
                    or not set(settings.oauth_request_scopes)
                    <= set(setup.oauth_request_scopes)
                ):
                    raise GoogleOAuthError(
                        "invalid_selection",
                        "Final Google services and request intent must come "
                        "from the reviewed selection.",
                    )
                if (
                    candidate.tokens.expires_at <= datetime.datetime.now(datetime.UTC)
                    or candidate.tokens.refresh_token is None
                ) or not (
                    eligible_model_operations(
                        settings.services, candidate.tokens.granted_scopes
                    )
                    & group_operations(settings.tool_groups)
                ):
                    raise GoogleOAuthError(
                        "no_usable_capability",
                        "Google did not provide a durable usable authorization.",
                    )
                config = GoogleToolkitConfig(
                    services=settings.services,
                    tool_groups=settings.tool_groups,
                    oauth_request_scopes=settings.oauth_request_scopes,
                    timeout=settings.timeout,
                ).model_dump(mode="json")
                if setup.target is None:
                    if not isinstance(settings, GoogleFinalSettings):
                        raise GoogleOAuthError(
                            "invalid_selection",
                            "New Google connection settings are required.",
                        )
                    identifiers = resolve_create_identifiers(
                        toolkit_type="google",
                        canonical_name="Google",
                        submitted_name=settings.name,
                        submitted_slug=settings.slug,
                    )
                    if isinstance(identifiers, IdentifierValidationError):
                        raise GoogleOAuthError(
                            "invalid_selection",
                            "Invalid Google connection name or slug.",
                        )
                    creation = ToolkitCreation(
                        toolkit_type="google",
                        name=identifiers.name,
                        slug=identifiers.slug,
                        description=settings.description,
                        prompt=settings.prompt,
                        config=config,
                        credentials=None,
                        enabled=settings.enabled,
                        always_expose_tools=settings.always_expose_tools,
                    )
                    if isinstance(subject, GooglePersonalSubject):
                        toolkit = await self.personal_toolkits.create_personal(
                            session,
                            user_id=subject.owner.user_id,
                            workspace_id=subject.workspace_id,
                            create=creation,
                        )
                    else:
                        toolkit = await self.toolkits.create(
                            session,
                            ToolkitCreate(
                                workspace_id=subject.workspace_id,
                                owner_agent_id=subject.agent_id,
                                **creation.model_dump(),
                            ),
                        )
                    toolkit_id = toolkit.id
                    if subject.agent_id is not None:
                        await self.namespaces.ensure_active(
                            session,
                            agent_id=subject.agent_id,
                            toolkit_id=toolkit.id,
                            base_slug=toolkit.slug,
                        )
                else:
                    if not isinstance(settings, GoogleReconnectSettings):
                        raise GoogleOAuthError(
                            "invalid_selection",
                            "Reconnect must preserve unrelated saved settings.",
                        )
                    if setup.target != await self._target(
                        session, subject, setup.target.toolkit_id
                    ):
                        raise GoogleOAuthError(
                            "stale",
                            "Saved Google authorization changed. "
                            "Reload before reconnecting.",
                        )
                    toolkit_id = setup.target.toolkit_id
                    await session.write_session.execute(
                        sa.delete(RDBGoogleConnection).where(
                            RDBGoogleConnection.toolkit_id == toolkit_id,
                            RDBGoogleConnection.id == setup.target.connection_id,
                        )
                    )
                    await session.write_session.execute(
                        sa.update(RDBToolkitConfig)
                        .where(RDBToolkitConfig.id == toolkit_id)
                        .values(config=config, revision=RDBToolkitConfig.revision + 1)
                    )
                connection = RDBGoogleConnection(
                    toolkit_id=toolkit_id,
                    client_id=registration.client_id,
                    encrypted_payload=self.cipher.encrypt(candidate.model_dump_json()),
                    status=GoogleConnectionStatus.CONNECTED,
                )
                session.write_session.add(connection)
                await session.write_session.flush()
                row.status = GoogleAttemptStatus.PUBLISHED
                row.encrypted_setup = None
                row.encrypted_candidate = None
                row.published_toolkit_id = toolkit_id
                row.published_connection_id = connection.id
                row.final_settings = settings.model_dump(mode="json")
                result = GooglePublication(toolkit_id, connection.id, True)
        if result is None:
            raise GoogleOAuthError("expired", "Google setup authorization expired.")
        return result

    async def cancel(
        self, subject: GoogleManager, attempt_id: str
    ) -> GooglePublication | None:
        """A completed publication is not reported as proven cancellation."""
        async with self.session_manager() as session:
            row = await self._row(session, subject, attempt_id)
            if row.status is GoogleAttemptStatus.PUBLISHED:
                return await self._outcome(session, row)
            row.encrypted_setup = None
            row.encrypted_candidate = None
            row.status = GoogleAttemptStatus.CANCELLED
        return None

    async def outcome(
        self, subject: GoogleManager, attempt_id: str
    ) -> GooglePublication:
        """Inspect a published result under exact authority without credentials."""
        async with self.session_manager() as session:
            row = await self._row(session, subject, attempt_id)
            if row.status is not GoogleAttemptStatus.PUBLISHED:
                raise GoogleOAuthError("stale", "Google setup is not published.")
            return await self._outcome(session, row)

    async def disconnect(self, subject: GoogleManager, toolkit_id: str) -> None:
        """Local disconnect permanently defeats pending reconnect targets."""
        async with self.session_manager() as session:
            await self._scope(session, subject, lock=True)
            toolkit = await session.write_session.scalar(
                sa.select(RDBToolkitConfig.id)
                .where(
                    RDBToolkitConfig.id == toolkit_id,
                    RDBToolkitConfig.workspace_id == subject.workspace_id,
                    RDBToolkitConfig.owner_agent_id == subject.agent_id,
                    RDBToolkitConfig.owner_kind == subject.owner.kind,
                    RDBToolkitConfig.owner_user_id
                    == (
                        subject.user_id
                        if isinstance(subject, GooglePersonalSubject)
                        else None
                    ),
                    RDBToolkitConfig.toolkit_type == "google",
                )
                .with_for_update()
            )
            if toolkit is None:
                raise GoogleOAuthError("not_found", "Google connection not found.")
            await session.write_session.execute(
                sa.delete(RDBGoogleConnection).where(
                    RDBGoogleConnection.toolkit_id == toolkit_id
                )
            )
            await session.write_session.execute(
                sa.update(RDBGoogleAttempt)
                .where(
                    RDBGoogleAttempt.target_toolkit_id == toolkit_id,
                    RDBGoogleAttempt.status != GoogleAttemptStatus.PUBLISHED,
                )
                .values(
                    encrypted_setup=None,
                    encrypted_candidate=None,
                    status=GoogleAttemptStatus.CANCELLED,
                )
            )
