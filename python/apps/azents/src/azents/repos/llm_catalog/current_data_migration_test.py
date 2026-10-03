"""Disposable PostgreSQL regression coverage for current catalog and price cutover."""

import copy
import datetime
import json
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT
from azents.core.agent import SelectableModelOption
from azents.core.enums import LLMProvider
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelCapabilities, ModelContextWindow
from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CatalogSourcePayload,
    decode_catalog_source,
)
from azents.core.model_operation import (
    ModelOperationCandidateOutcomeReason,
    ModelOperationKind,
    build_model_operation,
    mark_current_candidate_active,
    mark_model_operation_succeeded,
)
from azents.core.model_pricing import ModelPricingDefinition, normalize_model_pricing
from azents.testing.model_selection import make_test_model_selection

from .data_source_cutover_test import _historical_source_hash

_PARENT = "1c42cc5ce89f"
_CUTOVER = "d9bff320245f"
_BEFORE_SOURCE_FENCES = "459a4285993c"
_SOURCE_TIME = datetime.datetime(2026, 10, 1, 6, 7, 8, tzinfo=datetime.UTC)
_SUCCESS_TIME = datetime.datetime(2026, 10, 1, 7, 8, 9, tzinfo=datetime.UTC)
_FAILURE_TIME = datetime.datetime(2026, 10, 2, 8, 9, 10, tzinfo=datetime.UTC)
_OLDER_TIME = datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)
_DIAGNOSTICS = {
    "retry_policy": {"automatic_retry_blocked": True},
    "fixture": "failed",
    "receipts": {"preserved": "retry-fact"},
}
_OBSOLETE_RECEIPTS = {
    "producer_version": "sha256:" + "a" * 64,
    "raw_document_hash": "old-raw-hash",
    "source_hash": "old-source-hash",
    "source_snapshot_id": "old-source-id",
    "projection_fingerprint": "old-fingerprint",
    "resolver_revision": "old-resolver",
}
_LEGACY_DIAGNOSTICS = {
    **_DIAGNOSTICS,
    "producer_version": "sha256:" + "a" * 64,
    "receipts": {**_DIAGNOSTICS["receipts"], **_OBSOLETE_RECEIPTS},
}
_OWNER_DIAGNOSTICS = {
    "publication": "current-success-fact",
    "producer_version": "sha256:reviewed-release-1",
    "source_schema_version": "1",
    "receipts": {"preserved": "publication-fact"},
}
_LEGACY_OWNER_DIAGNOSTICS = {
    **_OWNER_DIAGNOSTICS,
    "receipts": {**_OWNER_DIAGNOSTICS["receipts"], **_OBSOLETE_RECEIPTS},
}

# Historical SQL JSON remains opaque here; price assertions use the typed decoder.


def _id(number: int) -> str:
    return f"{number:032x}"


_WORKSPACE = _id(1)
_OTHER_WORKSPACE = _id(2)
_NATIVE = _id(10)
_NATIVE_TWO = _id(11)
_ACCOUNT_A = _id(12)
_ACCOUNT_B = _id(13)
_OAUTH = _id(14)
_CROSS_WORKSPACE = _id(15)
_SOURCE_CURRENT = _id(20)
_SOURCE_HISTORY = _id(21)
_SYSTEM = _id(30)
_CONVERSATION = _id(31)
_ACCOUNT_CATALOG_A = _id(32)
_ACCOUNT_CATALOG_B = _id(33)
_OAUTH_CATALOG = _id(34)
_IMAGE_CURRENT = _id(35)
_IMAGE_STALE = _id(36)
_SYSTEM_SNAPSHOT = _id(40)
_HISTORY_SNAPSHOT = _id(49)
_ENTRY_CURRENT = _id(50)
_ENTRY_UNMATCHED = _id(51)
_ENTRY_HISTORY = _id(52)
_IMAGE_ENTRY_CURRENT = _id(57)
_IMAGE_ENTRY_STALE = _id(58)
_SOURCE_ATTEMPT = _id(60)
_CATALOG_ATTEMPT = _id(61)
_AGENT = _id(70)
_CROSS_AGENT = _id(74)
_SESSION = _id(71)
_COMPLETED_TITLE_SESSION = _id(72)
_ACTIVE_TITLE_SESSION = _id(73)
_PENDING_RUN = _id(80)
_RUNNING_RUN = _id(81)
_TERMINAL_RUN = _id(82)
_EVENT = _id(90)


@dataclass(frozen=True)
class _Database:
    engine: Engine
    config: AlembicConfig
    before: dict[str, Any]


@pytest.fixture
def database(postgres_container: PostgresContainer) -> Generator[_Database]:
    """Allocate a new database only inside the disposable Docker fixture."""
    name = "catalog_current_cutover_" + uuid4().hex
    admin = sa.create_engine(
        postgres_container.get_connection_url(), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as connection:
        connection.execute(sa.text(f"CREATE DATABASE {name}"))
    url = sa.engine.make_url(postgres_container.get_connection_url()).set(database=name)
    config = AlembicConfig(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, _BEFORE_SOURCE_FENCES)
        _seed_retired_source(engine)
        command.upgrade(config, _PARENT)
        _seed_legacy(engine)
        yield _Database(engine=engine, config=config, before=_preserved_data(engine))
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f"DROP DATABASE {name} WITH (FORCE)"))
        admin.dispose()


@pytest.fixture
def upgraded(database: _Database) -> _Database:
    command.upgrade(database.config, _CUTOVER)
    return database


def _payload() -> CatalogSourcePayload:
    return decode_catalog_source(
        b'{"gpt-current":{"litellm_provider":"openai","mode":"chat",'
        b'"max_input_tokens":999999,'
        b'"input_cost_per_token":0.0000012345678901234567890123456789,'
        b'"output_cost_per_token":0.000002},'
        b'"openrouter/vendor/shared":{"litellm_provider":"openrouter",'
        b'"mode":"chat","input_cost_per_token":0.000003},'
        b'"claude-unrelated":{"litellm_provider":"anthropic",'
        b'"mode":"chat","input_cost_per_token":0.000004}}'
    )


