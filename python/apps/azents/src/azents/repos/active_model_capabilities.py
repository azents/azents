"""DB-only exact local declarations for active reads and new operation preparation."""

import copy
import dataclasses
from collections.abc import Mapping, Sequence
from typing import Annotated

from fastapi import Depends

from azents.core.active_model_capabilities import (
    ActiveModelMetadataUnavailable,
    CapturedStoredChoice,
    ConfiguredModelIdentity,
)
from azents.core.enums import LLMCatalogPurpose, LLMModelDeveloper
from azents.core.model_catalog_identity import catalog_source_keys
from azents.core.model_catalog_source import CATALOG_SOURCE_KEY
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.active_model_capabilities_data import (
    ActiveReadScope,
    CapturedActiveChoiceInputs,
    CapturedCatalogChoice,
    CapturedIntegrationScope,
)
from azents.repos.llm_catalog import CatalogEntryWithCatalog, LLMCatalogRepository
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import SourceModelExpectation


@dataclasses.dataclass(frozen=True)
class ActiveModelCapabilitiesRepository:
    """Capture local inputs without provider discovery or configuration writes."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
    source_repository: Annotated[
        ModelMetadataSourceRepository, Depends(ModelMetadataSourceRepository)
    ]

    async def prepare_read_scope_in_session(
        self,
        session: ReadSession,
        *,
        workspace_id: str,
        integration_ids: Sequence[str],
    ) -> ActiveReadScope:
        """Read scoped integration and optional source descriptions without locks."""
        scopes: list[CapturedIntegrationScope] = []
        for integration_id in sorted(set(integration_ids)):
            integration = await self.catalog_repository.read_integration(
                session,
                integration_id=integration_id,
                workspace_id=workspace_id,
            )
            scopes.append(
                CapturedIntegrationScope(
                    integration_id=integration_id,
                    provider=integration.provider if integration is not None else None,
                    configuration_version=integration.catalog_configuration_version
                    if integration is not None
                    else None,
                )
            )
        metadata = (
            await self.source_repository.get_projection_metadata(
                session, source_key=CATALOG_SOURCE_KEY
            )
            if integration_ids
            else None
        )
        return ActiveReadScope(
            workspace_id=workspace_id,
            integrations=tuple(scopes),
            source_metadata=metadata,
        )

    async def capture_exact_choices(
        self, *, workspace_id: str, identities: Sequence[ConfiguredModelIdentity]
    ) -> CapturedActiveChoiceInputs:
        async with self.session_manager() as session:
            return await self.capture_exact_choices_in_session(
                session, workspace_id=workspace_id, identities=identities
            )

    async def capture_exact_choices_in_session(
        self,
        session: ReadSession,
        *,
        workspace_id: str,
        identities: Sequence[ConfiguredModelIdentity],
    ) -> CapturedActiveChoiceInputs:
        """Capture configured identities without authorizing a final mutation."""
        ordered = tuple(dict.fromkeys(identities))
        scope = await self.prepare_read_scope_in_session(
            session,
            workspace_id=workspace_id,
            integration_ids=tuple(identity.integration_id for identity in ordered),
        )
        integrations = {item.integration_id: item for item in scope.integrations}
        authorized = tuple(
            identity
            for identity in ordered
            if integrations[identity.integration_id].provider == identity.provider
        )
        entries = (
            await self.catalog_repository.get_selectable_entries_for_identities(
                session, workspace_id=workspace_id, identities=authorized
            )
            if authorized
            else {}
        )
        return await self._capture_entries(
            session, scope=scope, identities=ordered, entries=entries
        )

    async def capture_current_entries_in_session(
        self,
        session: ReadSession,
        *,
        scope: ActiveReadScope,
        integration_id: str,
        entries: Sequence[CatalogEntryWithCatalog],
    ) -> CapturedActiveChoiceInputs:
        """Reuse observed page rows for descriptive capability compilation."""
        identities = tuple(
            ConfiguredModelIdentity(
                integration_id=integration_id,
                provider=result.entry.provider,
                model_identifier=result.entry.provider_model_identifier,
            )
            for result in entries
        )
        return await self._capture_entries(
            session,
            scope=scope,
            identities=identities,
            entries=dict(zip(identities, entries, strict=True)),
        )

    async def _capture_entries(
        self,
        session: ReadSession,
        *,
        scope: ActiveReadScope,
        identities: Sequence[ConfiguredModelIdentity],
        entries: Mapping[ConfiguredModelIdentity, CatalogEntryWithCatalog],
    ) -> CapturedActiveChoiceInputs:
        integrations = {item.integration_id: item for item in scope.integrations}
        authorized = tuple(
            identity
            for identity in identities
            if identity.integration_id in integrations
            and integrations[identity.integration_id].provider == identity.provider
        )
        keys = tuple(
            dict.fromkeys(
                (key.provider, key.source_model_key)
                for identity in authorized
                for key in catalog_source_keys(
                    provider=identity.provider,
                    model_identifier=identity.model_identifier,
                )
            )
        )
        models = (
            await self.source_repository.get_models(
                session, source_key=CATALOG_SOURCE_KEY, keys=keys
            )
            if keys and scope.source_metadata is not None
            else {}
        )
        expectations = tuple(
            SourceModelExpectation(
                provider=provider,
                source_model_key=key,
                current=models.get((provider, key)),
            )
            for provider, key in keys
        )
        catalog_choices = tuple(
            self._catalog_choice(
                identity=identity,
                integration=integrations.get(identity.integration_id),
                result=entries.get(identity),
            )
            for identity in identities
        )
        choices: list[CapturedStoredChoice | ActiveModelMetadataUnavailable] = []
        for catalog in catalog_choices:
            identity = catalog.identity
            if catalog.failure is not None:
                choices.append(catalog.failure)
                continue
            assert catalog.catalog_id is not None
            applicable = catalog_source_keys(
                provider=identity.provider, model_identifier=identity.model_identifier
            )
            choices.append(
                CapturedStoredChoice(
                    identity=identity,
                    source_metadata=catalog.source_metadata,
                    source_models=tuple(
                        models[(key.provider, key.source_model_key)].model
                        for key in applicable
                        if (key.provider, key.source_model_key) in models
                    ),
                    supported_execution_options=catalog.supported_execution_options,
                    model_developer=catalog.model_developer,
                    catalog_id=catalog.catalog_id,
                )
            )
        return CapturedActiveChoiceInputs(
            workspace_id=scope.workspace_id,
            choices=tuple(choices),
            catalog_choices=catalog_choices,
            source_metadata=scope.source_metadata,
            source_expectations=expectations,
        )

    @staticmethod
    def _catalog_choice(
        *,
        identity: ConfiguredModelIdentity,
        integration: CapturedIntegrationScope | None,
        result: CatalogEntryWithCatalog | None,
    ) -> CapturedCatalogChoice:
        if integration is None or integration.provider is None:
            return CapturedCatalogChoice(
                identity,
                None,
                None,
                None,
                (),
                None,
                ActiveModelMetadataUnavailable(
                    identity, "integration_scope_unavailable"
                ),
            )
        if integration.provider != identity.provider:
            return CapturedCatalogChoice(
                identity,
                None,
                integration.configuration_version,
                None,
                (),
                None,
                ActiveModelMetadataUnavailable(identity, "provider_scope_mismatch"),
            )
        if result is None:
            return CapturedCatalogChoice(
                identity,
                None,
                integration.configuration_version,
                None,
                (),
                None,
                ActiveModelMetadataUnavailable(identity, "exact_entry_unavailable"),
            )
        entry = result.entry
        if entry.provider != identity.provider:
            return CapturedCatalogChoice(
                identity,
                result.catalog.id,
                integration.configuration_version,
                None,
                (),
                None,
                ActiveModelMetadataUnavailable(identity, "provider_scope_mismatch"),
            )
        developer = next(
            (value for value in LLMModelDeveloper if value.value == entry.publisher),
            None,
        )
        metadata = entry.source_metadata
        consumed = (
            None
            if metadata is None
            else copy.deepcopy(
                {
                    key: metadata[key]
                    for key in (
                        "provider_metadata",
                        "capability_evidence",
                        "provider_listing_source",
                    )
                    if key in metadata
                }
            )
        )
        try:
            options = tuple(
                ModelExecutionOptionId(option)
                for option in entry.supported_execution_options
            )
        except ValueError:
            return CapturedCatalogChoice(
                identity,
                result.catalog.id,
                integration.configuration_version,
                consumed,
                (),
                developer,
                ActiveModelMetadataUnavailable(identity, "stored_declarations_invalid"),
            )
        return CapturedCatalogChoice(
            identity=identity,
            catalog_id=result.catalog.id,
            configuration_version=integration.configuration_version,
            source_metadata=consumed,
            supported_execution_options=options,
            model_developer=developer,
            failure=None,
        )

    async def guard_acceptance_in_session(
        self,
        session: WriteSession,
        *,
        captured: CapturedActiveChoiceInputs,
    ) -> None:
        """Retain integration → source → catalog exclusion through owner commit."""
        identities = tuple(choice.identity for choice in captured.catalog_choices)
        for integration_id in sorted({i.integration_id for i in identities}):
            await self.catalog_repository.lock_integration(
                session,
                integration_id=integration_id,
                workspace_id=captured.workspace_id,
                shared=True,
            )
        if identities:
            await self.source_repository.lock_authority(
                session, source_key=CATALOG_SOURCE_KEY, shared=True
            )
        owners = []
        for identity in identities:
            owner = await self.catalog_repository._read_owner_for_integration(
                session,
                integration_id=identity.integration_id,
                workspace_id=captured.workspace_id,
                purpose=LLMCatalogPurpose.CONVERSATION,
                require_enabled=False,
            )
            if owner is not None:
                owners.append(owner.id)
        for catalog_id in sorted(set(owners)):
            await self.catalog_repository.lock_catalog(
                session, catalog_id=catalog_id, shared=True
            )

    async def inputs_match_in_session(
        self, session: WriteSession, *, captured: CapturedActiveChoiceInputs
    ) -> bool:
        """Recheck current compiler input values and presence under the same locks."""
        await self.guard_acceptance_in_session(session, captured=captured)
        current = await self.capture_exact_choices_in_session(
            session,
            workspace_id=captured.workspace_id,
            identities=tuple(choice.identity for choice in captured.catalog_choices),
        )
        return (
            current.catalog_choices == captured.catalog_choices
            and current.source_metadata == captured.source_metadata
            and current.source_expectations == captured.source_expectations
        )
