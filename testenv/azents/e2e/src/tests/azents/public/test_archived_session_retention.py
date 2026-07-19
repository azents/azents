"""Archived-session lifecycle and purge E2E tests."""

from typing import Any, cast

import azentsadminclient
import azentspublicclient
import requests
from azentsadminclient.api.system_v1_api import SystemV1Api
from azentsadminclient.models.file_lifecycle_settings_update_request import (
    FileLifecycleSettingsUpdateRequest,
)
from azentspublicclient.api.chat_v1_api import ChatV1Api
from testcontainers.core.container import DockerContainer

from support.utils import create_chat_session_with_agent


def _headers(token: str) -> dict[str, str]:
    """Return bearer authorization headers."""
    return {"Authorization": f"Bearer {token}"}


def _create_secondary_session(
    *,
    server_url: str,
    token: str,
    agent_id: str,
) -> str:
    """Create a non-primary root session through the product API."""
    response = requests.post(
        f"{server_url}/chat/v1/agents/{agent_id}/sessions",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"existing_project_paths": [], "setup_actions": []},
        timeout=10,
    )
    response.raise_for_status()
    session_id = response.json().get("id")
    if not isinstance(session_id, str):
        raise AssertionError("session creation did not return an ID")
    return session_id


def _set_retention(system_api: SystemV1Api, retention_days: int | None) -> None:
    """Apply a future-archive retention revision."""
    current = system_api.system_v1_get_file_lifecycle_settings()
    if current.archived_session_retention_days == retention_days:
        return
    system_api.system_v1_update_file_lifecycle_settings(
        FileLifecycleSettingsUpdateRequest(
            expected_revision=current.revision,
            archived_session_retention_days=retention_days,
            application_scope="new_archives_only",
        )
    )


def _run_scheduler_task(
    container: DockerContainer,
    *,
    task_key: str,
) -> None:
    """Trigger and execute one scheduler pass inside the deployed server image."""
    script = f"""
import asyncio
from azents.app import run_with_container
from azents.core.config import Config
from azents.scheduler.service import SchedulerService

async def main():
    config = Config.from_env()
    async with run_with_container(config) as dependency_container:
        scheduler = await dependency_container.solve(SchedulerService)
        state = await scheduler.trigger({task_key!r})
        if state is None:
            raise RuntimeError('unknown scheduler task')
        await scheduler.run_once()

asyncio.run(main())
"""
    result = container.get_wrapped_container().exec_run(["python", "-c", script])
    exit_code = cast(Any, result).exit_code
    if exit_code != 0:
        output = cast(Any, result).output.decode(errors="replace")
        raise AssertionError(
            f"scheduler task {task_key} failed with exit {exit_code}:\n{output}"
        )


def test_archive_list_restore_and_hard_delete_absence(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Archive is reversible, listed separately, and has no hard-delete route."""
    system_api = SystemV1Api(admin_api_client)
    _set_retention(system_api, 30)
    token, _, agent_id = create_chat_session_with_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    session_id = _create_secondary_session(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
    )
    chat_api = ChatV1Api(public_api_client)
    headers = _headers(token)

    before = chat_api.chat_v1_list_agent_sessions(agent_id, _headers=headers)
    assert before.current_archive_retention_days == 30
    assert any(item.id == session_id for item in before.items)

    chat_api.chat_v1_archive_agent_session(
        agent_id,
        session_id,
        _headers=headers,
    )

    active = chat_api.chat_v1_list_agent_sessions(agent_id, _headers=headers)
    archived = chat_api.chat_v1_list_archived_agent_sessions(
        agent_id,
        _headers=headers,
    )
    assert all(item.id != session_id for item in active.items)
    archived_item = next(item for item in archived.items if item.id == session_id)
    assert archived_item.archived_at is not None
    assert archived_item.archive_retention_days_snapshot == 30
    assert archived_item.purge_after is not None

    hard_delete = requests.delete(
        f"{azents_public_server_url}/chat/v1/sessions/{session_id}",
        headers=headers,
        timeout=10,
    )
    assert hard_delete.status_code in {404, 405}

    restored = chat_api.chat_v1_restore_agent_session(
        agent_id,
        session_id,
        _headers=headers,
    )
    assert restored.status == "active"
    assert restored.archived_at is None
    assert restored.purge_after is None
    assert restored.archive_retention_days_snapshot is None

    active_after_restore = chat_api.chat_v1_list_agent_sessions(
        agent_id,
        _headers=headers,
    )
    archived_after_restore = chat_api.chat_v1_list_archived_agent_sessions(
        agent_id,
        _headers=headers,
    )
    assert any(item.id == session_id for item in active_after_restore.items)
    assert all(item.id != session_id for item in archived_after_restore.items)


def test_zero_day_archive_waits_for_scheduler_purge(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_container: DockerContainer,
) -> None:
    """Zero-day archive remains visible until the purge scheduler owns deletion."""
    system_api = SystemV1Api(admin_api_client)
    _set_retention(system_api, 0)
    try:
        token, _, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        session_id = _create_secondary_session(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
        )
        chat_api = ChatV1Api(public_api_client)
        headers = _headers(token)

        chat_api.chat_v1_archive_agent_session(
            agent_id,
            session_id,
            _headers=headers,
        )
        archived_before_purge = chat_api.chat_v1_list_archived_agent_sessions(
            agent_id,
            _headers=headers,
        )
        archived_item = next(
            item for item in archived_before_purge.items if item.id == session_id
        )
        assert archived_item.archive_retention_days_snapshot == 0
        assert archived_item.purge_after is not None

        _run_scheduler_task(
            azents_admin_server_container,
            task_key="archived_session_purge",
        )

        archived_after_purge = chat_api.chat_v1_list_archived_agent_sessions(
            agent_id,
            _headers=headers,
        )
        assert all(item.id != session_id for item in archived_after_purge.items)
        get_deleted = requests.get(
            f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=headers,
            timeout=10,
        )
        assert get_deleted.status_code == 404
    finally:
        _set_retention(system_api, 30)
