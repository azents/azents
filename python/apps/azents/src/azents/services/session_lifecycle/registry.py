"""Service composition for external purge-phase sequencing."""

from azents.core.session_lifecycle_registry import get_session_lifecycle_registry
from azents.services.session_lifecycle.orchestrator import SessionLifecycleOrchestrator


def get_session_lifecycle_orchestrator() -> SessionLifecycleOrchestrator:
    """Compose the existing external purge orchestrator with its immutable registry."""
    return SessionLifecycleOrchestrator(registry=get_session_lifecycle_registry())
