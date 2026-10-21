"""Manager-only minimal Picker credentials with current grant/client/owner fencing."""

import asyncio
import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.google_oauth import GoogleManager, GoogleOAuthError
from azents.core.google_system_setting import GoogleApplicationUnavailable
from azents.core.google_workspace_policy import GOOGLE_PICKER_SCOPE
from azents.repos.google_oauth.management import GoogleOAuthRepository
from azents.services.google_application.service import GoogleApplicationService
from azents.services.google_oauth.data import (
    GooglePickerTokenInput,
    GooglePickerTokenOutput,
)
from azents.services.google_oauth.provider import GoogleOAuthProvider


@dataclasses.dataclass(frozen=True)
class GooglePickerService:
    """The main credential never leaves the server or becomes a scoped receipt."""

    repository: Annotated[GoogleOAuthRepository, Depends()]
    application: Annotated[GoogleApplicationService, Depends()]
    provider: Annotated[GoogleOAuthProvider, Depends()]

    async def issue(
        self,
        subject: GoogleManager,
        toolkit_id: str,
        expected: GooglePickerTokenInput,
    ) -> GooglePickerTokenOutput:
        await self.repository.authorize(subject)
        try:
            application = await self.application.picker()
        except GoogleApplicationUnavailable:
            raise GoogleOAuthError(
                "picker_setup_required",
                "Ask the operator to configure the Google Picker browser API key "
                "and project/app ID before selecting files.",
            ) from None
        snapshot = await self.repository.admit_picker(
            subject,
            toolkit_id=toolkit_id,
            expected_revision=expected.expected_revision,
            connection_id=expected.connection_id,
            application=application,
        )
        refresh = snapshot.connection.candidate.tokens.refresh_token
        if refresh is None:
            raise AssertionError("Admitted Picker grant has no renewal credential.")
        try:
            receipt = await self.provider.refresh_picker(
                application.registration, refresh
            )
        except asyncio.CancelledError:
            raise
        except GoogleOAuthError as error:
            if error.code in {"invalid_grant", "invalid_client"}:
                await self.repository.finalize_picker(
                    snapshot, rotated_refresh=None, rejected=True
                )
                raise GoogleOAuthError(
                    "reconnect_required", "Reconnect Google before selecting files."
                ) from None
            raise
        rotated = receipt.refresh_token
        if rotated == refresh:
            rotated = None
        # A valid OAuth receipt may still be unsuitable for browser delivery.
        # Preserve observed rotation under the original exact-current fence before
        # rejecting it; it never proves the main grant's renewal coverage unchanged.
        await self.repository.finalize_picker(
            snapshot, rotated_refresh=rotated, rejected=False
        )
        if rotated is not None:
            raise GoogleOAuthError(
                "reconnect_required",
                "Google rotated renewal authorization. Reconnect before using Picker.",
            )
        tokens = receipt.tokens()
        if not {
            "scope",
            "token_type",
        } <= receipt.model_fields_set or tokens.granted_scopes != (
            GOOGLE_PICKER_SCOPE,
        ):
            raise GoogleOAuthError(
                "picker_scope_unverified",
                "Google did not return a verified minimal app-file credential. "
                "No browser token was delivered.",
            )
        if tokens.expires_at <= datetime.datetime.now(
            datetime.UTC
        ) + datetime.timedelta(seconds=15):
            raise GoogleOAuthError(
                "picker_token_unusable",
                "Google Picker authorization expires too soon. "
                "No browser token was delivered.",
            )
        return GooglePickerTokenOutput(
            access_token=tokens.access_token,
            expires_at=tokens.expires_at,
            api_key=application.api_key,
            app_id=application.app_id,
        )
