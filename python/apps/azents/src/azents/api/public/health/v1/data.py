"""Health API data models."""

from pydantic import BaseModel


class HealthStatus(BaseModel):
    """Server status response model."""

    status: str
