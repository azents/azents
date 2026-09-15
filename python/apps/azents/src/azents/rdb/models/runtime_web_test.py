"""Runtime Web RDB model contract tests."""

import sqlalchemy as sa

from azents.rdb.models.base import RDBModel
from azents.rdb.models.runtime_web import (
    RDBRuntimeWebAuthBinding,
    RDBRuntimeWebAuthConfiguration,
    RDBRuntimeWebAuthTicket,
    RDBRuntimeWebGatewayIdentity,
    RDBRuntimeWebOperationReceipt,
    RDBRuntimeWebQuotaScope,
    RDBRuntimeWebService,
)


def test_runtime_web_service_has_agent_port_and_hostname_constraints() -> None:
    table = RDBModel.metadata.tables["runtime_web_services"]
    assert isinstance(table, sa.Table)
    constraints = {constraint.name for constraint in table.constraints}

    assert "uq_runtime_web_services_agent_port" in constraints
    assert "uq_runtime_web_services_hostname_key" in constraints
    assert "ck_runtime_web_services_duration" in constraints
    assert "ck_runtime_web_services_port" in constraints
    assert "agent_session_id" not in table.columns
    assert "current_request_id" not in table.columns
    assert "current_cycle_id" not in table.columns


def test_runtime_web_authority_tables_are_durable_metadata_only() -> None:
    tables = [
        RDBRuntimeWebService.__table__,
        RDBRuntimeWebOperationReceipt.__table__,
        RDBRuntimeWebQuotaScope.__table__,
        RDBRuntimeWebAuthConfiguration.__table__,
        RDBRuntimeWebGatewayIdentity.__table__,
        RDBRuntimeWebAuthBinding.__table__,
        RDBRuntimeWebAuthTicket.__table__,
    ]
    forbidden = {"body", "request_body", "response_body", "headers", "cookie"}

    for table in tables:
        assert forbidden.isdisjoint(table.columns.keys())


def test_service_dependents_cascade_from_agent_service_identity() -> None:
    agent_fk = next(
        foreign_key
        for foreign_key in RDBRuntimeWebService.__table__.foreign_keys
        if foreign_key.target_fullname == "agents.id"
    )
    service_fks = [
        foreign_key
        for table in (
            RDBRuntimeWebOperationReceipt.__table__,
            RDBRuntimeWebAuthBinding.__table__,
            RDBRuntimeWebAuthTicket.__table__,
        )
        for foreign_key in table.foreign_keys
        if foreign_key.target_fullname == "runtime_web_services.id"
    ]

    assert agent_fk.ondelete == "CASCADE"
    assert service_fks
    assert all(foreign_key.ondelete == "CASCADE" for foreign_key in service_fks)


def test_runtime_web_enums_use_postgresql_enum_columns() -> None:
    enum_columns = [
        RDBRuntimeWebOperationReceipt.__table__.c.actor_kind,
        RDBRuntimeWebOperationReceipt.__table__.c.operation_kind,
        RDBRuntimeWebAuthConfiguration.__table__.c.mode,
        RDBRuntimeWebGatewayIdentity.__table__.c.mode,
    ]

    assert all(isinstance(column.type, sa.Enum) for column in enum_columns)


def test_legacy_service_authority_tables_are_absent() -> None:
    assert {
        "runtime_web_endpoints",
        "runtime_web_requests",
        "runtime_web_cycles",
        "runtime_web_tunnel_routes",
        "runtime_web_admission_leases",
        "runtime_web_gateway_admission_leases",
    }.isdisjoint(RDBModel.metadata.tables)


def test_runtime_web_session_route_remains_runtime_generation_authority() -> None:
    route = RDBModel.metadata.tables["runtime_web_session_routes"]
    assert isinstance(route, sa.Table)
    constraints = {constraint.name for constraint in route.constraints}

    assert route.primary_key.columns.keys() == ["runtime_id"]
    assert "uq_runtime_web_session_routes_session_lease" in constraints
    assert "uq_runtime_web_session_routes_join_nonce_hash" in constraints
    assert {foreign_key.target_fullname for foreign_key in route.foreign_keys} == {
        "agent_runtimes.id"
    }