def _seed_retired_source(engine: Engine) -> None:
    """Create opaque old-family history before its SQL writer becomes frozen."""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO model_metadata_sources(source_key) VALUES ('genai_prices')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO model_metadata_source_snapshots "
                "(id,source_key,source_kind,source_schema_version,source_url,"
                "source_hash,producer_name,producer_version,"
                "provider_count,model_count,payload,created_at) "
                "VALUES (:id,'genai_prices','genai_prices','1',"
                "'https://fixture.test/retired.json',:hash,'Retired fixture','old',"
                "0,0,CAST(:payload AS jsonb),:when)"
            ),
            {
                "id": _id(19),
                "hash": "g" * 64,
                "when": _OLDER_TIME,
                "payload": json.dumps({"retired_opaque_history": True}),
            },
        )
        connection.execute(
            sa.text(
                "UPDATE model_metadata_sources SET current_snapshot_id=:id "
                "WHERE source_key='genai_prices'"
            ),
            {"id": _id(19)},
        )


def _saved_price() -> dict[str, Any]:
    old = decode_catalog_source(
        b'{"gpt-current":{"litellm_provider":"openai",'
        b'"input_cost_per_token":0.07,"output_cost_per_token":0.08}}'
    ).models[0]
    return normalize_model_pricing(
        source_key=CATALOG_SOURCE_KEY, source_model=old, collected_at=_OLDER_TIME
    ).model_dump(mode="json")


def _selection(
    *, integration: str, provider: LLMProvider, identifier: str
) -> dict[str, Any]:
    selection = (
        make_test_model_selection(
            integration_id=integration, provider=provider, model_identifier=identifier
        )
        .model_copy(
            update={
                "normalized_capabilities": ModelCapabilities(
                    context_window=ModelContextWindow(
                        default_input_tokens=64_000,
                        max_input_tokens=131_072,
                        max_output_tokens=8_192,
                    )
                ),
                "model_snapshot": {
                    "source": "historical-diagnostics",
                    "snapshot_id": _SYSTEM_SNAPSHOT,
                },
            }
        )
        .model_dump(mode="json")
    )
    del selection["pricing"]
    return selection


def _option(label: str, selections: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "label": label,
        "candidates": [
            {
                "model_selection": selection,
                "settings": {
                    "context_window_tokens": 70_000,
                    "max_output_tokens": 4_096,
                    "builtin_tools": [],
                },
            }
            for selection in selections
        ],
        "subagent_enabled": True,
        "subagent_guidance": "Preserved fixture guidance",
    }


def _operation(
    option: dict[str, Any], *, kind: ModelOperationKind, state: str
) -> dict[str, Any]:
    typed_option = SelectableModelOption.model_validate(option)
    operation = build_model_operation(
        option=typed_option,
        profile=RequestedInferenceProfile(
            model_target_label=typed_option.label,
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
        kind=kind,
        operation_id=uuid4().hex,
        recorded_at=_OLDER_TIME,
    )
    if state in {"active", "completed"}:
        operation = mark_current_candidate_active(
            operation,
            reason=ModelOperationCandidateOutcomeReason.SELECTED,
            recorded_at=_OLDER_TIME,
        )
    if state == "completed":
        operation = mark_model_operation_succeeded(operation, recorded_at=_OLDER_TIME)
    encoded = operation.model_dump(mode="json")
    for candidate, original in zip(
        encoded["candidates"], option["candidates"], strict=True
    ):
        if "pricing" not in original["model_selection"]:
            del candidate["model_selection"]["pricing"]
    return encoded


def _insert_source(
    connection: Connection,
    *,
    source_id: str,
    payload: CatalogSourcePayload,
    when: datetime.datetime,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO model_metadata_source_snapshots "
            "(id,source_key,source_kind,source_schema_version,source_url,source_hash,"
            "producer_name,producer_version,provider_count,"
            "model_count,payload,created_at) "
            "VALUES (:id,:key,'litellm_json','1','https://fixture.test/catalog.json',"
            ":hash,'Fixture',:producer,:providers,:models,"
            "CAST(:payload AS jsonb),:when)"
        ),
        {
            "id": source_id,
            "key": CATALOG_SOURCE_KEY,
            "hash": _historical_source_hash(payload),
            "producer": "sha256:" + _historical_source_hash(payload),
            "providers": payload.provider_count,
            "models": payload.model_count,
            "payload": payload.model_dump_json(),
            "when": when,
        },
    )


def _insert_catalog(
    connection: Connection,
    *,
    catalog: str,
    provider: str,
    integration: str | None,
    purpose: str,
    snapshot: str,
    source: str | None,
    configuration: int | None,
    count: int,
    hidden: int,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO llm_catalogs "
            "(id,scope,provider,purpose,provider_integration_id) "
            "VALUES (:id,:scope,:provider,:purpose,:integration)"
        ),
        {
            "id": catalog,
            "scope": "system" if integration is None else "integration",
            "provider": provider,
            "purpose": purpose,
            "integration": integration,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO llm_catalog_snapshots "
            "(id,catalog_id,source_snapshot_id,projection_schema_version,entry_count,"
            "visible_count,hidden_count,projection_fingerprint,"
            "catalog_configuration_version,created_at,diagnostics) "
            "VALUES (:id,:catalog,:source,:schema,:count,:visible,"
            ":hidden,:fingerprint,:configuration,:when,CAST(:diagnostics AS jsonb))"
        ),
        {
            "id": snapshot,
            "catalog": catalog,
            "source": source,
            "schema": "2" if purpose == "conversation" else None,
            "count": count,
            "visible": count - hidden,
            "hidden": hidden,
            "fingerprint": "f" * 64,
            "configuration": configuration,
            "when": _SUCCESS_TIME,
            "diagnostics": json.dumps(_LEGACY_OWNER_DIAGNOSTICS),
        },
    )
    connection.execute(
        sa.text("UPDATE llm_catalogs SET current_snapshot_id=:snapshot WHERE id=:id"),
        {"snapshot": snapshot, "id": catalog},
    )


