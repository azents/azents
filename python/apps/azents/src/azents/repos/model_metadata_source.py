"""Current source authority, exact per-model rows and narrow context queries."""

import datetime
import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from azents.core.model_catalog_identity import CatalogIdentityError, catalog_source_keys
from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CATALOG_SOURCE_SCHEMA_VERSION,
    CatalogSourceModel,
    CatalogSourcePayload,
)
from azents.core.model_metadata_collection_data import (
    CurrentSourceModel,
    FetchedModelMetadataSource,
)
from azents.core.model_pricing import ModelPricingDefinition
from azents.rdb.models.model_metadata_source import (
    RDBModelMetadataSource,
    RDBModelMetadataSourceModel,
)
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.llm_catalog.data import LLMCatalogSyncStatus
from azents.repos.model_catalog_sync_state import (
    current_sync_status,
    fail_sync,
    start_sync,
    succeed_sync,
)
from azents.repos.model_metadata_source_data import (
    CapturedContextSource,
    ContextModelMetadata,
    ContextModelRequest,
    ModelMetadataSource,
    SourceModelExpectation,
    SourceProjectionMetadata,
)

_ROW_BATCH_SIZE = 250


class ModelMetadataSourceRepository:
    """Persist only current normalized facts; publication callers own transactions."""

    async def ensure_authority(
        self, session: WriteSession, *, source_key: str
    ) -> RDBModelMetadataSource:
        if source_key != CATALOG_SOURCE_KEY:
            raise ValueError("Only the current data-only source can own publication.")
        result = await session.write_session.execute(
            insert(RDBModelMetadataSource)
            .values(
                source_key=source_key,
                source_kind=CATALOG_SOURCE_KIND,
                source_schema_version=CATALOG_SOURCE_SCHEMA_VERSION,
            )
            .on_conflict_do_nothing(index_elements=["source_key"])
            .returning(RDBModelMetadataSource)
        )
        owner = result.scalar_one_or_none()
        if owner is None:
            owner = await session.write_session.get(RDBModelMetadataSource, source_key)
        if owner is None:
            raise RuntimeError("Current source authority upsert failed.")
        return owner

    async def lock_authority(
        self, session: WriteSession, *, source_key: str, shared: bool = False
    ) -> RDBModelMetadataSource | None:
        result = await session.write_session.execute(
            sa.select(RDBModelMetadataSource)
            .where(RDBModelMetadataSource.source_key == source_key)
            .with_for_update(read=shared)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def begin_sync(
        self, session: WriteSession, *, source_key: str, started_at: datetime.datetime
    ) -> str:
        await self.ensure_authority(session, source_key=source_key)
        owner = await self.lock_authority(session, source_key=source_key)
        if owner is None:
            raise RuntimeError("Current source authority was not found.")
        token = start_sync(
            owner, work_token=None, started_at=started_at, diagnostics=None
        )
        await session.write_session.flush()
        return token

    async def get_current(
        self, session: ReadSession, *, source_key: str
    ) -> ModelMetadataSource | None:
        """Observe provenance and complete current rows in one ordinary statement."""
        result = await session.read_session.execute(
            sa.select(RDBModelMetadataSource, RDBModelMetadataSourceModel)
            .outerjoin(
                RDBModelMetadataSourceModel,
                RDBModelMetadataSourceModel.source_key
                == RDBModelMetadataSource.source_key,
            )
            .where(RDBModelMetadataSource.source_key == source_key)
            .order_by(
                RDBModelMetadataSourceModel.provider,
                RDBModelMetadataSourceModel.source_model_key,
            )
            .execution_options(populate_existing=True)
        )
        rows = result.all()
        if not rows or rows[0][0].last_success_at is None:
            return None
        owner = rows[0][0]
        self._validate_owner(owner)
        if owner.source_url is None or owner.producer_name is None:
            raise ValueError("Published source provenance is incomplete.")
        models = tuple(self._build_model(row) for _, row in rows if row is not None)
        payload = CatalogSourcePayload(
            schema_version=CATALOG_SOURCE_SCHEMA_VERSION,
            interpreter_version="1",
            models=tuple(row.model for row in models),
        )
        if (
            payload.model_count != owner.model_count
            or payload.provider_count != owner.provider_count
        ):
            raise ValueError("Current source counts and model facts disagree.")
        return ModelMetadataSource(
            source_key=owner.source_key,
            source_kind=owner.source_kind,
            source_schema_version=owner.source_schema_version,
            source_url=owner.source_url,
            producer_name=owner.producer_name,
            producer_version=owner.producer_version,
            provider_count=owner.provider_count,
            model_count=owner.model_count,
            collected_at=owner.last_success_at,
            payload=payload,
            models=models,
        )

    async def get_projection_metadata(
        self, session: ReadSession, *, source_key: str
    ) -> SourceProjectionMetadata | None:
        owner = await session.read_session.scalar(
            sa.select(RDBModelMetadataSource)
            .where(RDBModelMetadataSource.source_key == source_key)
            .execution_options(populate_existing=True)
        )
        if owner is None or owner.last_success_at is None:
            return None
        self._validate_owner(owner)
        return SourceProjectionMetadata(
            source_key=owner.source_key,
            source_kind=owner.source_kind,
            collected_at=owner.last_success_at,
        )

    async def get_models(
        self, session: ReadSession, *, source_key: str, keys: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], CurrentSourceModel]:
        """Read only exact adopted namespace/key pairs, including missing keys."""
        if not keys:
            return {}
        result = await session.read_session.execute(
            sa.select(RDBModelMetadataSourceModel)
            .where(
                RDBModelMetadataSourceModel.source_key == source_key,
                sa.tuple_(
                    RDBModelMetadataSourceModel.provider,
                    RDBModelMetadataSourceModel.source_model_key,
                ).in_(set(keys)),
            )
            .execution_options(populate_existing=True)
        )
        return {
            (row.provider, row.source_model_key): self._build_model(row)
            for row in result.scalars()
        }

    async def projection_inputs_match(
        self,
        session: WriteSession,
        *,
        expected_metadata: SourceProjectionMetadata | None,
        expectations: Sequence[SourceModelExpectation],
    ) -> bool:
        """Compare relevant values/presence, never work tokens or dataset identities."""
        await self.lock_authority(session, source_key=CATALOG_SOURCE_KEY, shared=True)
        metadata = await self.get_projection_metadata(
            session, source_key=CATALOG_SOURCE_KEY
        )
        if metadata != expected_metadata:
            return False
        expected_by_key: dict[tuple[str, str], CurrentSourceModel | None] = {}
        for expected in expectations:
            key = (expected.provider, expected.source_model_key)
            if key in expected_by_key and expected_by_key[key] != expected.current:
                raise ValueError(
                    "Conflicting preparation inputs for an exact source key."
                )
            expected_by_key[key] = expected.current
        actual = await self.get_models(
            session, source_key=CATALOG_SOURCE_KEY, keys=tuple(expected_by_key)
        )
        return all(actual.get(key) == value for key, value in expected_by_key.items())

    async def replace_current(
        self,
        session: WriteSession,
        *,
        owner: RDBModelMetadataSource,
        work_token: str,
        fetched: FetchedModelMetadataSource,
        finished_at: datetime.datetime,
        diagnostics: dict[str, object],
    ) -> None:
        """Atomically overwrite incoming exact keys and remove missing current keys."""
        self._validate_owner(owner)
        if (
            fetched.source_kind != CATALOG_SOURCE_KIND
            or fetched.source_schema_version != CATALOG_SOURCE_SCHEMA_VERSION
        ):
            raise ValueError("Source collection uses an incompatible contract.")
        if (
            tuple(row.model for row in fetched.models) != fetched.payload.models
            or fetched.model_count != fetched.payload.model_count
            or fetched.provider_count != fetched.payload.provider_count
        ):
            raise ValueError("Prepared source rows and validated collection disagree.")
        keys: set[tuple[str, str]] = set()
        for row in fetched.models:
            key = (row.model.provider, row.model.source_key)
            if (
                key in keys
                or row.collected_at != fetched.collected_at
                or row.pricing.collected_at != fetched.collected_at
                or row.pricing.source_key != owner.source_key
                or row.pricing.source_model_key != row.model.source_key
            ):
                raise ValueError(
                    "Prepared source identity or pricing provenance disagrees."
                )
            keys.add(key)
        existing_result = await session.write_session.execute(
            sa.select(
                RDBModelMetadataSourceModel.provider,
                RDBModelMetadataSourceModel.source_model_key,
            )
            .where(RDBModelMetadataSourceModel.source_key == owner.source_key)
            .with_for_update()
        )
        obsolete = sorted(
            {(row.provider, row.source_model_key) for row in existing_result} - keys
        )
        for start in range(0, len(fetched.models), _ROW_BATCH_SIZE):
            rows = fetched.models[start : start + _ROW_BATCH_SIZE]
            statement = insert(RDBModelMetadataSourceModel).values(
                [
                    {
                        "source_key": owner.source_key,
                        "provider": row.model.provider,
                        "source_model_key": row.model.source_key,
                        "model_data": row.model.model_dump(mode="json"),
                        "pricing": row.pricing.model_dump(mode="json"),
                        "collected_at": row.collected_at,
                    }
                    for row in rows
                ]
            )
            await session.write_session.execute(
                statement.on_conflict_do_update(
                    index_elements=["source_key", "provider", "source_model_key"],
                    set_={
                        "model_data": statement.excluded.model_data,
                        "pricing": statement.excluded.pricing,
                        "collected_at": statement.excluded.collected_at,
                    },
                )
            )
        for start in range(0, len(obsolete), _ROW_BATCH_SIZE):
            await session.write_session.execute(
                sa.delete(RDBModelMetadataSourceModel).where(
                    RDBModelMetadataSourceModel.source_key == owner.source_key,
                    sa.tuple_(
                        RDBModelMetadataSourceModel.provider,
                        RDBModelMetadataSourceModel.source_model_key,
                    ).in_(obsolete[start : start + _ROW_BATCH_SIZE]),
                )
            )
        owner.source_url = fetched.source_url
        owner.producer_name = fetched.producer_name
        owner.producer_version = fetched.producer_version
        owner.provider_count = fetched.provider_count
        owner.model_count = fetched.model_count
        owner.last_success_at = fetched.collected_at
        succeed_sync(
            owner,
            work_token=work_token,
            finished_at=finished_at,
            fetched_count=fetched.model_count,
            matched_count=fetched.model_count,
            skipped_count=0,
            hidden_count=0,
            diagnostics=diagnostics,
        )
        await session.write_session.flush()

    async def fail_sync(
        self,
        session: WriteSession,
        *,
        source_key: str,
        work_token: str,
        finished_at: datetime.datetime,
        failure_code: str,
        failure_message: str,
        action_hint: str | None,
        diagnostics: dict[str, object],
    ) -> bool:
        owner = await self.lock_authority(session, source_key=source_key)
        if owner is None:
            return False
        changed = fail_sync(
            owner,
            work_token=work_token,
            finished_at=finished_at,
            failure_code=failure_code,
            failure_message=failure_message,
            action_hint=action_hint,
            diagnostics=diagnostics,
        )
        await session.write_session.flush()
        return changed

    async def get_sync_status(
        self, session: ReadSession, *, source_key: str
    ) -> LLMCatalogSyncStatus | None:
        owner = await session.read_session.scalar(
            sa.select(RDBModelMetadataSource)
            .where(RDBModelMetadataSource.source_key == source_key)
            .execution_options(populate_existing=True)
        )
        return None if owner is None else current_sync_status(owner)

    async def capture_for_context(
        self, session: ReadSession, *, requests: Sequence[ContextModelRequest]
    ) -> CapturedContextSource:
        """Project only requested maxima; never load model payloads or price rules."""
        if not requests:
            return CapturedContextSource(models=())
        request_keys = {
            request: catalog_source_keys(
                provider=request.provider, model_identifier=request.model_identifier
            )
            for request in requests
        }
        keys = {
            (key.provider, key.source_model_key)
            for values in request_keys.values()
            for key in values
        }
        result = await session.read_session.execute(
            sa.select(
                RDBModelMetadataSource,
                RDBModelMetadataSourceModel.provider,
                RDBModelMetadataSourceModel.source_model_key,
                sa.cast(
                    RDBModelMetadataSourceModel.model_data["facts"]["max_input_tokens"][
                        "value"
                    ].astext,
                    sa.BigInteger,
                ).label("maximum"),
            )
            .outerjoin(
                RDBModelMetadataSourceModel,
                sa.and_(
                    RDBModelMetadataSourceModel.source_key
                    == RDBModelMetadataSource.source_key,
                    sa.tuple_(
                        RDBModelMetadataSourceModel.provider,
                        RDBModelMetadataSourceModel.source_model_key,
                    ).in_(keys),
                ),
            )
            .where(RDBModelMetadataSource.source_key == CATALOG_SOURCE_KEY)
            .execution_options(populate_existing=True)
        )
        rows = result.all()
        maxima: dict[tuple[str, str], int | None] = {}
        if rows and rows[0][0].last_success_at is not None:
            self._validate_owner(rows[0][0])
            maxima = {
                (row.provider, row.source_model_key): row.maximum
                for row in rows
                if row.provider is not None
            }
        models: list[ContextModelMetadata] = []
        for request in requests:
            found = [
                maxima[(key.provider, key.source_model_key)]
                for key in request_keys[request]
                if (key.provider, key.source_model_key) in maxima
            ]
            if len(found) > 1:
                raise CatalogIdentityError("Conflicting canonical catalog identities.")
            maximum = found[0] if found else None
            models.append(
                ContextModelMetadata(
                    provider=request.provider,
                    model_identifier=request.model_identifier,
                    max_input_tokens=maximum
                    if maximum is not None and maximum > 0
                    else None,
                )
            )
        return CapturedContextSource(models=tuple(models))

    @staticmethod
    def _validate_owner(owner: RDBModelMetadataSource) -> None:
        if (
            owner.source_key != CATALOG_SOURCE_KEY
            or owner.source_kind != CATALOG_SOURCE_KIND
            or owner.source_schema_version != CATALOG_SOURCE_SCHEMA_VERSION
        ):
            raise ValueError("Current source owner uses an incompatible contract.")

    @staticmethod
    def _build_model(row: RDBModelMetadataSourceModel) -> CurrentSourceModel:
        model = CatalogSourceModel.model_validate_json(
            json.dumps(row.model_data, allow_nan=False)
        )
        pricing = ModelPricingDefinition.model_validate(row.pricing)
        if (
            model.provider != row.provider
            or model.source_key != row.source_model_key
            or pricing.source_key != row.source_key
            or pricing.source_model_key != row.source_model_key
            or pricing.collected_at != row.collected_at
        ):
            raise ValueError("Current source facts and pricing provenance disagree.")
        return CurrentSourceModel(
            model=model, pricing=pricing, collected_at=row.collected_at
        )
