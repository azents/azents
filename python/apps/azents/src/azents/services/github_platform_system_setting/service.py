"""Platform GitHub App System Settings domain service."""

import dataclasses
from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.github_system_setting import (
    PlatformGitHubAppConfig,
    PlatformGitHubAppEffective,
    PlatformGitHubAppIncomplete,
    PlatformGitHubAppSecrets,
)
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingFieldSource,
    SystemSettingHealthStatus,
    SystemSettingSection,
    SystemSettingValidationStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.github_platform_system_setting.data import PlatformGitHubAppImpact
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)
from azents.services.system_setting.data import (
    SystemSettingActivated,
    SystemSettingCandidateValidationResult,
    SystemSettingCandidateValidationSnapshot,
    SystemSettingHealthResult,
    SystemSettingMutation,
    SystemSettingMutationResult,
    SystemSettingState,
)
from azents.services.system_setting.service import SystemSettingsService

from .binding import PlatformGitHubAppBindingService
from .client import PlatformGitHubAppValidationClient
from .data import (
    PlatformGitHubAppAuditPage,
    PlatformGitHubAppBindingState,
    PlatformGitHubAppCandidateState,
    PlatformGitHubAppDetail,
    PlatformGitHubAppEffectiveStatus,
    PlatformGitHubAppFieldState,
    PlatformGitHubAppHealthState,
    PlatformGitHubAppInventoryItem,
)