def _insert_entry(
    connection: Connection,
    *,
    entry: str,
    catalog: str,
    snapshot: str,
    provider: str,
    integration: str | None,
    identifier: str,
    hidden: bool,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO llm_catalog_entries "
            "(id,catalog_id,snapshot_id,provider,provider_integration_id,"
            "provider_model_identifier,display_name,normalized_capabilities,"
            "supported_execution_options,lifecycle_status,"
            "visibility_status,source_metadata,projection_metadata,hidden_reason) "
            "VALUES (:id,:catalog,:snapshot,:provider,:integration,"
            ":identifier,:identifier,CAST(:caps AS jsonb),'[]'::jsonb,"
            "'active',:visibility,CAST(:source AS jsonb),"
            "CAST(:projection AS jsonb),:hidden_reason)"
        ),
        {
            "id": entry,
            "catalog": catalog,
            "snapshot": snapshot,
            "provider": provider,
            "integration": integration,
            "identifier": identifier,
            "caps": ModelCapabilities().model_dump_json(),
            "visibility": "hidden" if hidden else "selectable",
            "source": json.dumps({"fixture": "source-preserved"}),
            "projection": json.dumps(
                {
                    "fixture": "projection-preserved",
                    "source_snapshot_id": _SOURCE_CURRENT,
                    "source_hash": "h" * 64,
                    "projection_fingerprint": "f" * 64,
                }
            ),
            "hidden_reason": "fixture-hidden" if hidden else None,
        },
    )


