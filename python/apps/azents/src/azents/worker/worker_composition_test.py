"""Agent Worker background-service composition tests."""

import dataclasses

from azents.worker.worker import AgentWorker


def test_worker_does_not_compose_legacy_external_channel_event_processor() -> None:
    """Normal provider messages have no legacy Worker ingestion owner."""
    dependency_names = {field.name for field in dataclasses.fields(AgentWorker)}

    assert "socket_manager" not in dependency_names
    assert "provider_control" not in dependency_names
    assert "external_channel_event_processor" not in dependency_names
