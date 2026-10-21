"""Token-free per-service management projections from the direct operation catalog."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from azents.core.google_policy import GoogleService
from azents.core.google_workspace_policy import (
    GOOGLE_WORKSPACE_OPERATIONS,
    GoogleWorkspaceOperation,
    eligible_operations,
)


class GoogleServiceAccess(BaseModel):
    """Local enablement and actual operation evidence are independent facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    service: GoogleService
    enabled: bool = Field(strict=True)
    status: Literal["disabled", "permitted", "partial", "not_granted", "unknown"]
    permitted_tools: tuple[GoogleWorkspaceOperation, ...]
    unavailable_tools: tuple[GoogleWorkspaceOperation, ...]


def service_accesses(
    services: tuple[GoogleService, ...],
    actual_scopes: tuple[str, ...] | None,
) -> tuple[GoogleServiceAccess, ...]:
    """Project all supported services without treating requested scopes as grants."""
    allowed = eligible_operations(services, actual_scopes)
    result: list[GoogleServiceAccess] = []
    for service in GoogleService:
        # Sender verification is an argument-dependent prerequisite, not a
        # user-facing alias-administration operation or separate model tool.
        known = frozenset(
            policy.operation
            for policy in GOOGLE_WORKSPACE_OPERATIONS.values()
            if policy.service is service
            and policy.operation is not GoogleWorkspaceOperation.GMAIL_GET_SEND_AS
        )
        permitted = known & allowed
        status: Literal["disabled", "permitted", "partial", "not_granted", "unknown"]
        if service not in services:
            status = "disabled"
        elif actual_scopes is None:
            status = "unknown"
        elif not permitted:
            status = "not_granted"
        elif permitted == known:
            status = "permitted"
        else:
            status = "partial"
        result.append(
            GoogleServiceAccess(
                service=service,
                enabled=service in services,
                status=status,
                permitted_tools=tuple(sorted(permitted)),
                unavailable_tools=tuple(sorted(known - permitted)),
            )
        )
    return tuple(result)