def _seed_legacy(engine: Engine) -> None:
    known = _selection(
        integration=_NATIVE, provider=LLMProvider.OPENAI, identifier="gpt-current"
    )
    retained = _selection(
        integration=_NATIVE_TWO, provider=LLMProvider.OPENAI, identifier="gpt-current"
    )
    retained["pricing"] = _saved_price()
    missing = _selection(
        integration=_NATIVE, provider=LLMProvider.OPENAI, identifier="gpt-unmatched"
    )
    wrong_account = _selection(
        integration=_ACCOUNT_A,
        provider=LLMProvider.OPENROUTER,
        identifier="vendor/shared",
    )
    oauth = _selection(
        integration=_OAUTH, provider=LLMProvider.CHATGPT_OAUTH, identifier="gpt-current"
    )
    null_price = copy.deepcopy(known)
    null_price["pricing"] = None
    main = _option("default", [known, retained, missing, wrong_account, oauth])
    lightweight = _option("lightweight", [null_price])
    pending = _operation(main, kind=ModelOperationKind.FOREGROUND, state="pending")
    active = _operation(main, kind=ModelOperationKind.FOREGROUND, state="active")
    pending_compaction = _operation(
        main, kind=ModelOperationKind.COMPACTION, state="pending"
    )
    completed_compaction = _operation(
        main, kind=ModelOperationKind.COMPACTION, state="completed"
    )
    title_pending = _operation(main, kind=ModelOperationKind.TITLE, state="pending")
    title_completed = _operation(main, kind=ModelOperationKind.TITLE, state="completed")
    title_active = _operation(main, kind=ModelOperationKind.TITLE, state="active")
    memory_pending = _operation(
        main, kind=ModelOperationKind.HISTORICAL_MEMORY, state="pending"
    )
    memory_active = _operation(
        main, kind=ModelOperationKind.HISTORICAL_MEMORY, state="active"
    )
    memory_completed = _operation(
        main, kind=ModelOperationKind.HISTORICAL_MEMORY, state="completed"
    )
    cross = _selection(
        integration=_CROSS_WORKSPACE,
        provider=LLMProvider.OPENAI,
        identifier="gpt-current",
    )
    with engine.begin() as connection:
        for workspace, handle in (
            (_WORKSPACE, "current-cutover"),
            (_OTHER_WORKSPACE, "other-cutover"),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO workspaces (id,name,handle) "
                    "VALUES (:id,'Fixture',:handle)"
                ),
                {"id": workspace, "handle": handle},
            )
        for integration, provider, workspace in (
            (_NATIVE, "openai", _WORKSPACE),
            (_NATIVE_TWO, "openai", _WORKSPACE),
            (_ACCOUNT_A, "openrouter", _WORKSPACE),
            (_ACCOUNT_B, "openrouter", _WORKSPACE),
            (_OAUTH, "chatgpt_oauth", _WORKSPACE),
            (_CROSS_WORKSPACE, "openai", _OTHER_WORKSPACE),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO llm_provider_integrations "
                    "(id,workspace_id,provider,name,encrypted_credentials,enabled) "
                    "VALUES (:id,:workspace,:provider,'Fixture',"
                    "'inert-fixture-not-a-secret',true)"
                ),
                {"id": integration, "workspace": workspace, "provider": provider},
            )
        _insert_source(
            connection, source_id=_SOURCE_CURRENT, payload=_payload(), when=_SOURCE_TIME
        )
        historical = decode_catalog_source(
            b'{"gpt-removed":{"litellm_provider":"openai",'
            b'"mode":"chat","input_cost_per_token":999}}'
        )
        _insert_source(
            connection, source_id=_SOURCE_HISTORY, payload=historical, when=_OLDER_TIME
        )
        connection.execute(
            sa.text(
                "UPDATE model_metadata_sources SET current_snapshot_id=:source "
                "WHERE source_key=:key"
            ),
            {"source": _SOURCE_CURRENT, "key": CATALOG_SOURCE_KEY},
        )
        for args in (
            (
                _SYSTEM,
                "openai",
                None,
                "conversation",
                _SYSTEM_SNAPSHOT,
                _SOURCE_CURRENT,
                None,
                2,
                1,
            ),
            (
                _CONVERSATION,
                "openai",
                _NATIVE,
                "conversation",
                _id(41),
                _SOURCE_CURRENT,
                None,
                1,
                0,
            ),
            (
                _ACCOUNT_CATALOG_A,
                "openrouter",
                _ACCOUNT_A,
                "conversation",
                _id(42),
                _SOURCE_CURRENT,
                None,
                1,
                0,
            ),
            (
                _ACCOUNT_CATALOG_B,
                "openrouter",
                _ACCOUNT_B,
                "conversation",
                _id(43),
                _SOURCE_CURRENT,
                None,
                1,
                0,
            ),
            (
                _OAUTH_CATALOG,
                "chatgpt_oauth",
                _OAUTH,
                "conversation",
                _id(44),
                _SOURCE_CURRENT,
                None,
                1,
                0,
            ),
            (
                _IMAGE_CURRENT,
                "openai",
                _NATIVE,
                "image_generation",
                _id(45),
                None,
                1,
                1,
                0,
            ),
            (
                _IMAGE_STALE,
                "openai",
                _NATIVE_TWO,
                "image_generation",
                _id(46),
                None,
                0,
                1,
                0,
            ),
        ):
            (
                catalog,
                provider,
                integration,
                purpose,
                snapshot,
                source,
                configuration,
                count,
                hidden,
            ) = args
            _insert_catalog(
                connection,
                catalog=catalog,
                provider=provider,
                integration=integration,
                purpose=purpose,
                snapshot=snapshot,
                source=source,
                configuration=configuration,
                count=count,
                hidden=hidden,
            )
        connection.execute(
            sa.text(
                "INSERT INTO llm_catalog_snapshots "
                "(id,catalog_id,source_snapshot_id,projection_schema_version,"
                "entry_count,visible_count,hidden_count,"
                "projection_fingerprint,created_at) "
                "VALUES (:id,:catalog,:source,'2',1,1,0,:fingerprint,:when)"
            ),
            {
                "id": _HISTORY_SNAPSHOT,
                "catalog": _SYSTEM,
                "source": _SOURCE_HISTORY,
                "fingerprint": "o" * 64,
                "when": _OLDER_TIME,
            },
        )
        for args in (
            (
                _ENTRY_CURRENT,
                _SYSTEM,
                _SYSTEM_SNAPSHOT,
                "openai",
                None,
                "gpt-current",
                True,
            ),
            (
                _ENTRY_UNMATCHED,
                _SYSTEM,
                _SYSTEM_SNAPSHOT,
                "openai",
                None,
                "gpt-unmatched",
                False,
            ),
            (
                _ENTRY_HISTORY,
                _SYSTEM,
                _HISTORY_SNAPSHOT,
                "openai",
                None,
                "gpt-removed",
                False,
            ),
            (
                _id(53),
                _ACCOUNT_CATALOG_A,
                _id(42),
                "openrouter",
                _ACCOUNT_A,
                "vendor/account-a",
                False,
            ),
            (
                _id(54),
                _ACCOUNT_CATALOG_B,
                _id(43),
                "openrouter",
                _ACCOUNT_B,
                "vendor/shared",
                False,
            ),
            (
                _id(55),
                _OAUTH_CATALOG,
                _id(44),
                "chatgpt_oauth",
                _OAUTH,
                "gpt-current",
                False,
            ),
            (_id(56), _CONVERSATION, _id(41), "openai", _NATIVE, "gpt-current", False),
        ):
            entry, catalog, snapshot, provider, integration, identifier, hidden = args
            _insert_entry(
                connection,
                entry=entry,
                catalog=catalog,
                snapshot=snapshot,
                provider=provider,
                integration=integration,
                identifier=identifier,
                hidden=hidden,
            )
        for entry, catalog, snapshot, integration in (
            (_IMAGE_ENTRY_CURRENT, _IMAGE_CURRENT, _id(45), _NATIVE),
            (_IMAGE_ENTRY_STALE, _IMAGE_STALE, _id(46), _NATIVE_TWO),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO image_generation_catalog_entries "
                    "(id,catalog_id,snapshot_id,provider,provider_integration_id,"
                    "provider_model_identifier,display_name,description,"
                    "recommendation_rank,lifecycle_status,visibility_status) "
                    "VALUES (:id,:catalog,:snapshot,'openai',:integration,"
                    "'gpt-image-2.5-flare','Image','Reviewed fixture',"
                    "1,'active','selectable')"
                ),
                {
                    "id": entry,
                    "catalog": catalog,
                    "snapshot": snapshot,
                    "integration": integration,
                },
            )
        for attempt, catalog, key in (
            (_SOURCE_ATTEMPT, None, CATALOG_SOURCE_KEY),
            (_CATALOG_ATTEMPT, _SYSTEM, CATALOG_SOURCE_KEY),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO llm_catalog_sync_attempts "
                    "(id,catalog_id,source_key,status,started_at,finished_at,"
                    "failure_code,failure_message,action_hint,fetched_count,"
                    "matched_count,skipped_count,hidden_count,diagnostics) "
                    "VALUES (:id,:catalog,:key,'failed',:when,:when,"
                    "'fixture-failure','Fixture failure','Retry fixture',"
                    "17,13,3,1,CAST(:diagnostics AS jsonb))"
                ),
                {
                    "id": attempt,
                    "catalog": catalog,
                    "key": key,
                    "when": _FAILURE_TIME,
                    "diagnostics": json.dumps(_LEGACY_DIAGNOSTICS),
                },
            )
        connection.execute(
            sa.text(
                "UPDATE model_metadata_sources SET latest_attempt_id=:attempt "
                "WHERE source_key=:key"
            ),
            {"attempt": _SOURCE_ATTEMPT, "key": CATALOG_SOURCE_KEY},
        )
        connection.execute(
            sa.text(
                "UPDATE llm_catalogs SET latest_attempt_id=:attempt WHERE id=:catalog"
            ),
            {"attempt": _CATALOG_ATTEMPT, "catalog": _SYSTEM},
        )
        for agent, selections, options in (
            (_AGENT, (known, null_price), [main, lightweight]),
            (_CROSS_AGENT, (cross, cross), [_option("default", [cross])]),
        ):
            primary, light = selections
            light_label = "lightweight" if agent == _AGENT else "default"
            connection.execute(
                sa.text(
                    "INSERT INTO agents "
                    "(id,workspace_id,name,model_selection,"
                    "lightweight_model_selection,selectable_model_options,"
                    "main_model_label,lightweight_model_label,"
                    "enabled,type,memory_enabled) "
                    "VALUES (:id,:workspace,'Fixture',CAST(:primary AS jsonb),"
                    "CAST(:light AS jsonb),CAST(:options AS jsonb),"
                    "'default',:label,true,'public',true)"
                ),
                {
                    "id": agent,
                    "workspace": _WORKSPACE,
                    "primary": json.dumps(primary),
                    "light": json.dumps(light),
                    "options": json.dumps(options),
                    "label": light_label,
                },
            )
        connection.execute(
            sa.text(
                "INSERT INTO workspace_model_settings "
                "(workspace_id,default_model_selection,"
                "default_lightweight_model_selection,default_selectable_model_options,"
                "default_main_model_label,default_lightweight_model_label) "
                "VALUES (:workspace,CAST(:primary AS jsonb),CAST(:light AS jsonb),"
                "CAST(:options AS jsonb),'default','lightweight')"
            ),
            {
                "workspace": _WORKSPACE,
                "primary": json.dumps(known),
                "light": json.dumps(null_price),
                "options": json.dumps([main, lightweight]),
            },
        )
        for session, title in (
            (_SESSION, title_pending),
            (_COMPLETED_TITLE_SESSION, title_completed),
            (_ACTIVE_TITLE_SESSION, title_active),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO agent_sessions "
                    "(id,workspace_id,agent_id,handle,session_kind,status,"
                    "start_reason,product_mode,primary_kind,current_model_target_label,"
                    "current_model_selection,current_model_settings,"
                    "current_effective_context_window_tokens,"
                    "current_effective_auto_compaction_threshold_tokens,"
                    "current_inference_resolved_at,title_model_operation_state) "
                    "VALUES (:id,:workspace,:agent,:handle,'root','active','initial',"
                    "'team',:primary_kind,'default',CAST(:selection AS jsonb),"
                    "CAST(:settings AS jsonb),70000,63000,:when,"
                    "CAST(:title AS jsonb))"
                ),
                {
                    "id": session,
                    "workspace": _WORKSPACE,
                    "agent": _AGENT,
                    "handle": "fixture-" + session[-2:],
                    "primary_kind": "team_primary" if session == _SESSION else None,
                    "selection": json.dumps(known),
                    "settings": json.dumps(main["candidates"][0]["settings"]),
                    "when": _OLDER_TIME,
                    "title": json.dumps(title),
                },
            )
        for run, index, status, state in (
            (
                _PENDING_RUN,
                1,
                "pending",
                {"foreground": pending, "compaction": pending_compaction},
            ),
            (
                _RUNNING_RUN,
                2,
                "running",
                {"foreground": active, "compaction": completed_compaction},
            ),
            (
                _TERMINAL_RUN,
                3,
                "completed",
                {"foreground": pending, "compaction": pending_compaction},
            ),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO agent_runs "
                    "(id,session_id,run_index,status,model_operation_state) "
                    "VALUES (:id,:session,:index,:status,CAST(:state AS jsonb))"
                ),
                {
                    "id": run,
                    "session": _SESSION,
                    "index": index,
                    "status": status,
                    "state": json.dumps(state),
                },
            )
        event_payload = {
            "content": "Historical fixture",
            "usage": {
                "cost_usd": 0.125,
                "cost_provenance": {
                    "method": "estimated",
                    "provider": "openai",
                    "model_identifier": "gpt-current",
                    "service_tier": "standard",
                    "source_snapshot_id": _SOURCE_HISTORY,
                    "source_hash": "historic-hash",
                    "source_model_key": "gpt-current",
                    "estimator_version": "1",
                },
            },
        }
        connection.execute(
            sa.text(
                "INSERT INTO events (id,session_id,kind,payload) "
                "VALUES (:id,:session,'assistant_message',CAST(:payload AS jsonb))"
            ),
            {"id": _EVENT, "session": _SESSION, "payload": json.dumps(event_payload)},
        )
        connection.execute(
            sa.text(
                "INSERT INTO events (id,session_id,kind,payload) "
                "VALUES (:id,:session,'assistant_message',CAST(:payload AS jsonb))"
            ),
            {
                "id": _id(91),
                "session": _COMPLETED_TITLE_SESSION,
                "payload": json.dumps(event_payload),
            },
        )
        for session, operation, prepared in (
            (_SESSION, memory_pending, False),
            (_ACTIVE_TITLE_SESSION, memory_active, False),
            (_COMPLETED_TITLE_SESSION, memory_completed, True),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO historical_memory_sources "
                    "(source_session_id,admitted_at,model_operation_state,prepared_at,"
                    "completed_source_activity_at,completed_source_tail_event_id,"
                    "summary,source_title_snapshot) "
                    "VALUES (:session,:when,CAST(:operation AS jsonb),:prepared,"
                    ":completed,:tail,:summary,:title)"
                ),
                {
                    "session": session,
                    "when": _OLDER_TIME,
                    "operation": json.dumps(operation),
                    "prepared": _OLDER_TIME if prepared else None,
                    "completed": _OLDER_TIME if prepared else None,
                    "tail": _id(91) if prepared else None,
                    "summary": "Preserved prepared memory" if prepared else None,
                    "title": "Preserved memory source title" if prepared else None,
                },
            )


