"""System-Admin operations for Provider-owned infrastructure Profiles."""

import dataclasses
import logging
from typing import Annotated, NamedTuple

from azcommon.datetime import tznow
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import RuntimeProviderKind
from azents.core.runtime_profile import (
    RuntimeInfrastructureProfileInternalSpec,
    RuntimeInfrastructureProfileKind,
    RuntimeProfileCompatibility,
    RuntimeProfileLifecycle,
    RuntimeReconcileSourceKind,
    digest_runtime_profile_document,
    evaluate_runtime_profile_compatibility,
    parse_runtime_infrastructure_profile_spec,
    required_runtime_profile_capabilities,
)
from azents.core.runtime_provider_contract import RuntimeProviderCapabilityContract
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.runtime_profile.data import (
    RuntimeInfrastructureProfile,
    RuntimeInfrastructureProfileCreate,
    RuntimeInfrastructureProfileDeletion,
    RuntimeInfrastructureProfileDeletionImpact,
    RuntimeInfrastructureProfileReplace,
    WorkspaceRuntimeProfile,
    WorkspaceRuntimeProfileUsage,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import Workspace
from azents.services.terminal_policy.invalidation import (
    TerminalPolicyInvalidationPublisherDependency,
    TerminalPolicySourceInvalidation,
    TerminalPolicySourceScope,
)

logger = logging.getLogger(__name__)


class _CurrentContract(NamedTuple):
    """Current capability contract and its revision identifier."""

    contract: RuntimeProviderCapabilityContract | None
    revision_id: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeInfrastructureProfileProjection:
    """Infrastructure Profile plus current Provider compatibility evidence."""

    profile: RuntimeInfrastructureProfile
    compatibility: RuntimeProfileCompatibility
    capability_revision_id: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeInfrastructureProfileDeletionImpactProjection:
    """Infrastructure Profile plus current deletion impact."""

    profile: RuntimeInfrastructureProfile
    impact: RuntimeInfrastructureProfileDeletionImpact


@dataclasses.dataclass(frozen=True)
class AdminWorkspaceRuntimeProfileDetailProjection:
    """System-Admin read-only Workspace Runtime Profile detail."""

    workspace_id: str
    workspace: Workspace
    profile: WorkspaceRuntimeProfile
    infrastructure_profile: RuntimeInfrastructureProfile
    provider: RuntimeProvider
    usage: WorkspaceRuntimeProfileUsage


@dataclasses.dataclass
class RuntimeProfileAdminUnavailable(Exception):
    """One bounded infrastructure Profile management failure."""

    code: str
    message: str
    current_profile: RuntimeInfrastructureProfile | None = None
    blocking_reference_count: int | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclasses.dataclass
class RuntimeProfileAdminService:
    """Manage typed infrastructure Profiles within one Provider boundary."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]
    provider_repository: Annotated[
        RuntimeProviderRepository, Depends(RuntimeProviderRepository)
    ]
    policy_repository: Annotated[
        RuntimeProviderPolicyRepository, Depends(RuntimeProviderPolicyRepository)
    ]
    workspace_repository: Annotated[WorkspaceRepository, Depends(WorkspaceRepository)]
    terminal_policy_invalidation_publisher: (
        TerminalPolicyInvalidationPublisherDependency
    )

    async def list_profiles(
        self,
        provider_logical_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        include_disabled: bool,
    ) -> list[RuntimeInfrastructureProfileProjection]:
        """List one Provider's Profiles with current compatibility."""
        async with self.session_manager() as session:
            provider = await self._require_provider(session, provider_logical_id)
            self._validate_provider_kind(provider.kind, profile_kind)
            profiles = await self.profile_repository.list_infrastructure_profiles(
                session,
                provider_id=provider.id,
                include_disabled=include_disabled,
            )
            contract, revision_id = await self._current_contract(session, provider)
            return [
                RuntimeInfrastructureProfileProjection(
                    profile=profile,
                    compatibility=self._compatibility(profile, contract),
                    capability_revision_id=revision_id,
                )
                for profile in profiles
            ]

    async def get_profile(
        self,
        provider_logical_id: str,
        profile_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
    ) -> RuntimeInfrastructureProfileProjection:
        """Get one exact Provider-owned Profile."""
        async with self.session_manager() as session:
            provider = await self._require_provider(session, provider_logical_id)
            self._validate_provider_kind(provider.kind, profile_kind)
            profile = await self.profile_repository.get_infrastructure_profile(
                session,
                profile_id=profile_id,
                for_update=False,
            )
            if profile is None or profile.provider_id != provider.id:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_not_found",
                    message="Runtime infrastructure Profile was not found.",
                )
            contract, revision_id = await self._current_contract(session, provider)
            return RuntimeInfrastructureProfileProjection(
                profile=profile,
                compatibility=self._compatibility(profile, contract),
                capability_revision_id=revision_id,
            )

    async def create_profile(
        self,
        provider_logical_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        display_name: str,
        description: str,
        lifecycle: RuntimeProfileLifecycle,
        spec: RuntimeInfrastructureProfileInternalSpec,
        terminal_enabled: bool,
        actor_user_id: str,
    ) -> RuntimeInfrastructureProfileProjection:
        """Create one typed Profile and enqueue its first source version."""
        async with self.session_manager() as session:
            provider = await self._require_provider(session, provider_logical_id)
            if spec.profile_kind is not profile_kind:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_kind_mismatch",
                    message="Profile document does not match the requested API kind.",
                )
            self._validate_provider_kind(provider.kind, spec.profile_kind)
            try:
                profile = await self.profile_repository.create_infrastructure_profile(
                    session,
                    create=RuntimeInfrastructureProfileCreate(
                        provider_id=provider.id,
                        profile_kind=spec.profile_kind,
                        display_name=display_name,
                        description=description,
                        lifecycle=lifecycle,
                        contract_family=spec.contract_family,
                        schema_version=spec.schema_version,
                        spec=spec.model_dump(mode="json"),
                        required_capabilities=tuple(
                            sorted(required_runtime_profile_capabilities(spec))
                        ),
                        terminal_enabled=terminal_enabled,
                        digest=digest_runtime_profile_document(spec),
                        actor_user_id=actor_user_id,
                    ),
                )
            except IntegrityError as error:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_name_conflict",
                    message="A Profile with this name already exists for the Provider.",
                ) from error
            await self.profile_repository.enqueue_reconcile_task(
                session,
                source_type=RuntimeReconcileSourceKind.INFRASTRUCTURE_PROFILE,
                source_id=profile.id,
                source_version=str(profile.version),
                available_at=tznow(),
            )
            contract, revision_id = await self._current_contract(session, provider)
            return RuntimeInfrastructureProfileProjection(
                profile=profile,
                compatibility=evaluate_runtime_profile_compatibility(
                    spec,
                    contract.profile_contracts if contract is not None else [],
                    provider_protocol_version=(
                        contract.protocol_version if contract is not None else None
                    ),
                ),
                capability_revision_id=revision_id,
            )

    async def replace_profile(
        self,
        provider_logical_id: str,
        profile_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        expected_version: int,
        display_name: str,
        description: str,
        lifecycle: RuntimeProfileLifecycle,
        spec: RuntimeInfrastructureProfileInternalSpec,
        terminal_enabled: bool,
        actor_user_id: str,
    ) -> RuntimeInfrastructureProfileProjection:
        """Replace one Profile with optimistic version fencing."""
        async with self.session_manager() as session:
            provider = await self._require_provider(session, provider_logical_id)
            if spec.profile_kind is not profile_kind:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_kind_mismatch",
                    message="Profile document does not match the requested API kind.",
                )
            self._validate_provider_kind(provider.kind, spec.profile_kind)
            current = await self.profile_repository.get_infrastructure_profile(
                session,
                profile_id=profile_id,
                for_update=False,
            )
            if current is None or current.provider_id != provider.id:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_not_found",
                    message="Runtime infrastructure Profile was not found.",
                )
            replacement = RuntimeInfrastructureProfileReplace(
                display_name=display_name,
                description=description,
                lifecycle=lifecycle,
                contract_family=spec.contract_family,
                schema_version=spec.schema_version,
                spec=spec.model_dump(mode="json"),
                required_capabilities=tuple(
                    sorted(required_runtime_profile_capabilities(spec))
                ),
                terminal_enabled=terminal_enabled,
                digest=digest_runtime_profile_document(spec),
                actor_user_id=actor_user_id,
            )
            terminal_only_change = _infrastructure_terminal_only_change(
                current,
                replacement,
            )
            terminal_changed = current.terminal_enabled != terminal_enabled
            try:
                profile = await self.profile_repository.replace_infrastructure_profile(
                    session,
                    provider_id=provider.id,
                    profile_id=profile_id,
                    expected_version=expected_version,
                    replacement=replacement,
                )
            except IntegrityError as error:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_name_conflict",
                    message="A Profile with this name already exists for the Provider.",
                ) from error
            if profile is None:
                latest = await self.profile_repository.get_infrastructure_profile(
                    session,
                    profile_id=profile_id,
                    for_update=False,
                )
                raise RuntimeProfileAdminUnavailable(
                    code="profile_version_conflict",
                    message="Runtime infrastructure Profile version is stale.",
                    current_profile=latest,
                )
            if not terminal_only_change:
                await self.profile_repository.enqueue_reconcile_task(
                    session,
                    source_type=RuntimeReconcileSourceKind.INFRASTRUCTURE_PROFILE,
                    source_id=profile.id,
                    source_version=str(profile.version),
                    available_at=tznow(),
                )
            contract, revision_id = await self._current_contract(session, provider)
            projection = RuntimeInfrastructureProfileProjection(
                profile=profile,
                compatibility=evaluate_runtime_profile_compatibility(
                    spec,
                    contract.profile_contracts if contract is not None else [],
                    provider_protocol_version=(
                        contract.protocol_version if contract is not None else None
                    ),
                ),
                capability_revision_id=revision_id,
            )
        if terminal_changed:
            publisher = self.terminal_policy_invalidation_publisher
            await publisher.publish_terminal_policy_invalidation(
                TerminalPolicySourceInvalidation(
                    scope=TerminalPolicySourceScope.INFRASTRUCTURE_PROFILE,
                    source_id=profile.id,
                    source_version=str(profile.version),
                )
            )
        return projection

    async def get_profile_deletion_impact(
        self,
        provider_logical_id: str,
        profile_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        offset: int,
        limit: int,
    ) -> RuntimeInfrastructureProfileDeletionImpactProjection:
        """Return fresh blocking and applied-only infrastructure Profile impact."""
        async with self.session_manager() as session:
            provider = await self._require_provider(session, provider_logical_id)
            self._validate_provider_kind(provider.kind, profile_kind)
            profile = await self.profile_repository.get_infrastructure_profile(
                session,
                profile_id=profile_id,
                for_update=False,
            )
            if profile is None or profile.provider_id != provider.id:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_not_found",
                    message="Runtime infrastructure Profile was not found.",
                )
            if profile.profile_kind is not profile_kind:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_kind_mismatch",
                    message="Profile kind does not match the requested API kind.",
                )
            impact = await (
                self.profile_repository.get_infrastructure_profile_deletion_impact(
                    session,
                    profile_id=profile.id,
                    offset=offset,
                    limit=limit,
                )
            )
            logger.info(
                "Projected infrastructure Profile deletion impact",
                extra={
                    "provider_id": provider.provider_id,
                    "infrastructure_profile_id": profile.id,
                    "infrastructure_profile_kind": profile.profile_kind.value,
                    "infrastructure_profile_version": profile.version,
                    "blocking_reference_count": impact.blocking_reference_count,
                    "applied_only_running_runtime_count": (
                        impact.applied_only_running_runtime_count
                    ),
                },
            )
            return RuntimeInfrastructureProfileDeletionImpactProjection(
                profile=profile,
                impact=impact,
            )

    async def delete_profile(
        self,
        provider_logical_id: str,
        profile_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        expected_version: int,
        actor_user_id: str,
    ) -> RuntimeInfrastructureProfileDeletion:
        """Permanently delete one exact unreferenced infrastructure Profile."""
        async with self.session_manager() as session:
            provider = await self._require_provider(session, provider_logical_id)
            self._validate_provider_kind(provider.kind, profile_kind)
            current = await self.profile_repository.get_infrastructure_profile(
                session,
                profile_id=profile_id,
                for_update=False,
            )
            if current is None or current.provider_id != provider.id:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_not_found",
                    message="Runtime infrastructure Profile was not found.",
                )
            if current.profile_kind is not profile_kind:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_kind_mismatch",
                    message="Profile kind does not match the requested API kind.",
                )
            try:
                outcome = await self.profile_repository.delete_infrastructure_profile(
                    session,
                    provider_id=provider.id,
                    profile_id=profile_id,
                    expected_version=expected_version,
                )
            except IntegrityError as error:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_delete_conflict",
                    message=(
                        "Runtime infrastructure Profile deletion conflicted "
                        "with a current reference."
                    ),
                ) from error
            if outcome.deletion is not None:
                logger.info(
                    "Deleted infrastructure Profile",
                    extra={
                        "provider_id": provider.provider_id,
                        "infrastructure_profile_id": profile_id,
                        "infrastructure_profile_kind": profile_kind.value,
                        "infrastructure_profile_version": expected_version,
                        "actor_user_id": actor_user_id,
                        "superseded_recreation_operation_count": (
                            outcome.deletion.superseded_recreation_operation_count
                        ),
                        "skipped_recreation_item_count": (
                            outcome.deletion.skipped_recreation_item_count
                        ),
                    },
                )
                return outcome.deletion
            if outcome.current_profile is None:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_not_found",
                    message="Runtime infrastructure Profile was not found.",
                )
            if outcome.current_profile.version != expected_version:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_version_conflict",
                    message="Runtime infrastructure Profile version is stale.",
                    current_profile=outcome.current_profile,
                )
            if outcome.blocking_reference_count:
                raise RuntimeProfileAdminUnavailable(
                    code="profile_referenced",
                    message=(
                        "Runtime infrastructure Profile is referenced by current "
                        "Workspace Runtime Profiles."
                    ),
                    current_profile=outcome.current_profile,
                    blocking_reference_count=outcome.blocking_reference_count,
                )
            raise AssertionError("Infrastructure Profile deletion returned no outcome.")

    async def get_workspace_profile_admin_detail(
        self,
        workspace_handle: str,
        profile_id: str,
    ) -> AdminWorkspaceRuntimeProfileDetailProjection:
        """Return one System-Admin-owned read-only Workspace Profile detail."""
        async with self.session_manager() as session:
            workspace_snapshot = await self.workspace_repository.get_with_id_by_handle(
                session, workspace_handle
            )
            if workspace_snapshot is None:
                raise RuntimeProfileAdminUnavailable(
                    code="workspace_profile_not_found",
                    message="Workspace Runtime Profile was not found.",
                )
            workspace_id, workspace = workspace_snapshot
            profile = await self.profile_repository.get_workspace_runtime_profile(
                session,
                workspace_id=workspace_id,
                profile_id=profile_id,
                for_update=False,
            )
            if profile is None:
                raise RuntimeProfileAdminUnavailable(
                    code="workspace_profile_not_found",
                    message="Workspace Runtime Profile was not found.",
                )
            infrastructure = await self.profile_repository.get_infrastructure_profile(
                session,
                profile_id=profile.infrastructure_profile_id,
                for_update=False,
            )
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=profile.provider_id,
                for_update=False,
            )
            if (
                infrastructure is None
                or infrastructure.provider_id != profile.provider_id
                or provider is None
            ):
                raise RuntimeProfileAdminUnavailable(
                    code="workspace_profile_not_found",
                    message="Workspace Runtime Profile was not found.",
                )
            usage = await self.profile_repository.get_workspace_runtime_profile_usage(
                session,
                profile_id=profile.id,
            )
            return AdminWorkspaceRuntimeProfileDetailProjection(
                workspace_id=workspace_id,
                workspace=workspace,
                profile=profile,
                infrastructure_profile=infrastructure,
                provider=provider,
                usage=usage,
            )

    async def _require_provider(
        self,
        session: AsyncSession,
        provider_logical_id: str,
    ) -> RuntimeProvider:
        provider = await self.provider_repository.get_by_provider_id(
            session,
            provider_logical_id=provider_logical_id,
            for_update=False,
        )
        if provider is None:
            raise RuntimeProfileAdminUnavailable(
                code="provider_not_found",
                message="Runtime Provider was not found.",
            )
        return provider

    async def _current_contract(
        self,
        session: AsyncSession,
        provider: RuntimeProvider,
    ) -> _CurrentContract:
        revision_id = provider.current_contract_revision_id
        if revision_id is None:
            return _CurrentContract(contract=None, revision_id=None)
        revision = await self.policy_repository.get_contract_by_id(
            session,
            contract_revision_id=revision_id,
            for_update=False,
        )
        if revision is None or revision.provider_id != provider.id:
            return _CurrentContract(contract=None, revision_id=revision_id)
        try:
            return _CurrentContract(
                contract=RuntimeProviderCapabilityContract.model_validate(
                    revision.contract
                ),
                revision_id=revision.id,
            )
        except ValidationError:
            return _CurrentContract(contract=None, revision_id=revision.id)

    @staticmethod
    def _compatibility(
        profile: RuntimeInfrastructureProfile,
        contract: RuntimeProviderCapabilityContract | None,
    ) -> RuntimeProfileCompatibility:
        try:
            spec = parse_runtime_infrastructure_profile_spec(profile.spec)
        except ValidationError:
            return RuntimeProfileCompatibility(
                compatible=False,
                reason_code="profile_document_invalid",
                missing_capabilities=(),
                incompatible_constraints=(),
            )
        return evaluate_runtime_profile_compatibility(
            spec,
            contract.profile_contracts if contract is not None else [],
            provider_protocol_version=(
                contract.protocol_version if contract is not None else None
            ),
        )

    @staticmethod
    def _validate_provider_kind(
        provider_kind: RuntimeProviderKind,
        profile_kind: RuntimeInfrastructureProfileKind,
    ) -> None:
        expected = {
            RuntimeProviderKind.KUBERNETES: (
                RuntimeInfrastructureProfileKind.KUBERNETES_POD
            ),
            RuntimeProviderKind.DOCKER: (
                RuntimeInfrastructureProfileKind.DOCKER_CONTAINER
            ),
        }.get(provider_kind)
        if expected is not profile_kind:
            raise RuntimeProfileAdminUnavailable(
                code="profile_kind_mismatch",
                message="Profile kind does not match the owning Provider kind.",
            )


def _infrastructure_terminal_only_change(
    current: RuntimeInfrastructureProfile,
    replacement: RuntimeInfrastructureProfileReplace,
) -> bool:
    """Return whether only the non-physical Terminal policy flag changed."""
    return (
        current.terminal_enabled != replacement.terminal_enabled
        and current.display_name == replacement.display_name
        and current.description == replacement.description
        and current.lifecycle is replacement.lifecycle
        and current.contract_family == replacement.contract_family
        and current.schema_version == replacement.schema_version
        and current.spec == replacement.spec
        and current.required_capabilities == replacement.required_capabilities
        and current.digest == replacement.digest
    )
