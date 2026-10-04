"""Complete namespace and definition proof for explicit bounded index renames."""

import importlib
import io
import pkgutil
from types import ModuleType

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from pytest_alembic.runner import MigrationContext as AlembicRunner
from sqlalchemy.engine import Engine

import azents.rdb.models as models
from azents.consts import PROJECT_ROOT
from azents.rdb.index_names import explicit_index_name, validate_index_name
from azents.rdb.models.base import RDBModel

_PARENT = "a332f5e0f329"
_REVISION = "5fc49fa80a63"

# The source-authoring expansion is separate from deployed literal identifiers.
_INDEX_AUTHORING = (
    (
        "ix_agent_runs_session_id_unique_pafdf7e0366e76506",
        "agent_runs",
        ("session_id",),
        True,
        "status = 'pending'",
        (),
    ),
    (
        "ix_agent_runtimes_desired_generation_last_life_bb2bd3e4f43c8f7a",
        "agent_runtimes",
        ("desired_generation", "last_lifecycle_dispatch_generation"),
        False,
        None,
        (),
    ),
    (
        "ix_agent_sessions_model_file_gc_cursor_event_i_75efbf56f215debd",
        "agent_sessions",
        ("model_file_gc_cursor_event_id", "model_input_head_event_id"),
        False,
        None,
        ("asc_nulls_first",),
    ),
    (
        "ix_agent_sessions_agent_id_unique_p7b932c5c10d734da",
        "agent_sessions",
        ("agent_id",),
        True,
        "status = 'active' AND primary_kind = 'team_primary' AND product_mode = 'team'",
        (),
    ),
    (
        "ix_archived_session_retention_applications_exp_733c28f24767a30d",
        "archived_session_retention_applications",
        ("expr",),
        False,
        None,
        ("fd0ad9026eee596b",),
    ),
    (
        "ix_archived_session_purge_participant_executio_5ea0028eac0baeb3",
        "archived_session_purge_participant_executions",
        ("purge_job_id", "phase"),
        False,
        None,
        (),
    ),
    (
        "ix_chat_write_requests_creation_agent_id_reque_b51989afdaf21d2f",
        "chat_write_requests",
        ("creation_agent_id", "requester_user_id", "client_request_id"),
        False,
        None,
        (),
    ),
    (
        "ix_exchange_upload_operations_cleanup_after_cl_183b909f7be93a36",
        "exchange_upload_operations",
        ("cleanup_after", "cleanup_lease_until", "id"),
        False,
        None,
        (),
    ),
    (
        "ix_external_account_links_provider_identity_sc_13d48b547d72dd7a",
        "external_account_links",
        ("provider", "identity_scope", "provider_user_id"),
        False,
        None,
        (),
    ),
    (
        "ix_external_channel_connections_provider_provi_0a15e241b656e145",
        "external_channel_connections",
        ("provider", "provider_tenant_id", "provider_app_id"),
        False,
        None,
        (),
    ),
    (
        "ix_external_channel_conversation_positions_con_1d1df5ccdc27993c",
        "external_channel_conversation_positions",
        ("connection_id", "provider_channel_id"),
        False,
        None,
        (),
    ),
    (
        "ix_external_channel_conversation_positions_con_fced1c72c65a3bca",
        "external_channel_conversation_positions",
        ("connection_id", "provider_channel_id", "provider_thread_key"),
        False,
        None,
        (),
    ),
    (
        "ix_external_channel_agent_routes_connection_id_e76c6f5501491d09",
        "external_channel_agent_routes",
        ("connection_id",),
        True,
        "connection_app_mode = 'single'",
        (),
    ),
    (
        "ix_external_channel_channel_defaults_connectio_3ed2f72938e718df",
        "external_channel_channel_defaults",
        ("connection_id", "provider_channel_id"),
        False,
        None,
        (),
    ),
    (
        "ix_external_channel_participation_settings_con_eff7d8df5d637efe",
        "external_channel_participation_settings",
        ("connection_id", "provider_parent_channel_id"),
        False,
        None,
        (),
    ),
    (
        "ix_external_channel_setup_claims_connection_id_14a8330f61c7560b",
        "external_channel_setup_claims",
        ("connection_id", "provider_parent_channel_id"),
        False,
        None,
        (),
    ),
    (
        "ix_external_channel_ingress_owners_preparation_401dc98916b2a085",
        "external_channel_ingress_owners",
        ("preparation_next_attempt_at", "lease_expires_at", "updated_at"),
        False,
        None,
        (),
    ),
    (
        "ix_external_channel_ingress_items_owner_id_sta_805bf271f468bc7a",
        "external_channel_ingress_items",
        ("owner_id", "state", "next_attempt_at", "queue_key"),
        False,
        None,
        (),
    ),
    (
        "ix_external_channel_ingress_items_conversation_e956b183b9e748f3",
        "external_channel_ingress_items",
        ("conversation_position_id", "trigger_position"),
        False,
        None,
        (),
    ),
    (
        "ix_github_user_installations_user_id_platform__04fa208ede6106a8",
        "github_user_installations",
        ("user_id", "platform_app_id", "installation_id"),
        False,
        None,
        (),
    ),
    (
        "ix_historical_consolidation_units_workspace_id_bea7c9654d4d7b7d",
        "historical_consolidation_units",
        ("workspace_id", "agent_id", "associated_user_id"),
        False,
        None,
        (),
    ),
    (
        "ix_historical_consolidation_work_workspace_id__76da5073a287ecef",
        "historical_consolidation_work",
        ("workspace_id", "agent_id", "scope", "associated_user_id", "sequence"),
        False,
        None,
        (),
    ),
    (
        "ix_historical_consolidation_revision_dependenc_6679cd501af214fe",
        "historical_consolidation_revision_dependencies",
        ("source_session_id",),
        False,
        None,
        (),
    ),
    (
        "ix_image_generation_catalog_entries_catalog_id_09d1052ed90fd2e8",
        "image_generation_catalog_entries",
        ("catalog_id", "recommendation_rank", "display_name"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_auth_binding_audit_events__eb3dbab7484ad7a9",
        "runtime_provider_auth_binding_audit_events",
        ("binding_id", "created_at"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_connections_binding_id_aut_43f2baf6a989b7a6",
        "runtime_provider_connections",
        ("binding_id", "auth_method", "auth_subject", "status"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_web_session_routes_desired_generati_45b803111f49cb65",
        "runtime_web_session_routes",
        ("desired_generation", "runner_generation", "lease_expires_at"),
        False,
        None,
        (),
    ),
    (
        "ix_session_agent_context_git_worktrees_session_eed7843d46102e3f",
        "session_agent_context_git_worktrees",
        ("session_agent_context_id", "status"),
        False,
        None,
        (),
    ),
    (
        "ix_session_agent_context_git_worktrees_session_ff1a8aeb4dda50f3",
        "session_agent_context_git_worktrees",
        ("session_agent_context_project_id",),
        False,
        None,
        (),
    ),
    (
        "ix_agent_automatic_project_items_agent_id_position",
        "agent_automatic_project_items",
        ("agent_id", "position"),
        False,
        None,
        (),
    ),
    (
        "ix_agent_project_catalog_entries_agent_id_updated_at",
        "agent_project_catalog_entries",
        ("agent_id", "updated_at"),
        False,
        None,
        (),
    ),
    (
        "ix_agent_project_defaults_agent_id_position",
        "agent_project_defaults",
        ("agent_id", "position"),
        False,
        None,
        (),
    ),
    (
        "ix_agent_runs_session_id_status",
        "agent_runs",
        ("session_id", "status"),
        False,
        None,
        (),
    ),
    (
        "ix_agent_run_input_events_event_id_agent_run_id",
        "agent_run_input_events",
        ("event_id", "agent_run_id"),
        False,
        None,
        (),
    ),
    (
        "ix_agent_run_input_events_agent_run_id_input_order",
        "agent_run_input_events",
        ("agent_run_id", "input_order"),
        False,
        None,
        (),
    ),
    (
        "ix_agent_runtimes_desired_state_provider_observed_state",
        "agent_runtimes",
        ("desired_state", "provider_observed_state"),
        False,
        None,
        (),
    ),
    (
        "ix_agent_sessions_agent_id_primary_kind_last_user_input_at",
        "agent_sessions",
        ("agent_id", "primary_kind", "last_user_input_at"),
        False,
        None,
        (),
    ),
    (
        "ix_agent_sessions_pending_command_created_at",
        "agent_sessions",
        ("pending_command_created_at",),
        False,
        None,
        (),
    ),
    (
        "ix_agent_sessions_run_heartbeat_at",
        "agent_sessions",
        ("run_heartbeat_at",),
        False,
        None,
        (),
    ),
    (
        "ix_agent_sessions_purge_after",
        "agent_sessions",
        ("purge_after",),
        False,
        None,
        (),
    ),
    (
        "ix_agent_sessions_last_activity_at_agent_id",
        "agent_sessions",
        ("last_activity_at", "agent_id"),
        False,
        None,
        (),
    ),
    (
        "ix_agent_sessions_agent_id_associated_user_id_status",
        "agent_sessions",
        ("agent_id", "associated_user_id", "status"),
        False,
        None,
        (),
    ),
    ("ix_events_session_id_id", "events", ("session_id", "id"), False, None, ()),
    (
        "ix_events_session_id_external_id",
        "events",
        ("session_id", "external_id"),
        False,
        None,
        (),
    ),
    (
        "ix_exchange_files_retention_root_session_id_status_id",
        "exchange_files",
        ("retention_root_session_id", "status", "id"),
        False,
        None,
        (),
    ),
    (
        "ix_external_account_oauth_attempts_user_id_auth_session_id",
        "external_account_oauth_attempts",
        ("user_id", "auth_session_id"),
        False,
        None,
        (),
    ),
    (
        "ix_historical_consolidation_units_workspace_id_agent_id",
        "historical_consolidation_units",
        ("workspace_id", "agent_id"),
        False,
        None,
        (),
    ),
    (
        "ix_mailbox_items_session_id_order_group_order_sequence_id",
        "mailbox_items",
        ("session_id", "order_group", "order_sequence", "id"),
        False,
        None,
        (),
    ),
    (
        "ix_mailbox_items_session_id_kind_idempotency_key",
        "mailbox_items",
        ("session_id", "kind", "idempotency_key"),
        False,
        None,
        (),
    ),
    (
        "ix_owner_lifecycle_jobs_workspace_id_user_id",
        "owner_lifecycle_jobs",
        ("workspace_id", "user_id"),
        False,
        None,
        (),
    ),
    (
        "ix_owner_lifecycle_jobs_user_id",
        "owner_lifecycle_jobs",
        ("user_id",),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_providers_lifecycle_state_enabled",
        "runtime_providers",
        ("lifecycle_state", "enabled"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_auth_bindings_auth_method_subject",
        "runtime_provider_auth_bindings",
        ("auth_method", "subject"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_auth_bindings_bootstrap_declaration_id",
        "runtime_provider_auth_bindings",
        ("bootstrap_declaration_id",),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_auth_bindings_provider_id_state",
        "runtime_provider_auth_bindings",
        ("provider_id", "state"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_auth_bindings_auth_method_subject_state",
        "runtime_provider_auth_bindings",
        ("auth_method", "subject", "state"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_audit_events_provider_id_created_at",
        "runtime_provider_audit_events",
        ("provider_id", "created_at"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_enrollment_grants_provider_id_state",
        "runtime_provider_enrollment_grants",
        ("provider_id", "state"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_credentials_provider_id_state",
        "runtime_provider_credentials",
        ("provider_id", "state"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_connections_provider_id_status",
        "runtime_provider_connections",
        ("provider_id", "status"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_connections_credential_id_status",
        "runtime_provider_connections",
        ("credential_id", "status"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_connections_binding_id_status",
        "runtime_provider_connections",
        ("binding_id", "status"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_contract_revisions_provider_id_created_at",
        "runtime_provider_contract_revisions",
        ("provider_id", "created_at"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_config_revisions_provider_id_state",
        "runtime_provider_config_revisions",
        ("provider_id", "state"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_provider_config_revisions_validation_request_id",
        "runtime_provider_config_revisions",
        ("validation_request_id",),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_web_services_agent_id_created_at",
        "runtime_web_services",
        ("agent_id", "created_at"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_web_services_exposure_deadline_at",
        "runtime_web_services",
        ("exposure_deadline_at",),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_web_operation_receipts_service_id_created_at",
        "runtime_web_operation_receipts",
        ("service_id", "created_at"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_web_gateway_identities_auth_session_id_expires_at",
        "runtime_web_gateway_identities",
        ("auth_session_id", "expires_at"),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_web_gateway_identities_expires_at",
        "runtime_web_gateway_identities",
        ("expires_at",),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_web_auth_bindings_expires_at",
        "runtime_web_auth_bindings",
        ("expires_at",),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_web_auth_tickets_expires_at",
        "runtime_web_auth_tickets",
        ("expires_at",),
        False,
        None,
        (),
    ),
    (
        "ix_runtime_web_session_routes_owner_boot_id_lease_expires_at",
        "runtime_web_session_routes",
        ("owner_boot_id", "lease_expires_at"),
        False,
        None,
        (),
    ),
)


def _directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(
        Config(PROJECT_ROOT / "db-schemas/rdb/alembic.ini")
    )


def _module() -> ModuleType:
    revision = _directory().get_revision(_REVISION)
    assert revision is not None
    return revision.module


def _load_all_models() -> None:
    for module in pkgutil.iter_modules(models.__path__):
        if not module.ispkg:
            importlib.import_module(f"{models.__name__}.{module.name}")


def test_explicit_literals_match_helper_full_metadata_and_single_revision() -> None:
    _load_all_models()
    directory = _directory()
    assert directory.get_heads() == [_REVISION]
    assert (PROJECT_ROOT / "db-schemas/rdb/revision").read_text().strip() == _REVISION
    revision = directory.get_revision(_REVISION)
    assert revision is not None and revision.down_revision == _PARENT
    indexes = [
        index for table in RDBModel.metadata.tables.values() for index in table.indexes
    ]
    assert all(index.name is not None for index in indexes)
    index_names = [str(index.name) for index in indexes]
    assert len(index_names) == len(set(index_names))
    namespace = set(RDBModel.metadata.tables)
    for name in index_names:
        assert name is not None
        validate_index_name(name, namespace)
        namespace.add(name)
    names = {rename.new for rename in _module()._INDEX_RENAMES}
    assert len(names) == 73
    assert names == {spec[0] for spec in _INDEX_AUTHORING}
    for name, table, columns, unique_variant, predicate, qualifiers in _INDEX_AUTHORING:
        assert (
            explicit_index_name(
                table,
                columns,
                unique_variant=unique_variant,
                predicate_variant=predicate,
                semantic_qualifiers=qualifiers,
            )
            == name
        )
        assert index_names.count(name) == 1


def test_offline_upgrade_and_downgrade_use_exact_literals() -> None:
    module = _module()
    for upgrade in (True, False):
        output = io.StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
        )
        with Operations.context(context):
            if upgrade:
                module.upgrade()
            else:
                module.downgrade()
        statements = output.getvalue()
        assert statements.count("ALTER INDEX") == 73
        assert "CREATE INDEX" not in statements and "DROP INDEX" not in statements
        for rename in module._INDEX_RENAMES:
            old, new = (rename.old, rename.new) if upgrade else (rename.new, rename.old)
            assert f'ALTER INDEX "{old}" RENAME TO "{new}";' in statements


def _definitions(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'"
            )
        )
        return {name: definition for name, definition in rows}


def _oids(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT c.relname, c.oid FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = 'public' "
                "AND c.relkind = 'i'"
            )
        )
        return {name: oid for name, oid in rows}


def test_real_upgrade_downgrade_preserves_definitions_oids_and_full_namespace(
    alembic_runner: AlembicRunner,
    alembic_engine: Engine,
) -> None:
    alembic_runner.migrate_up_to(_PARENT)
    before = _definitions(alembic_engine)
    before_oids = _oids(alembic_engine)
    renames = _module()._INDEX_RENAMES
    with alembic_engine.connect() as connection:
        relations = set(
            connection.scalars(
                sa.text(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname='public'"
                )
            )
        )
    for rename in renames:
        assert rename.old in before
        validate_index_name(rename.new, relations)
        relations.add(rename.new)
    alembic_runner.migrate_up_to(_REVISION)
    after = _definitions(alembic_engine)
    after_oids = _oids(alembic_engine)
    assert len(before) == len(after)
    old_names = {rename.old for rename in renames}
    for rename in renames:
        assert rename.old not in after
        assert after[rename.new] == before[rename.old].replace(
            rename.old, rename.new, 1
        )
        assert after_oids[rename.new] == before_oids[rename.old]
    for name in before.keys() - old_names:
        assert before[name] == after[name]
        assert before_oids[name] == after_oids[name]
    for name in (
        "ix_agent_runs_session_id",
        "ix_agent_sessions_agent_id",
        "ix_external_channel_agent_routes_connection_id",
    ):
        assert before[name] == after[name]
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname='public' "
                    "AND octet_length(c.relname)>63"
                )
            )
            == 0
        )
    alembic_runner.migrate_down_to(_PARENT)
    assert _definitions(alembic_engine) == before
    assert _oids(alembic_engine) == before_oids