def _preserved_data(engine: Engine) -> dict[str, Any]:
    result: dict[str, Any] = {}
    with engine.connect() as connection:
        for table, columns in (
            (
                "agents",
                "id,model_selection,lightweight_model_selection,"
                "selectable_model_options,main_model_label,lightweight_model_label",
            ),
            (
                "workspace_model_settings",
                "workspace_id,default_model_selection,"
                "default_lightweight_model_selection,default_selectable_model_options",
            ),
            (
                "agent_sessions",
                "id,current_model_selection,current_model_settings,"
                "current_effective_context_window_tokens,"
                "current_effective_auto_compaction_threshold_tokens,"
                "title_model_operation_state",
            ),
            ("agent_runs", "id,status,model_operation_state"),
            ("events", "id,payload"),
            (
                "historical_memory_sources",
                "source_session_id,model_operation_state,prepared_at,"
                "completed_source_activity_at,completed_source_tail_event_id,"
                "summary,source_title_snapshot",
            ),
        ):
            result[table] = [
                dict(row)
                for row in connection.execute(
                    sa.text(f"SELECT {columns} FROM {table} ORDER BY 1")
                ).mappings()
            ]
    return result


def _without_prices(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_prices(child)
            for key, child in value.items()
            if key != "pricing"
        }
    if isinstance(value, list):
        return [_without_prices(child) for child in value]
    return value


