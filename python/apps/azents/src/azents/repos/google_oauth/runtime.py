"""Canonical Session admission and exact owner-fenced Google renewal persistence."""

import dataclasses
import secrets
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.google_oauth import (
    GoogleCandidate,
    GoogleConnection,
    GoogleConnectionStatus,
    GoogleOAuthError,
    GoogleTokens,
)
from azents.core.google_runtime import GoogleExecutionState
from azents.core.google_system_setting import (
    GoogleApplicationRegistration,
    GoogleApplicationUnavailable,
    resolve_google_registration,
)
from azents.core.personal_toolkit_runtime import (
    PersonalToolkitExecutionDenied,
    PersonalToolkitExecutionTarget,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.system_setting import SystemSettingSection
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.tools import GoogleToolkitConfig
from azents.rdb.deps import get_session_manager
from azents.rdb.models.google_oauth import RDBGoogleConnection
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.session_execution import SessionExecutionRepository
from azents.repos.session_execution.ownership import fence_owned_session_mutation
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import ToolkitConfiguration
from azents.repos.toolkit.personal import PersonalToolkitRepository
from azents.repos.toolkit.personal_runtime import PersonalToolkitRuntimeRepository
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository
from azents.repos.toolkit_operations import get_encrypted_toolkit_repository


def _connection(row: RDBGoogleConnection, cipher: CredentialCipher) -> GoogleConnection:
    return GoogleConnection(
        id=row.id,
        toolkit_id=row.toolkit_id,
        client_id=row.client_id,
        candidate=GoogleCandidate.model_validate_json(
            cipher.decrypt(row.encrypted_payload)
        ),
        status=row.status,
        updated_at=row.updated_at,
        encrypted_payload=row.encrypted_payload,
    )


@dataclasses.dataclass(frozen=True)
class GoogleRuntimeRepository:
    """DB truth owns eligibility; no human login or cache is execution authority."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]
    toolkits: Annotated[ToolkitRepository, Depends(get_encrypted_toolkit_repository)]
    settings: Annotated[SystemSettingRepository, Depends()]
    payloads: Annotated[SystemSettingPayloadResolver, Depends()]

    def for_personal(
        self, target: PersonalToolkitExecutionTarget
    ) -> "PersonalGoogleRuntimeRepository":
        """Bind exact personal authority without changing current Google grant logic."""
        return PersonalGoogleRuntimeRepository(
            self.session_manager,
            self.cipher,
            self.toolkits,
            self.settings,
            self.payloads,
            PersonalToolkitRuntimeRepository(
                self.session_manager,
                PersonalToolkitRepository(self.cipher),
                ToolkitNamespaceRepository(),
                self.payloads,
            ),
            target,
        )

    async def _admit_parent(
        self, session: WriteSession, owner: SessionExecutionOwner, toolkit_id: str
    ) -> None:
        """Shared execution retains its existing Toolkit delegation boundary."""

    async def _delegated_toolkit(
        self, session: WriteSession, owner: SessionExecutionOwner, toolkit_id: str
    ) -> ToolkitConfiguration:
        current = await SessionExecutionRepository().load_common_snapshot(
            session,
            session_id=owner.session_id,
            owner_generation=owner.owner_generation,
        )
        effective = await self.toolkits.list_effective_for_agent(
            session,
            current.agent_id,
            workspace_id=current.workspace_id,
        )
        toolkit = next(
            (item.toolkit for item in effective if item.toolkit.id == toolkit_id), None
        )
        if toolkit is None:
            raise GoogleOAuthError(
                "authorization_unavailable",
                "Google connection is not delegated to this Session.",
            )
        return toolkit

    async def _state(
        self,
        session: WriteSession,
        owner: SessionExecutionOwner,
        toolkit_id: str,
        registration: GoogleApplicationRegistration,
    ) -> GoogleExecutionState:
        toolkit = await self._delegated_toolkit(session, owner, toolkit_id)
        if toolkit.toolkit_type != "google":
            raise GoogleOAuthError(
                "authorization_unavailable", "Google connection is unavailable."
            )
        stored = await self.settings.get_current(
            session, section=SystemSettingSection.GOOGLE_OAUTH
        )
        effective_registration = resolve_google_registration(
            self.payloads.resolve_current(
                definition=self.payloads.registry.get(
                    SystemSettingSection.GOOGLE_OAUTH
                ),
                current=stored,
            ),
            registration.redirect_uri,
        )
        if (
            effective_registration.client_id != registration.client_id
            or not secrets.compare_digest(
                effective_registration.effective_generation,
                registration.effective_generation,
            )
        ):
            raise GoogleOAuthError("stale", "Google operator configuration changed.")
        row = await session.read_session.scalar(
            sa.select(RDBGoogleConnection)
            .where(RDBGoogleConnection.toolkit_id == toolkit_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise GoogleOAuthError(
                "reconnect_required", "Google authorization is unavailable."
            )
        if row.client_id != registration.client_id:
            raise GoogleOAuthError(
                "client_changed",
                "Google application changed. Reconnect this connection.",
            )
        config = GoogleToolkitConfig.model_validate(toolkit.config)
        if not config.security_risk_acknowledged:
            raise GoogleOAuthError(
                "risk_acknowledgement_required",
                "Google connection requires content-risk review.",
            )
        return GoogleExecutionState(
            config, _connection(row, self.cipher), effective_registration
        )

    async def load(
        self,
        owner: SessionExecutionOwner,
        toolkit_id: str,
        registration: GoogleApplicationRegistration,
    ) -> GoogleExecutionState:
        """Complete current canonical Session and grant admission before SDK effects."""
        async with self.session_manager() as session:
            return await self._state(session, owner, toolkit_id, registration)

    async def finalize_refresh(
        self,
        owner: SessionExecutionOwner,
        *,
        snapshot: GoogleExecutionState,
        refreshed: GoogleTokens | None,
        rejected: bool,
    ) -> bool:
        """Stale successes and failures yield to newer saved authority."""
        async with self.session_manager() as session:
            # Keep the existing global settings order shared with confirm, then
            # acquire the personal parent before dependent credential/owner fences.
            await self.settings.acquire_section_lock(
                session, section=SystemSettingSection.GOOGLE_OAUTH
            )
            try:
                await self._admit_parent(session, owner, snapshot.connection.toolkit_id)
            except GoogleOAuthError as error:
                if error.code == "authorization_unavailable":
                    return False
                raise
            await fence_owned_session_mutation(session, owner)
            await session.write_session.scalar(
                sa.select(RDBToolkitConfig.id)
                .where(
                    RDBToolkitConfig.id == snapshot.connection.toolkit_id,
                )
                .with_for_update()
            )
            row = await session.write_session.scalar(
                sa.select(RDBGoogleConnection)
                .where(RDBGoogleConnection.toolkit_id == snapshot.connection.toolkit_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None or (
                row.id != snapshot.connection.id
                or row.encrypted_payload != snapshot.connection.encrypted_payload
                or row.updated_at != snapshot.connection.updated_at
                or row.status is not snapshot.connection.status
            ):
                return False
            try:
                current = await self._state(
                    session,
                    owner,
                    snapshot.connection.toolkit_id,
                    snapshot.registration,
                )
            except GoogleApplicationUnavailable:
                return False
            except GoogleOAuthError as error:
                if error.code not in {
                    "stale",
                    "client_changed",
                    "authorization_unavailable",
                    "reconnect_required",
                    "risk_acknowledgement_required",
                }:
                    raise
                return False
            if current.config != snapshot.config:
                return False
            if rejected:
                row.status = GoogleConnectionStatus.RECONNECT_REQUIRED
            elif refreshed is not None:
                # RFC 6749 refresh omission retains only exact same-current-grant
                # evidence; requests never substitute for provider-granted scopes.
                old = current.connection.candidate
                tokens = GoogleTokens(
                    access_token=refreshed.access_token,
                    refresh_token=refreshed.refresh_token
                    if refreshed.refresh_token is not None
                    else old.tokens.refresh_token,
                    expires_at=refreshed.expires_at,
                    granted_scopes=refreshed.granted_scopes
                    if refreshed.granted_scopes is not None
                    else old.tokens.granted_scopes,
                )
                row.encrypted_payload = self.cipher.encrypt(
                    old.model_copy(update={"tokens": tokens}).model_dump_json()
                )
            else:
                raise AssertionError("Google refresh finalization has no result.")
            await session.write_session.flush()
            return True


@dataclasses.dataclass(frozen=True)
class PersonalGoogleRuntimeRepository(GoogleRuntimeRepository):
    """Compose current personal allowance with existing Google grant/client checks."""

    personal: PersonalToolkitRuntimeRepository
    target: PersonalToolkitExecutionTarget

    async def _delegated_toolkit(
        self,
        session: WriteSession,
        owner: SessionExecutionOwner,
        toolkit_id: str,
    ) -> ToolkitConfiguration:
        if owner != self.target.execution_owner or toolkit_id != self.target.toolkit_id:
            raise GoogleOAuthError(
                "authorization_unavailable", "Google connection is unavailable."
            )
        try:
            return await self.personal.admit_in_session(session, self.target)
        except PersonalToolkitExecutionDenied:
            raise GoogleOAuthError(
                "authorization_unavailable",
                "Personal Google authorization is unavailable.",
            ) from None

    async def _admit_parent(
        self,
        session: WriteSession,
        owner: SessionExecutionOwner,
        toolkit_id: str,
    ) -> None:
        await self._delegated_toolkit(session, owner, toolkit_id)
