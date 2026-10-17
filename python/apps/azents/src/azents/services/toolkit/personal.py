"""Personal management adapters sharing all common Provider configuration behavior."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.google_oauth import GooglePersonalSubject
from azents.core.personal_toolkit import (
    PersonalToolkitAccessMutation,
    PersonalToolkitManager,
)
from azents.core.toolkit_ownership import PersonalToolkitAccess
from azents.repos.toolkit.personal_management import (
    PersonalToolkitEligibleAgent,
    PersonalToolkitManagementRepository,
    PersonalToolkitManagementSnapshot,
)
from azents.services.google_oauth.service import GoogleOAuthService
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import (
    InvalidConfig,
    InvalidCredentials,
    InvalidIdentifier,
    InvalidToolkitType,
    PersonalToolkitOutput,
    ToolkitConfigurationInput,
    ToolkitUpdateInput,
)


@dataclasses.dataclass
class PersonalToolkitService:
    """Orchestrate detached owner-authorized operations around common Provider I/O."""

    operations: Annotated[
        PersonalToolkitManagementRepository,
        Depends(PersonalToolkitManagementRepository),
    ]
    common: Annotated[ToolkitService, Depends(ToolkitService)]
    google: Annotated[GoogleOAuthService, Depends(GoogleOAuthService)]

    async def _output(
        self,
        subject: PersonalToolkitManager,
        snapshot: PersonalToolkitManagementSnapshot,
    ) -> PersonalToolkitOutput:
        output = PersonalToolkitOutput(
            **snapshot.toolkit.model_dump(exclude={"access_mode"}),
            access_mode=snapshot.access.mode,
            selected_agent_ids=snapshot.access.selected_agent_ids,
            oauth_connection=snapshot.oauth_connection,
            github_user_connection=snapshot.github_user_connection,
            authorization_state=None,
            readiness="ready",
        )
        output = await self.common.attach_personal_provider_state(output)
        if output.toolkit_type == "google":
            connection = await self.google.status(
                GooglePersonalSubject(
                    subject.user_id, subject.session_id, output.owner
                ),
                output.id,
            )
            output = output.model_copy(
                update={
                    "readiness": "disabled"
                    if not output.enabled
                    else "ready"
                    if connection.status == "connected"
                    else "authorization_required"
                }
            )
        return output

    async def list(
        self, subject: PersonalToolkitManager
    ) -> Sequence[PersonalToolkitOutput]:
        """List owned connections with the same current Provider readiness semantics."""
        return [
            await self._output(subject, snapshot)
            for snapshot in await self.operations.list(subject)
        ]

    async def agent_connections(
        self,
        subject: PersonalToolkitManager,
        agent_id: str,
    ) -> Sequence[PersonalToolkitOutput]:
        """Project choices only after current ordinary access to the exact Agent."""
        return [
            await self._output(subject, snapshot)
            for snapshot in await self.operations.agent_connections(subject, agent_id)
        ]

    async def get(
        self, subject: PersonalToolkitManager, toolkit_id: str
    ) -> PersonalToolkitOutput:
        """Read exact-owner metadata; credentials remain internal to orchestration."""
        return await self._output(
            subject, await self.operations.get(subject, toolkit_id)
        )

    async def create(
        self,
        subject: PersonalToolkitManager,
        create: ToolkitConfigurationInput,
    ) -> Result[
        PersonalToolkitOutput,
        InvalidToolkitType | InvalidConfig | InvalidIdentifier | InvalidCredentials,
    ]:
        """Validate common Provider fields before an owner-scoped canonical write."""
        await self.operations.authorize(subject)
        prepared = await self.common.prepare_configuration(
            create, user_id=subject.user_id
        )
        if isinstance(prepared, Failure):
            return Failure(prepared.error)
        snapshot = await self.operations.create(
            subject,
            prepared.value.configuration,
            platform_authority=prepared.value.platform_authority,
        )
        return Success(await self._output(subject, snapshot))

    async def update(
        self,
        subject: PersonalToolkitManager,
        toolkit_id: str,
        update: ToolkitUpdateInput,
    ) -> Result[
        PersonalToolkitOutput, InvalidConfig | InvalidIdentifier | InvalidCredentials
    ]:
        """Reuse common credential merge/auth edits, then revalidate current source."""
        current = await self.operations.get(subject, toolkit_id)
        prepared = await self.common.prepare_configuration_update(
            current.toolkit,
            update,
            user_id=subject.user_id,
        )
        if isinstance(prepared, Failure):
            return Failure(prepared.error)
        snapshot = await self.operations.update(
            subject,
            toolkit_id,
            prepared.value.update,
            expected_revision=current.toolkit.revision,
            slug_reset_canonical_name=prepared.value.slug_reset_canonical_name,
            platform_authority=prepared.value.platform_authority,
        )
        return Success(await self._output(subject, snapshot))

    async def delete(self, subject: PersonalToolkitManager, toolkit_id: str) -> None:
        """Delete locally before ordinary Provider cleanup outside DB scopes."""
        revocations = await self.operations.delete(subject, toolkit_id)
        await self.common.github_user_oauth.cleanup_revocations(revocations)

    async def eligible_agents(
        self, subject: PersonalToolkitManager
    ) -> Sequence[PersonalToolkitEligibleAgent]:
        """Return current eligible Agents for the account's permission editors."""
        return await self.operations.eligible_agents(subject)

    async def mutate_access(
        self,
        subject: PersonalToolkitManager,
        mutations: Sequence[PersonalToolkitAccessMutation],
        *,
        agent_id: str | None,
    ) -> Sequence[PersonalToolkitAccess]:
        """Save explicit mode/delta intents through the same atomic authority."""
        return await self.operations.mutate_access(
            subject, mutations, agent_id=agent_id
        )