def _row(engine: Engine, table: str, key: str, *, key_column: str) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(
            connection.execute(
                sa.text(f"SELECT * FROM {table} WHERE {key_column}=:key"), {"key": key}
            )
            .mappings()
            .one()
        )


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()


@contextmanager
def _rejected(engine: Engine) -> Generator[Connection]:
    with pytest.raises(DBAPIError) as failure, engine.begin() as connection:
        yield connection
    assert isinstance(failure.value.orig, psycopg.Error)
    assert failure.value.orig.sqlstate in {"P0001", "23503", "23514", "22P02"}


def test_cutover_retains_only_current_models_entries_and_latest_status(
    upgraded: _Database,
) -> None:
    assert _revision(upgraded.engine) == _CUTOVER
    with upgraded.engine.connect() as connection:
        models = (
            connection.execute(
                sa.text(
                    "SELECT provider,source_model_key,collected_at,pricing "
                    "FROM model_metadata_source_models "
                    "ORDER BY provider,source_model_key"
                )
            )
            .mappings()
            .all()
        )
        entries = (
            connection.execute(
                sa.text(
                    "SELECT id,provider_model_identifier,visibility_status,"
                    "pricing,projection_metadata FROM llm_catalog_entries ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
        images = (
            connection.execute(
                sa.text("SELECT id FROM image_generation_catalog_entries ORDER BY id")
            )
            .scalars()
            .all()
        )
    assert {(row["provider"], row["source_model_key"]) for row in models} == {
        (model.provider, model.source_key) for model in _payload().models
    }
    assert all(row["collected_at"] == _SOURCE_TIME for row in models)
    assert _ENTRY_HISTORY not in {row["id"] for row in entries}
    assert {row["id"] for row in entries} == {
        _ENTRY_CURRENT,
        _ENTRY_UNMATCHED,
        _id(53),
        _id(54),
        _id(55),
        _id(56),
    }
    assert images == [_IMAGE_ENTRY_CURRENT, _IMAGE_ENTRY_STALE]
    current = next(row for row in entries if row["id"] == _ENTRY_CURRENT)
    assert current["visibility_status"] == "hidden"
    price = ModelPricingDefinition.model_validate(current["pricing"])
    expected = normalize_model_pricing(
        source_key=CATALOG_SOURCE_KEY,
        source_model=next(
            model for model in _payload().models if model.provider == "openai"
        ),
        collected_at=_SOURCE_TIME,
    )
    assert price == expected
    for row in entries:
        assert not {
            "source_snapshot_id",
            "source_hash",
            "projection_fingerprint",
        }.intersection(row["projection_metadata"])
    source = _row(
        upgraded.engine,
        "model_metadata_sources",
        CATALOG_SOURCE_KEY,
        key_column="source_key",
    )
    catalog = _row(upgraded.engine, "llm_catalogs", _SYSTEM, key_column="id")
    assert source["model_count"] == 3 and source["last_success_at"] == _SOURCE_TIME
    assert source["producer_version"] is None
    assert catalog["entry_count"] == 2 and catalog["hidden_count"] == 1
    assert catalog["last_success_at"] == _SUCCESS_TIME
    assert catalog["diagnostics"] == _OWNER_DIAGNOSTICS
    for owner in (source, catalog):
        assert owner["sync_status"] == "failed"
        assert owner["sync_failure_code"] == "fixture-failure"
        assert owner["sync_fetched_count"] == 17
        assert owner["sync_diagnostics"] == _DIAGNOSTICS
        assert owner["sync_work_token"] is None


def test_cutover_removes_revision_tables_columns_and_foreign_keys(
    upgraded: _Database,
) -> None:
    inspector = sa.inspect(upgraded.engine)
    assert not {
        "model_metadata_source_snapshots",
        "llm_catalog_snapshots",
        "llm_catalog_sync_attempts",
    }.intersection(inspector.get_table_names())
    obsolete = {
        "current_snapshot_id",
        "latest_attempt_id",
        "snapshot_id",
        "source_snapshot_id",
        "source_hash",
        "projection_fingerprint",
        "catalog_configuration_version",
        "produced_snapshot_id",
    }
    for table in (
        "model_metadata_sources",
        "model_metadata_source_models",
        "llm_catalogs",
        "llm_catalog_entries",
        "image_generation_catalog_entries",
    ):
        assert not obsolete.intersection(
            column["name"] for column in inspector.get_columns(table)
        )
        assert all(
            fk["referred_table"]
            not in {
                "model_metadata_source_snapshots",
                "llm_catalog_snapshots",
                "llm_catalog_sync_attempts",
            }
            for fk in inspector.get_foreign_keys(table)
        )
    with upgraded.engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT source_key FROM model_metadata_sources")
        ).scalars().all() == [CATALOG_SOURCE_KEY]
        functions = (
            connection.execute(
                sa.text(
                    "SELECT proname FROM pg_proc "
                    "WHERE pronamespace='public'::regnamespace AND proname IN "
                    "('azents_check_catalog_source','azents_check_catalog_candidate',"
                    "'azents_guard_model_source_snapshot',"
                    "'azents_guard_catalog_snapshot',"
                    "'azents_guard_retired_source_attempt')"
                )
            )
            .scalars()
            .all()
        )
    assert functions == []


def test_price_only_initialization_covers_mirrors_workspace_and_session(
    upgraded: _Database,
) -> None:
    after = _preserved_data(upgraded.engine)
    assert _without_prices(after) == _without_prices(upgraded.before)
    agent = _row(upgraded.engine, "agents", _AGENT, key_column="id")
    workspace = _row(
        upgraded.engine,
        "workspace_model_settings",
        _WORKSPACE,
        key_column="workspace_id",
    )
    for choice in (agent["model_selection"], workspace["default_model_selection"]):
        assert (
            ModelPricingDefinition.model_validate(choice["pricing"]).collected_at
            == _SOURCE_TIME
        )
    assert agent["lightweight_model_selection"]["pricing"] is None
    assert workspace["default_lightweight_model_selection"]["pricing"] is None
    for options in (
        agent["selectable_model_options"],
        workspace["default_selectable_model_options"],
    ):
        selections = [
            candidate["model_selection"] for candidate in options[0]["candidates"]
        ]
        assert (
            ModelPricingDefinition.model_validate(selections[0]["pricing"]).rules
            is not None
        )
        assert selections[1]["pricing"] == _saved_price()
        for choice in selections[2:]:
            definition = ModelPricingDefinition.model_validate(choice["pricing"])
            assert (
                definition.rules is None and definition.unavailable_reason is not None
            )
        assert options[1]["candidates"][0]["model_selection"]["pricing"] is None
    for session in (_SESSION, _COMPLETED_TITLE_SESSION, _ACTIVE_TITLE_SESSION):
        row = _row(upgraded.engine, "agent_sessions", session, key_column="id")
        assert (
            ModelPricingDefinition.model_validate(
                row["current_model_selection"]["pricing"]
            ).rules
            is not None
        )
    cross = _row(upgraded.engine, "agents", _CROSS_AGENT, key_column="id")
    assert (
        ModelPricingDefinition.model_validate(cross["model_selection"]["pricing"]).rules
        is None
    )


def test_pending_candidates_preserve_physical_and_completed_history(
    upgraded: _Database,
) -> None:
    before_runs = {row["id"]: row for row in upgraded.before["agent_runs"]}
    before_sessions = {row["id"]: row for row in upgraded.before["agent_sessions"]}
    pending = _row(upgraded.engine, "agent_runs", _PENDING_RUN, key_column="id")[
        "model_operation_state"
    ]
    running = _row(upgraded.engine, "agent_runs", _RUNNING_RUN, key_column="id")[
        "model_operation_state"
    ]
    terminal = _row(upgraded.engine, "agent_runs", _TERMINAL_RUN, key_column="id")[
        "model_operation_state"
    ]
    assert terminal == before_runs[_TERMINAL_RUN]["model_operation_state"]
    for slot in ("foreground", "compaction"):
        assert (
            ModelPricingDefinition.model_validate(
                pending[slot]["candidates"][0]["model_selection"]["pricing"]
            ).rules
            is not None
        )
    assert (
        running["foreground"]["candidates"][0]["model_selection"]
        == before_runs[_RUNNING_RUN]["model_operation_state"]["foreground"][
            "candidates"
        ][0]["model_selection"]
    )
    assert "pricing" not in running["foreground"]["candidates"][0]["model_selection"]
    assert (
        running["foreground"]["candidates"][1]["model_selection"]["pricing"]
        == _saved_price()
    )
    assert "pricing" in running["foreground"]["candidates"][2]["model_selection"]
    assert (
        running["compaction"]
        == before_runs[_RUNNING_RUN]["model_operation_state"]["compaction"]
    )
    completed_title = _row(
        upgraded.engine, "agent_sessions", _COMPLETED_TITLE_SESSION, key_column="id"
    )["title_model_operation_state"]
    assert (
        completed_title
        == before_sessions[_COMPLETED_TITLE_SESSION]["title_model_operation_state"]
    )
    pending_title = _row(upgraded.engine, "agent_sessions", _SESSION, key_column="id")[
        "title_model_operation_state"
    ]
    assert "pricing" in pending_title["candidates"][0]["model_selection"]
    active_title = _row(
        upgraded.engine, "agent_sessions", _ACTIVE_TITLE_SESSION, key_column="id"
    )["title_model_operation_state"]
    assert "pricing" not in active_title["candidates"][0]["model_selection"]
    assert "pricing" in active_title["candidates"][2]["model_selection"]
    assert _preserved_data(upgraded.engine)["events"] == upgraded.before["events"]


def test_image_usability_and_configuration_invalidation_preserve_conversation(
    upgraded: _Database,
) -> None:
    conversation = _row(upgraded.engine, "llm_catalogs", _CONVERSATION, key_column="id")
    assert conversation["image_usable"] is None
    assert (
        _row(upgraded.engine, "llm_catalogs", _IMAGE_CURRENT, key_column="id")[
            "image_usable"
        ]
        is True
    )
    assert (
        _row(upgraded.engine, "llm_catalogs", _IMAGE_STALE, key_column="id")[
            "image_usable"
        ]
        is False
    )
    with upgraded.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE llm_provider_integrations SET "
                "catalog_configuration_version=catalog_configuration_version+1 "
                "WHERE id=:id"
            ),
            {"id": _NATIVE},
        )
    assert (
        _row(upgraded.engine, "llm_catalogs", _IMAGE_CURRENT, key_column="id")[
            "image_usable"
        ]
        is False
    )
    assert (
        _row(upgraded.engine, "llm_catalogs", _CONVERSATION, key_column="id")
        == conversation
    )


