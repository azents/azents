"""Operation-boundary Google authorization with detached fenced SDK renewal."""

import dataclasses
import datetime
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from pydantic import ValidationError

from azents.core.google_oauth import (
    GoogleConnectionStatus,
    GoogleOAuthError,
)
from azents.core.google_runtime import (
    GoogleExecutionState,
    GoogleOperationAuthorization,
)
from azents.core.google_system_setting import GoogleApplicationUnavailable
from azents.core.google_tool_groups import group_operations
from azents.core.google_workspace_policy import (
    GoogleWorkspaceOperation,
    eligible_model_operations,
    operation_permitted,
)
from azents.core.personal_toolkit_runtime import PersonalToolkitExecutionTarget
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.repos.google_oauth.runtime import GoogleRuntimeRepository
from azents.services.google_application.service import GoogleApplicationService
from azents.services.google_oauth.provider import GoogleOAuthProvider


@dataclasses.dataclass(frozen=True)
class GoogleRuntimeService:
    """Admit current direct operations against exact server-owned grant snapshots."""

    repository: Annotated[GoogleRuntimeRepository, Depends()]
    application: Annotated[GoogleApplicationService, Depends()]
    provider: Annotated[GoogleOAuthProvider, Depends()]

    def for_personal(
        self, target: PersonalToolkitExecutionTarget
    ) -> "GoogleRuntimeService":
        """Retain current grant/client/service checks under exact personal scope."""
        return dataclasses.replace(
            self, repository=self.repository.for_personal(target)
        )

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

    @staticmethod
    def _require_operation(
        current: GoogleExecutionState,
        operation: GoogleWorkspaceOperation,
        auxiliary: tuple[GoogleWorkspaceOperation, ...],
    ) -> None:
        if operation not in group_operations(
            current.config.tool_groups
        ) or not operation_permitted(
            operation,
            current.config.services,
            current.connection.candidate.tokens.granted_scopes,
            auxiliary,
        ):
            raise GoogleOAuthError(
                "capability_unavailable",
                "This Google operation is not currently enabled and permitted.",
            )

    async def direct_operations(
        self,
        owner: SessionExecutionOwner,
        toolkit_id: str,
    ) -> frozenset[GoogleWorkspaceOperation]:
        """Projection reloads current state but never performs provider I/O."""
        current = await self._state(owner, toolkit_id)
        return eligible_model_operations(
            current.config.services,
            current.connection.candidate.tokens.granted_scopes,
        ) & group_operations(current.config.tool_groups)

    async def authorize_operation(
        self,
        owner: SessionExecutionOwner,
        toolkit_id: str,
        operation: GoogleWorkspaceOperation,
        auxiliary_operations: tuple[GoogleWorkspaceOperation, ...]
        | Callable[[str | None], tuple[GoogleWorkspaceOperation, ...]],
    ) -> GoogleOperationAuthorization:
        """Renew only after admitting all argument-dependent prerequisites."""
        current = await self._state(owner, toolkit_id)

        def auxiliary(
            state: GoogleExecutionState,
        ) -> tuple[GoogleWorkspaceOperation, ...]:
            if isinstance(auxiliary_operations, tuple):
                return auxiliary_operations
            return auxiliary_operations(state.connection.candidate.identity.email)

        self._require_operation(current, operation, auxiliary(current))
        await self._renew(owner, current)
        # Even a valid access token needs a fresh post-await owner/config check.
        current = await self._state(owner, toolkit_id)
        resolved_auxiliary = auxiliary(current)
        self._require_operation(current, operation, resolved_auxiliary)
        if current.connection.candidate.tokens.expires_at <= datetime.datetime.now(
            datetime.UTC
        ):
            raise GoogleOAuthError(
                "renewal_unavailable", "Google authorization expired."
            )
        return GoogleOperationAuthorization(
            owner,
            operation,
            resolved_auxiliary,
            current,
        )

    async def recheck_operation(self, admitted: GoogleOperationAuthorization) -> None:
        """Before each effect/publication, reject stale authority without renewal."""
        old = admitted.snapshot
        current = await self._state(admitted.owner, old.connection.toolkit_id)
        self._require_operation(
            current, admitted.operation, admitted.auxiliary_operations
        )
        if (
            current.revision != old.revision
            or current.config != old.config
            or current.connection.id != old.connection.id
            or current.connection.encrypted_payload != old.connection.encrypted_payload
            or current.connection.updated_at != old.connection.updated_at
            or current.registration != old.registration
            or current.connection.candidate.tokens.expires_at
            <= datetime.datetime.now(datetime.UTC)
        ):
            raise GoogleOAuthError(
                "stale",
                "Google authorization changed. The operation was not replayed.",
            )

    async def direct_authentication_failed(
        self,
        admitted: GoogleOperationAuthorization,
    ) -> None:
        """Exact original snapshot defeats a late 401 after config/reconnect changes."""
        await self.repository.finalize_refresh(
            admitted.owner,
            snapshot=admitted.snapshot,
            refreshed=None,
            rejected=True,
        )