async def get_platform_github_validation_http_client() -> AsyncIterator[
    httpx.AsyncClient
]:
    """Yield the bounded GitHub validation HTTP client."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def get_platform_github_validation_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_platform_github_validation_http_client),
    ],
    config: Annotated[Config, Depends(get_config)],
) -> PlatformGitHubAppValidationClient:
    """Return the Platform GitHub App external validation client."""
    base_url = config.testenv_github_platform_validation_base_url
    if base_url is None:
        app_url = "https://api.github.com/app"
        oauth_token_url = "https://github.com/login/oauth/access_token"
    else:
        normalized_base_url = base_url.rstrip("/")
        app_url = f"{normalized_base_url}/app"
        oauth_token_url = f"{normalized_base_url}/login/oauth/access_token"
    return PlatformGitHubAppValidationClient(
        http_client,
        app_url=app_url,
        oauth_token_url=oauth_token_url,
    )


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppSystemSettingService:
    """Manage and project the Platform GitHub App Section."""

    system_settings: Annotated[SystemSettingsService, Depends()]
    validation_client: Annotated[
        PlatformGitHubAppValidationClient,
        Depends(get_platform_github_validation_client),
    ]
    impact_repository: Annotated[
        PlatformGitHubAppSystemSettingRepository,
        Depends(PlatformGitHubAppSystemSettingRepository),
    ]
    binding_service: Annotated[PlatformGitHubAppBindingService, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]

    async def list_inventory(self) -> list[PlatformGitHubAppInventoryItem]:
        """Return the registry-driven inventory for the first compiled Section."""
        detail = await self.get_detail()
        return [
            PlatformGitHubAppInventoryItem(
                section=detail.section,
                display_name="Platform GitHub App",
                effective_status=detail.effective_status,
                admin_version=detail.admin_version,
                environment_managed_field_count=sum(
                    field.source is SystemSettingFieldSource.ENVIRONMENT
                    for field in detail.fields
                ),
                candidate_status=(
                    detail.candidate.validation_status
                    if detail.candidate is not None
                    else None
                ),
            )
        ]

    async def get_detail(self) -> PlatformGitHubAppDetail:
        """Return the redacted current, candidate, and health projection."""
        state = await self.system_settings.get_state(
            SystemSettingSection.PLATFORM_GITHUB_APP
        )
        binding_impact = await self._resolve_current_binding_impact(state.resolved)
        return self._project_detail(state, binding_impact)

    async def patch(
        self,
        mutation: SystemSettingMutation,
    ) -> SystemSettingMutationResult:
        """Create a candidate and immediately run external validation."""
        result = await self.system_settings.mutate(mutation)
        if isinstance(result, SystemSettingActivated):
            return result
        return await self.system_settings.validate_candidate(
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
            candidate_id=result.candidate.id,
            validator=self._validate_candidate,
        )

    async def retry_candidate_validation(self) -> SystemSettingMutationResult:
        """Retry external validation for the current candidate."""
        return await self.system_settings.validate_candidate(
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
            candidate_id=None,
            validator=self._validate_candidate,
        )

    async def confirm_candidate(
        self,
        *,
        candidate_id: str,
        expected_version: int,
        confirmation_action: str,
        actor_user_id: str | None,
    ) -> SystemSettingActivated:
        """Recheck redacted impact and activate the candidate."""

        async def impact_resolver(
            session: AsyncSession,
            current: ResolvedSystemSetting,
            candidate: ResolvedSystemSetting,
        ) -> dict[str, Any] | None:
            return await self._resolve_impact(session, current, candidate)

        async def confirmation_handler(
            session: AsyncSession,
            action: str,
            candidate: ResolvedSystemSetting,
            impact: dict[str, Any] | None,
        ) -> None:
            raw_actions = impact.get("confirmation_actions") if impact else None
            allowed_actions = (
                tuple(item for item in raw_actions if isinstance(item, str))
                if isinstance(raw_actions, (list, tuple))
                else ()
            )
            if action not in allowed_actions:
                raise ValueError("Unsupported Platform GitHub App confirmation action.")

        return await self.system_settings.confirm_candidate(
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
            candidate_id=candidate_id,
            expected_version=expected_version,
            confirmation_action=confirmation_action,
            actor_user_id=actor_user_id,
            impact_resolver=impact_resolver,
            confirmation_handler=confirmation_handler,
        )

    async def cancel_candidate(
        self,
        *,
        candidate_id: str,
        actor_user_id: str | None,
    ) -> None:
        """Cancel and erase the pending candidate."""
        await self.system_settings.cancel_candidate(
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
            candidate_id=candidate_id,
            actor_user_id=actor_user_id,
        )

    async def check_health(
        self,
        *,
        actor_user_id: str | None,
    ) -> PlatformGitHubAppDetail:
        """Validate the current effective configuration without mutating it."""
        current = await self.system_settings.resolve(
            SystemSettingSection.PLATFORM_GITHUB_APP
        )
        try:
            effective = self._require_complete(current)
        except PlatformGitHubAppIncomplete as error:
            health_result = SystemSettingHealthResult(
                status=SystemSettingHealthStatus.INVALID,
                code="platform_github_app_incomplete",
                message="Platform GitHub App configuration is incomplete.",
                action_hint="Configure all required Platform GitHub App fields.",
                metadata={"missing_fields": list(error.missing_fields)},
            )
        except ValidationError:
            health_result = SystemSettingHealthResult(
                status=SystemSettingHealthStatus.INVALID,
                code="platform_github_app_invalid",
                message="Platform GitHub App configuration is invalid.",
                action_hint="Verify the App ID, Client ID, and private key.",
                metadata=None,
            )
        else:
            validation = await self.validation_client.validate(effective)
            health_result = SystemSettingHealthResult(
                status=(
                    SystemSettingHealthStatus.HEALTHY
                    if validation.status is SystemSettingValidationStatus.VALID
                    else SystemSettingHealthStatus.INVALID
                    if validation.status is SystemSettingValidationStatus.INVALID
                    else SystemSettingHealthStatus.UNAVAILABLE
                ),
                code=validation.code,
                message=validation.message,
                action_hint=validation.action_hint,
                metadata=validation.metadata,
            )
        await self.system_settings.record_health(
            section=SystemSettingSection.PLATFORM_GITHUB_APP,
            expected_generation=current.effective_generation,
            result=health_result,
            actor_user_id=actor_user_id,
        )
        return await self.get_detail()

    async def list_audit_events(
        self,
        *,
        offset: int,
        limit: int,
    ) -> PlatformGitHubAppAuditPage:
        """Return metadata-only System Settings audit events."""
        async with self.session_manager() as session:
            page = await self.system_settings.repository.list_audit_events(
                session,
                section=None,
                offset=offset,
                limit=limit,
            )
        return PlatformGitHubAppAuditPage(items=page.items, total=page.total)

    async def _validate_candidate(
        self,
        snapshot: SystemSettingCandidateValidationSnapshot,
    ) -> SystemSettingCandidateValidationResult:
        try:
            effective = self._require_complete(snapshot.candidate_resolved)
        except PlatformGitHubAppIncomplete as error:
            return SystemSettingCandidateValidationResult(
                status=SystemSettingValidationStatus.INVALID,
                code="platform_github_app_incomplete",
                message="Platform GitHub App configuration is incomplete.",
                action_hint="Configure all required Platform GitHub App fields.",
                metadata={"missing_fields": list(error.missing_fields)},
                impact=None,
                confirmation_required=False,
            )
        except ValidationError:
            return SystemSettingCandidateValidationResult(
                status=SystemSettingValidationStatus.INVALID,
                code="platform_github_app_invalid",
                message="Platform GitHub App configuration is invalid.",
                action_hint="Verify the App ID, Client ID, and private key.",
                metadata=None,
                impact=None,
                confirmation_required=False,
            )
        validation = await self.validation_client.validate(effective)
        impact: dict[str, Any] | None = None
        confirmation_required = False
        if validation.status is SystemSettingValidationStatus.VALID:
            async with self.session_manager() as session:
                impact = await self._resolve_impact(
                    session,
                    snapshot.current_resolved,
                    snapshot.candidate_resolved,
                )
            confirmation_required = bool(
                impact is not None and impact.get("confirmation_required") is True
            )
        return SystemSettingCandidateValidationResult(
            status=validation.status,
            code=validation.code,
            message=validation.message,
            action_hint=validation.action_hint,
            metadata=validation.metadata,
            impact=impact,
            confirmation_required=confirmation_required,
        )

    async def _resolve_impact(
        self,
        session: AsyncSession,
        current: ResolvedSystemSetting,
        candidate: ResolvedSystemSetting,
    ) -> dict[str, Any] | None:
        current_config = self._config(current)
        candidate_config = self._config(candidate)
        app_id_changed = current_config.app_id != candidate_config.app_id
        if current_config.app_id is None:
            affected_user_count = 0
            affected_installation_count = 0
            affected_toolkit_ids: set[str] = set()
        else:
            installation_impact = await self.impact_repository.get_installation_impact(
                session,
                app_id=current_config.app_id,
            )
            toolkit_impact = await self.binding_service.inspect_toolkits_bound_to(
                session,
                app_id=current_config.app_id,
            )
            affected_user_count = installation_impact.affected_user_count
            affected_installation_count = (
                installation_impact.affected_installation_count
            )
            affected_toolkit_ids = set(toolkit_impact.affected_toolkit_ids)
        affected_agent_count = await self.impact_repository.count_agents_for_toolkits(
            session,
            toolkit_ids=affected_toolkit_ids,
        )
        has_current_bindings = affected_installation_count > 0 or bool(
            affected_toolkit_ids
        )
        confirmation_actions = (
            ("activate",)
            if current_config.app_id is not None
            and app_id_changed
            and has_current_bindings
            else ()
        )
        impact = PlatformGitHubAppImpact(
            app_id_changed=app_id_changed,
            affected_user_count=affected_user_count,
            affected_installation_count=affected_installation_count,
            affected_toolkit_count=len(affected_toolkit_ids),
            affected_agent_count=affected_agent_count,
            current_app_id_source=current.field_sources["app_id"].value,
            confirmation_actions=confirmation_actions,
        )
        metadata = impact.to_metadata()
        metadata["confirmation_required"] = impact.confirmation_required
        return metadata

    async def _resolve_current_binding_impact(
        self,
        resolved: ResolvedSystemSetting,
    ) -> PlatformGitHubAppBindingState | None:
        app_id = self._config(resolved).app_id
        if app_id is None:
            return None
        async with self.session_manager() as session:
            installation_impact = (
                await self.impact_repository.get_current_binding_installation_impact(
                    session,
                    effective_app_id=app_id,
                )
            )
            toolkit_impact = (
                await self.binding_service.inspect_toolkits_mismatched_with(
                    session,
                    effective_app_id=app_id,
                )
            )
            affected_toolkit_ids = set(toolkit_impact.affected_toolkit_ids)
            affected_agent_count = (
                await self.impact_repository.count_agents_for_toolkits(
                    session,
                    toolkit_ids=affected_toolkit_ids,
                )
            )
        return PlatformGitHubAppBindingState(
            affected_user_count=installation_impact.affected_user_count,
            affected_installation_count=(
                installation_impact.affected_installation_count
            ),
            affected_toolkit_count=len(affected_toolkit_ids),
            affected_agent_count=affected_agent_count,
        )

    @classmethod
    def _project_detail(
        cls,
        state: SystemSettingState,
        binding_impact: PlatformGitHubAppBindingState | None,
    ) -> PlatformGitHubAppDetail:
        config = cls._config(state.resolved)
        secrets = cls._secrets(state.resolved)
        current = state.current
        effective_values = {
            "app_id": config.app_id,
            "client_id": config.client_id,
            "private_key": secrets.private_key,
            "client_secret": secrets.client_secret,
        }
        environment_variables = {
            "app_id": "AZ_GITHUB_PLATFORM_APP_ID",
            "client_id": "AZ_GITHUB_PLATFORM_CLIENT_ID",
            "private_key": "AZ_GITHUB_PLATFORM_PRIVATE_KEY",
            "client_secret": "AZ_GITHUB_PLATFORM_CLIENT_SECRET",
        }
        fields = tuple(
            PlatformGitHubAppFieldState(
                name=name,
                secret=name in {"private_key", "client_secret"},
                value=(None if name in {"private_key", "client_secret"} else value),
                configured=value is not None,
                source=state.resolved.field_sources[name],
                environment_variable=environment_variables[name],
                fallback_configured=cls._fallback_configured(state, name),
                fallback_last_changed_at=(
                    current.updated_at
                    if current is not None and cls._fallback_configured(state, name)
                    else None
                ),
            )
            for name, value in effective_values.items()
        )
        configured_count = sum(value is not None for value in effective_values.values())
        if configured_count == 0:
            effective_status = PlatformGitHubAppEffectiveStatus.NOT_CONFIGURED
        elif configured_count < len(effective_values):
            effective_status = PlatformGitHubAppEffectiveStatus.INCOMPLETE
        else:
            try:
                cls._require_complete(state.resolved)
            except ValidationError:
                effective_status = PlatformGitHubAppEffectiveStatus.INVALID
            else:
                if (
                    state.health is not None
                    and state.health.status is SystemSettingHealthStatus.INVALID
                ):
                    effective_status = PlatformGitHubAppEffectiveStatus.INVALID
                elif (
                    state.health is not None
                    and state.health.status is SystemSettingHealthStatus.UNAVAILABLE
                ):
                    effective_status = PlatformGitHubAppEffectiveStatus.UNAVAILABLE
                else:
                    effective_status = PlatformGitHubAppEffectiveStatus.READY
        if (
            effective_status is PlatformGitHubAppEffectiveStatus.READY
            and binding_impact is not None
            and binding_impact.reconnect_required
        ):
            effective_status = PlatformGitHubAppEffectiveStatus.RECONNECT_REQUIRED
        candidate = (
            PlatformGitHubAppCandidateState(
                id=state.candidate.id,
                base_version=state.candidate.base_version,
                validation_status=state.candidate.validation_status,
                validation_code=state.candidate.validation_code,
                validation_message=state.candidate.validation_message,
                action_hint=state.candidate.action_hint,
                impact=state.candidate.impact,
                created_at=state.candidate.created_at,
                updated_at=state.candidate.updated_at,
                expires_at=state.candidate.expires_at,
            )
            if state.candidate is not None
            else None
        )
        health = (
            PlatformGitHubAppHealthState(
                status=state.health.status,
                code=state.health.code,
                message=state.health.message,
                action_hint=state.health.action_hint,
                metadata=state.health.metadata,
                checked_at=state.health.checked_at,
            )
            if state.health is not None
            else None
        )
        activation_current = (
            current is not None
            and current.validated_generation == state.resolved.effective_generation
        )
        app_slug = None
        if activation_current and current is not None and current.validation_metadata:
            raw_slug = current.validation_metadata.get("app_slug")
            app_slug = raw_slug if isinstance(raw_slug, str) else None
        return PlatformGitHubAppDetail(
            section=SystemSettingSection.PLATFORM_GITHUB_APP.value,
            schema_version=state.resolved.schema_version,
            admin_version=state.resolved.admin_version,
            effective_status=effective_status,
            fields=fields,
            candidate=candidate,
            health=health,
            binding_impact=binding_impact,
            activation_validation_status=(
                current.validation_status
                if activation_current and current is not None
                else None
            ),
            app_slug=app_slug,
        )

    @staticmethod
    def _fallback_configured(state: SystemSettingState, name: str) -> bool:
        current = state.current
        if current is None:
            return False
        if name in {"app_id", "client_id"}:
            return current.config.get(name) is not None
        metadata = current.secret_metadata.get(name)
        return isinstance(metadata, dict) and metadata.get("configured") is True

    @staticmethod
    def _config(resolved: ResolvedSystemSetting) -> PlatformGitHubAppConfig:
        if not isinstance(resolved.config, PlatformGitHubAppConfig):
            raise TypeError("Unexpected Platform GitHub App config model.")
        return resolved.config

    @staticmethod
    def _secrets(resolved: ResolvedSystemSetting) -> PlatformGitHubAppSecrets:
        if not isinstance(resolved.secrets, PlatformGitHubAppSecrets):
            raise TypeError("Unexpected Platform GitHub App secret model.")
        return resolved.secrets

    @classmethod
    def _require_complete(
        cls,
        resolved: ResolvedSystemSetting,
    ) -> PlatformGitHubAppEffective:
        return PlatformGitHubAppEffective.from_parts(
            cls._config(resolved),
            cls._secrets(resolved),
        )