def test_pending_memory_prices_fill_and_completed_memory_remains_immutable(
    upgraded: _Database,
) -> None:
    before = {
        row["source_session_id"]: row
        for row in upgraded.before["historical_memory_sources"]
    }
    pending = _row(
        upgraded.engine,
        "historical_memory_sources",
        _SESSION,
        key_column="source_session_id",
    )
    assert (
        ModelPricingDefinition.model_validate(
            pending["model_operation_state"]["candidates"][0]["model_selection"][
                "pricing"
            ]
        ).rules
        is not None
    )
    active = _row(
        upgraded.engine,
        "historical_memory_sources",
        _ACTIVE_TITLE_SESSION,
        key_column="source_session_id",
    )["model_operation_state"]
    original = before[_ACTIVE_TITLE_SESSION]["model_operation_state"]
    assert (
        active["candidates"][0]["model_selection"]
        == (original["candidates"][0]["model_selection"])
    )
    assert "pricing" not in active["candidates"][0]["model_selection"]
    assert active["candidates"][1]["model_selection"]["pricing"] == _saved_price()
    assert "pricing" in active["candidates"][2]["model_selection"]
    completed = _row(
        upgraded.engine,
        "historical_memory_sources",
        _COMPLETED_TITLE_SESSION,
        key_column="source_session_id",
    )
    assert all(
        completed[column] == value
        for column, value in before[_COMPLETED_TITLE_SESSION].items()
    )


