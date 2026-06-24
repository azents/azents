"""Debug v1 API (Admin).

Provides operational debugging endpoints, such as Sentry/logging integration checks.
Exposed only on the Admin API and accessible only from the internal network.
"""

import logging
from enum import StrEnum
from typing import Annotated

import sentry_sdk
from fastapi import APIRouter, Query
from pydantic import BaseModel

from azents.utils.fastapi.route import RouteMounter

logger = logging.getLogger(__name__)

router = APIRouter()


class ErrorLevel(StrEnum):
    """Test error level."""

    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SentryDiagnostics(BaseModel):
    """Sentry SDK diagnostics."""

    initialized: bool
    dsn_configured: bool


class DebugErrorResponse(BaseModel):
    """Debug error response."""

    fired: bool
    level: str
    message: str
    sentry_event_id: str | None
    sentry: SentryDiagnostics


class DebugExceptionResponse(BaseModel):
    """Debug exception response. The actual response is 500."""

    message: str


def _get_sentry_diagnostics() -> SentryDiagnostics:
    """Collect Sentry SDK diagnostics."""
    initialized = sentry_sdk.is_initialized()
    dsn_configured = False
    if initialized:
        client = sentry_sdk.get_client()
        dsn_configured = client.dsn is not None
    return SentryDiagnostics(
        initialized=initialized,
        dsn_configured=dsn_configured,
    )


@router.post("/fire-log")
def fire_log(
    level: Annotated[
        ErrorLevel,
        Query(description="Log level (warning, error, critical)"),
    ] = ErrorLevel.ERROR,
    message: Annotated[
        str,
        Query(description="Log message"),
    ] = "Debug test log from admin API",
) -> DebugErrorResponse:
    """Emit a log at the specified level.

    Used to verify Sentry delivery.
    - WARNING: Sentry breadcrumb attached to the next event
    - ERROR/CRITICAL: sent directly with ``sentry_sdk.capture_message()``
    """
    log_func = getattr(logger, level.value)
    log_func(message, extra={"source": "debug_api"})

    # Send directly without relying on LoggingIntegration
    sentry_event_id: str | None = None
    if level != ErrorLevel.WARNING:
        sentry_event_id = sentry_sdk.capture_message(message, level=level.value)

    return DebugErrorResponse(
        fired=True,
        level=level.value,
        message=message,
        sentry_event_id=sentry_event_id,
        sentry=_get_sentry_diagnostics(),
    )


@router.post("/fire-exception")
def fire_exception(
    message: Annotated[
        str,
        Query(description="Exception message"),
    ] = "Debug test exception from admin API",
) -> DebugExceptionResponse:
    """Raise an unhandled exception.

    FastAPI returns 500 and sends an event with stacktrace to Sentry.
    """
    raise RuntimeError(message)


def mount(mounter: RouteMounter) -> None:
    """Mount Debug v1 routes."""
    mounter(
        router,
        prefix="/debug/v1",
        tag="Debug v1",
        description="Operational debugging API (Sentry/logging verification)",
    )
