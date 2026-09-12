"""Runtime Web RDB model contract tests."""

import sqlalchemy as sa

from azents.rdb.models.base import RDBModel
from azents.rdb.models.runtime_web import (
    RDBRuntimeWebAdmissionLease,
    RDBRuntimeWebAuthBinding,
    RDBRuntimeWebAuthConfiguration,
    RDBRuntimeWebAuthTicket,
    RDBRuntimeWebCycle,
    RDBRuntimeWebEndpoint,
    RDBRuntimeWebGatewayIdentity,
    RDBRuntimeWebOperationReceipt,
    RDBRuntimeWebQuotaScope,
    RDBRuntimeWebRequest,
    RDBRuntimeWebTunnelRoute,
)


def test_runtime_web_tables_have_expected_identity_constraints() -> None:
    """Keep stable endpoint and one-current-state constraints reviewable."""
    endpoint = RDBModel.metadata.tables["runtime_web_endpoints"]
    request = RDBModel.metadata.tables["runtime_web_requests"]
    cycle = RDBModel.metadata.tables["runtime_web_cycles"]
    endpoint_constraints = {constraint.name for constraint in endpoint.constraints}
    request_indexes = {index.name for index in request.indexes}
    cycle_indexes = {index.name for index in cycle.indexes}

    assert "uq_runtime_web_endpoints_session_port" in endpoint_constraints
    assert "uq_runtime_web_endpoints_hostname_key" in endpoint_constraints
    assert "uq_runtime_web_requests_pending_endpoint" in request_indexes
    assert "uq_runtime_web_cycles_current_endpoint" in cycle_indexes


def test_runtime_web_authority_tables_are_durable_metadata_only() -> None:
    """Reject accidental content/body storage in authority tables."""
    tables = [
        RDBRuntimeWebEndpoint.__table__,
        RDBRuntimeWebRequest.__table__,
        RDBRuntimeWebCycle.__table__,
        RDBRuntimeWebOperationReceipt.__table__,
        RDBRuntimeWebQuotaScope.__table__,
        RDBRuntimeWebAuthConfiguration.__table__,
        RDBRuntimeWebGatewayIdentity.__table__,
        RDBRuntimeWebAuthBinding.__table__,
        RDBRuntimeWebAuthTicket.__table__,
        RDBRuntimeWebTunnelRoute.__table__,
        RDBRuntimeWebAdmissionLease.__table__,
    ]
    forbidden = {"body", "request_body", "response_body", "headers", "cookie"}

    for table in tables:
        assert forbidden.isdisjoint(table.columns.keys())


def test_runtime_web_runtime_identity_is_not_approval_identity() -> None:
    """Keep Runtime generations out of durable endpoint and approval rows."""
    authority_tables = [
        RDBRuntimeWebEndpoint.__table__,
        RDBRuntimeWebRequest.__table__,
        RDBRuntimeWebCycle.__table__,
    ]

    for table in authority_tables:
        assert "runtime_id" not in table.columns
        assert "runner_generation" not in table.columns
        assert "desired_generation" not in table.columns


def test_runtime_web_session_owned_rows_cascade() -> None:
    """Ensure the concrete Session owns durable endpoint cleanup."""
    session_fk = next(
        foreign_key
        for foreign_key in RDBRuntimeWebEndpoint.__table__.foreign_keys
        if foreign_key.target_fullname == "agent_sessions.id"
    )
    endpoint_fks = [
        foreign_key
        for table in (
            RDBRuntimeWebRequest.__table__,
            RDBRuntimeWebCycle.__table__,
            RDBRuntimeWebOperationReceipt.__table__,
            RDBRuntimeWebAuthBinding.__table__,
            RDBRuntimeWebAuthTicket.__table__,
        )
        for foreign_key in table.foreign_keys
        if foreign_key.target_fullname == "runtime_web_endpoints.id"
    ]

    assert session_fk.ondelete == "CASCADE"
    assert endpoint_fks
    assert all(foreign_key.ondelete == "CASCADE" for foreign_key in endpoint_fks)


def test_runtime_web_enums_use_postgresql_enum_columns() -> None:
    """Require native PostgreSQL enums for persisted closed sets."""
    enum_columns = [
        RDBRuntimeWebRequest.__table__.c.requester_kind,
        RDBRuntimeWebRequest.__table__.c.state,
        RDBRuntimeWebCycle.__table__.c.end_reason,
        RDBRuntimeWebOperationReceipt.__table__.c.operation_kind,
        RDBRuntimeWebQuotaScope.__table__.c.scope_kind,
        RDBRuntimeWebAuthConfiguration.__table__.c.mode,
        RDBRuntimeWebGatewayIdentity.__table__.c.mode,
    ]

    assert all(isinstance(column.type, sa.Enum) for column in enum_columns)


def test_runtime_web_transport_routes_are_exact_and_lease_fenced() -> None:
    """Keep transport ownership separate from durable approval authority."""
    route = RDBModel.metadata.tables["runtime_web_tunnel_routes"]
    admission = RDBModel.metadata.tables["runtime_web_admission_leases"]
    route_constraints = {constraint.name for constraint in route.constraints}
    admission_constraints = {constraint.name for constraint in admission.constraints}

    assert route.primary_key.columns.keys() == ["tunnel_id"]
    assert "uq_runtime_web_tunnel_routes_join_nonce" in route_constraints
    assert "uq_runtime_web_tunnel_routes_route_lease" in route_constraints
    assert "uq_runtime_web_admission_leases_tunnel" in admission_constraints
    assert {
        "endpoint_authority_revision",
        "close_barrier",
        "runtime_id",
        "desired_generation",
        "runner_generation",
        "join_nonce",
        "owner_boot_id",
        "route_lease_id",
        "lease_generation",
        "lease_expires_at",
    }.issubset(route.columns.keys())
