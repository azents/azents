"""Application Job Runtime registry tests."""

from azents.job_runtime.registry import get_job_handler_registry
from azents.scheduler.executor import SCHEDULER_JOB_HANDLER_KEY
from azents.services.external_channel.ingress_queue import (
    EXTERNAL_CHANNEL_INGRESS_JOB_HANDLER_KEY,
)


def test_only_external_channel_ingress_reruns_on_coalesced_submission() -> None:
    """Ingress consumes a lost-wake edge without changing Scheduler execution."""
    registry = get_job_handler_registry()

    assert registry.reruns_on_coalesce(EXTERNAL_CHANNEL_INGRESS_JOB_HANDLER_KEY)
    assert not registry.reruns_on_coalesce(SCHEDULER_JOB_HANDLER_KEY)
