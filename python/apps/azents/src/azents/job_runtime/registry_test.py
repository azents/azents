"""Application Job Runtime registry tests."""

from azents.job_runtime.registry import get_job_handler_registry
from azents.scheduler.executor import SCHEDULER_JOB_HANDLER_KEY
from azents.services.external_channel.ingress_queue import (
    EXTERNAL_CHANNEL_INGRESS_JOB_HANDLER_KEY,
)
from azents.services.historical_memory.constants import (
    HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY,
    HISTORICAL_MEMORY_PREPARE_HANDLER_KEY,
)


def test_ingress_and_memory_consume_coalesced_edges_without_scheduler_reruns() -> None:
    """Event-driven background work reruns without changing Scheduler execution."""
    registry = get_job_handler_registry()

    assert registry.reruns_on_coalesce(EXTERNAL_CHANNEL_INGRESS_JOB_HANDLER_KEY)
    assert not registry.reruns_on_coalesce(SCHEDULER_JOB_HANDLER_KEY)
    assert registry.get(HISTORICAL_MEMORY_PREPARE_HANDLER_KEY) is not None
    assert registry.reruns_on_coalesce(HISTORICAL_MEMORY_PREPARE_HANDLER_KEY)
    assert registry.get(HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY) is not None
    assert registry.reruns_on_coalesce(HISTORICAL_MEMORY_CONSOLIDATE_HANDLER_KEY)
