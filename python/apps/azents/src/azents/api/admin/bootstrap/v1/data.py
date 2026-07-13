"""System bootstrap Admin API schemas."""

from pydantic import BaseModel, Field

from azents.services.system_bootstrap.data import (
    SystemBootstrapOutput,
    SystemBootstrapStatusOutput,
)


class SystemBootstrapStatusResponse(SystemBootstrapStatusOutput):
    """Initial system bootstrap availability response."""


class SystemBootstrapFirstAdminRequest(BaseModel):
    """Initial system administrator credentials."""

    email: str = Field(description="Initial administrator email")
    password: str = Field(description="Initial administrator password")


class SystemBootstrapFirstAdminResponse(SystemBootstrapOutput):
    """Initial system administrator session response."""
