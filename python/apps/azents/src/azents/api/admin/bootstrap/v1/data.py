"""System bootstrap Admin API schemas."""

from pydantic import BaseModel, Field

from azents.services.system_bootstrap.data import (
    SystemBootstrapOutput,
    SystemBootstrapStatusOutput,
)


class SystemBootstrapStatusResponse(SystemBootstrapStatusOutput):
    """Initial system bootstrap availability response."""

    @classmethod
    def convert_from(
        cls,
        output: SystemBootstrapStatusOutput,
    ) -> "SystemBootstrapStatusResponse":
        """Convert service output to an API response."""
        return cls.model_validate(output.model_dump())


class SystemBootstrapFirstAdminRequest(BaseModel):
    """Initial system administrator credentials."""

    email: str = Field(description="Initial administrator email")
    password: str = Field(description="Initial administrator password")


class SystemBootstrapFirstAdminResponse(SystemBootstrapOutput):
    """Initial system administrator session response."""

    @classmethod
    def convert_from(
        cls,
        output: SystemBootstrapOutput,
    ) -> "SystemBootstrapFirstAdminResponse":
        """Convert service output to an API response."""
        return cls.model_validate(output.model_dump())