@pytest.mark.parametrize("malformed", ["provider", "integration", "purpose"])
def test_invalid_legacy_current_ownership_aborts_atomically(
    database: _Database, malformed: str
) -> None:
    """Old independent FKs do not make incompatible current entries transferable."""
    statements = {
        "provider": (
            "UPDATE llm_catalog_entries SET provider='anthropic' WHERE id=:entry",
            {"entry": _ENTRY_CURRENT},
        ),
        "integration": (
            "UPDATE image_generation_catalog_entries "
            "SET provider_integration_id=:integration WHERE id=:entry",
            {"entry": _IMAGE_ENTRY_CURRENT, "integration": _NATIVE_TWO},
        ),
        "purpose": (
            "UPDATE image_generation_catalog_entries "
            "SET catalog_id=:catalog,snapshot_id=:snapshot WHERE id=:entry",
            {
                "entry": _IMAGE_ENTRY_CURRENT,
                "catalog": _CONVERSATION,
                "snapshot": _id(41),
            },
        ),
    }
    statement, parameters = statements[malformed]
    with database.engine.begin() as connection:
        connection.execute(sa.text(statement), parameters)
    before = _preserved_data(database.engine)
    legacy_tables = set(sa.inspect(database.engine).get_table_names())
    with pytest.raises(ValueError, match="ownership"):
        command.upgrade(database.config, _CUTOVER)
    assert _revision(database.engine) == _PARENT
    assert _preserved_data(database.engine) == before
    assert set(sa.inspect(database.engine).get_table_names()) == legacy_tables


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE llm_catalog_entries SET catalog_id='"
        + _IMAGE_CURRENT
        + "' WHERE id='"
        + _ENTRY_CURRENT
        + "'",
        "UPDATE llm_catalog_entries SET provider='anthropic' WHERE id='"
        + _ENTRY_CURRENT
        + "'",
        "UPDATE llm_catalog_entries SET provider_integration_id='"
        + _NATIVE
        + "' WHERE id='"
        + _ENTRY_CURRENT
        + "'",
        "UPDATE image_generation_catalog_entries SET catalog_id='"
        + _CONVERSATION
        + "' WHERE id='"
        + _IMAGE_ENTRY_CURRENT
        + "'",
        "UPDATE image_generation_catalog_entries SET provider_integration_id='"
        + _NATIVE_TWO
        + "' WHERE id='"
        + _IMAGE_ENTRY_CURRENT
        + "'",
        "UPDATE model_metadata_sources SET source_kind='genai_prices' "
        "WHERE source_key='litellm_catalog'",
        "UPDATE model_metadata_sources SET source_schema_version='unsupported' "
        "WHERE source_key='litellm_catalog'",
        "INSERT INTO model_metadata_sources "
        "(source_key,source_kind,source_schema_version) "
        "VALUES ('unreviewed','litellm_json','1')",
    ],
)
def test_current_owner_purpose_and_allowed_source_guards(
    upgraded: _Database, statement: str
) -> None:
    with _rejected(upgraded.engine) as connection:
        connection.execute(sa.text(statement))


@pytest.mark.parametrize("source_attempt", [False, True])
def test_running_legacy_catalog_work_aborts_before_schema_or_data_changes(
    database: _Database, source_attempt: bool
) -> None:
    attempt = _SOURCE_ATTEMPT if source_attempt else _CATALOG_ATTEMPT
    with database.engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE llm_catalog_sync_attempts SET "
                "status='running',finished_at=NULL WHERE id=:id"
            ),
            {"id": attempt},
        )
    before = _preserved_data(database.engine)
    with pytest.raises(RuntimeError, match="catalog synchronization is still running"):
        command.upgrade(database.config, _CUTOVER)
    assert _revision(database.engine) == _PARENT
    assert _preserved_data(database.engine) == before
    assert "llm_catalog_snapshots" in sa.inspect(database.engine).get_table_names()
    assert (
        "model_metadata_source_models"
        not in sa.inspect(database.engine).get_table_names()
    )


def test_irreversible_downgrade_refuses_without_partial_schema_reversal(
    upgraded: _Database,
) -> None:
    before = _preserved_data(upgraded.engine)
    with pytest.raises(RuntimeError, match="irreversible"):
        command.downgrade(upgraded.config, _PARENT)
    assert _revision(upgraded.engine) == _CUTOVER
    assert _preserved_data(upgraded.engine) == before
    assert (
        "model_metadata_source_models" in sa.inspect(upgraded.engine).get_table_names()
    )
    assert "llm_catalog_snapshots" not in sa.inspect(upgraded.engine).get_table_names()


@pytest.mark.parametrize("malformed", ["source", "selected_price"])
def test_malformed_current_data_aborts_atomically(
    database: _Database, malformed: str
) -> None:
    """Invalid current evidence cannot be stamped as a successful conversion."""
    with database.engine.begin() as connection:
        if malformed == "source":
            connection.execute(
                sa.text(
                    "UPDATE model_metadata_source_snapshots "
                    'SET payload=\'{"models":"malformed"}\'::jsonb WHERE id=:id'
                ),
                {"id": _SOURCE_CURRENT},
            )
        else:
            connection.execute(
                sa.text(
                    "UPDATE agents SET model_selection=jsonb_set("
                    "model_selection,'{pricing}',"
                    '\'{"unexpected":"invalid definition"}\'::jsonb)'
                    " WHERE id=:id"
                ),
                {"id": _AGENT},
            )
    before = _preserved_data(database.engine)
    source_before = _row(
        database.engine,
        "model_metadata_source_snapshots",
        _SOURCE_CURRENT,
        key_column="id",
    )
    with pytest.raises((ValueError, RuntimeError)):
        command.upgrade(database.config, _CUTOVER)
    assert _revision(database.engine) == _PARENT
    assert _preserved_data(database.engine) == before
    assert (
        _row(
            database.engine,
            "model_metadata_source_snapshots",
            _SOURCE_CURRENT,
            key_column="id",
        )
        == source_before
    )
    assert "llm_catalog_snapshots" in sa.inspect(database.engine).get_table_names()
    assert (
        "model_metadata_source_models"
        not in sa.inspect(database.engine).get_table_names()
    )
