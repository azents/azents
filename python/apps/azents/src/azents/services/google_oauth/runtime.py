"""Operation-boundary Google authorization with detached fenced SDK renewal."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from pydantic import ValidationError

from azents.core.google_oauth import (
    GoogleAuthorization,
    GoogleConnectionStatus,
    GoogleOAuthError,
)
from azents.core.google_policy import GoogleService, permitted_tools
from azents.core.google_runtime import GoogleExecutionState
from azents.core.google_system_setting import GoogleApplicationUnavailable
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.repos.google_oauth.runtime import GoogleRuntimeRepository
from azents.services.google_application.service import GoogleApplicationService
from azents.services.google_oauth.provider import GoogleOAuthProvider


@dataclasses.dataclass(frozen=True)
class GoogleRuntimeService:
    """Admit current exact raw tools, not cached account-level token authority."""

    repository: Annotated[GoogleRuntimeRepository, Depends()]
    application: Annotated[GoogleApplicationService, Depends()]
    provider: Annotated[GoogleOAuthProvider, Depends()]

    async def _state(
        self,
        owner: SessionExecutionOwner,
        toolkit_id: str,
    ) -> GoogleExecutionState:
        try:
            registration = await self.application.resolve()
            current = await self.repository.load(owner, toolkit_id, registration)
        except GoogleApplicationUnavailable, ValidationError:
            raise GoogleOAuthError(
                "operator_setup_required", "Google operator preparation is invalid."
            ) from None
        if current.connection.status is not GoogleConnectionStatus.CONNECTED:
            raise GoogleOAuthError(
                "reconnect_required", "Reconnect the Google connection."
            )
        return current

    async def _renew(
        self,
        owner: SessionExecutionOwner,
        snapshot: GoogleExecutionState,
    ) -> GoogleExecutionState:
        tokens = snapshot.connection.candidate.tokens
        if tokens.expires_at > datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            minutes=1
        ):
            return snapshot
        if not tokens.refresh_token:
            await self.repository.finalize_refresh(
                owner,
                snapshot=snapshot,
                refreshed=None,
                rejected=True,
            )
            raise GoogleOAuthError(
                "reconnect_required", "Google renewal authorization is missing."
            )
        try:
            refreshed = await self.provider.refresh(
                snapshot.registration, tokens.refresh_token
            )
        except GoogleOAuthError as error:
            if error.code not in {"invalid_grant", "invalid_client"}:
                raise
            committed = await self.repository.finalize_refresh(
                owner,
                snapshot=snapshot,
                refreshed=None,
                rejected=True,
            )
            if committed:
                raise GoogleOAuthError(
                    "reconnect_required", "Reconnect the Google connection."
                ) from None
        else:
            await self.repository.finalize_refresh(
                owner,
                snapshot=snapshot,
                refreshed=refreshed,
                rejected=False,
            )
        latest = await self._state(owner, snapshot.connection.toolkit_id)
        if latest.connection.candidate.tokens.expires_at <= datetime.datetime.now(
            datetime.UTC
        ):
            raise GoogleOAuthError(
                "renewal_unavailable", "Google authorization could not be renewed."
            )
        return latest

    async def permitted_tools(
        self,
        owner: SessionExecutionOwner,
        toolkit_id: str,
        service: GoogleService,
    ) -> frozenset[str]:
        """Reload scope/selection evidence without synchronous provider I/O."""
        current = await self._state(owner, toolkit_id)
        return permitted_tools(
            tuple(current.config.tasks),
            current.connection.candidate.tokens.granted_scopes,
            service,
        )

    async def discovery_authorization(
        self,
        owner: SessionExecutionOwner,
        toolkit_id: str,
        service: GoogleService,
    ) -> GoogleAuthorization:
        """Discovery may renew but admits no unknown tool or unselected service."""
        current = await self._renew(owner, await self._state(owner, toolkit_id))
        if not permitted_tools(
            tuple(current.config.tasks),
            current.connection.candidate.tokens.granted_scopes,
            service,
        ):
            raise GoogleOAuthError(
                "capability_unavailable", "No selected Google capability is permitted."
            )
        return GoogleAuthorization(
            current.connection.candidate.tokens.access_token, current.connection.id
        )

    async def authentication_failed(
        self,
        owner: SessionExecutionOwner,
        toolkit_id: str,
        admitted: GoogleAuthorization,
    ) -> None:
        """A proved 401 affects only the still-matching admitted credential."""
        try:
            current = await self._state(owner, toolkit_id)
        except GoogleOAuthError as error:
            if error.code not in {
                "stale",
                "reconnect_required",
                "client_changed",
                "operator_setup_required",
                "authorization_unavailable",
            }:
                raise
            return
        if (
            current.connection.id != admitted.connection_id
            or current.connection.candidate.tokens.access_token != admitted.access_token
        ):
            return
        await self.repository.finalize_refresh(
            owner,
            snapshot=current,
            refreshed=None,
            rejected=True,
        )

    async def authorize_tool(
        self,
        owner: SessionExecutionOwner,
        toolkit_id: str,
        service: GoogleService,
        raw_name: str,
    ) -> GoogleAuthorization:
        """Current exact task/scope admission is repeated after any token renewal."""
        current = await self._state(owner, toolkit_id)
        if raw_name not in permitted_tools(
            tuple(current.config.tasks),
            current.connection.candidate.tokens.granted_scopes,
            service,
        ):
            raise GoogleOAuthError(
                "capability_unavailable",
                "This Google task is not currently selected and permitted.",
            )
        current = await self._renew(owner, current)
        if raw_name not in permitted_tools(
            tuple(current.config.tasks),
            current.connection.candidate.tokens.granted_scopes,
            service,
        ):
            raise GoogleOAuthError(
                "capability_unavailable", "Google permission changed before execution."
            )
        return GoogleAuthorization(
            current.connection.candidate.tokens.access_token, current.connection.id
        )
