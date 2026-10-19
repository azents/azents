"""Real HTTP and DB contracts for read-only Session Routine inspection."""

from typing import Literal

import httpx
import pytest

from azents.api.public.chat.v1.route_test_support import focused_chat_app
from azents.core.auth.deps import CurrentUser, get_current_user
from azents.core.enums import AgentRunStatus
from azents.core.routine import RoutineObjectiveOutcome
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.routine.completion_test import NOW, fixture, work
from azents.repos.routine.inspection_test import inspection, member
from azents.repos.routine.retry_test import _seed
from azents.services.chat_write_test import _service
from azents.services.routine.inspection import RoutineInspectionService

LIST_PATH = "/agents/{agent_id}/sessions/{session_id}/routines"
DETAIL_PATH = f"{LIST_PATH}/{{slug}}"


@pytest.mark.parametrize(
    "state", ["started", "complete_silent", "complete_failed_notify"]
)
async def test_read_only_routine_http_preserves_semantic_work_and_delivery(
    rdb_session_manager: SessionManager[WriteSession],
    *,
    state: Literal["started", "complete_silent", "complete_failed_notify"],
) -> None:
    f = await fixture(rdb_session_manager)
    user_id = await member(rdb_session_manager, f.scope)
    if state != "started":
        await f.repository.complete(
            scope=f.scope,
            authority=f.authority,
            slug=f.definitions[0].slug,
            execution_id=f.states[0].context.execution_id,
            work=work(
                notify=state == "complete_failed_notify",
                outcome=RoutineObjectiveOutcome.FAILED
                if state == "complete_failed_notify"
                else RoutineObjectiveOutcome.FINISHED,
            ),
            now=NOW,
        )
    service = RoutineInspectionService(repository=inspection(rdb_session_manager))
    app = focused_chat_app(LIST_PATH, DETAIL_PATH)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=user_id, session_id="fixture-auth"
    )
    app.dependency_overrides[RoutineInspectionService] = lambda: service
    path = f"/chat/v1/agents/{f.scope.agent_id}/sessions/{f.scope.session_id}/routines"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        inventory = await client.get(path)
        assert inventory.status_code == 200
        assert len(inventory.json()["items"]) == 2
        detail = await client.get(f"{path}/{f.definitions[0].slug}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["routine"]["content"] == f.definitions[0].content.model_dump(
            mode="json"
        )
        assert "scope" not in body["routine"]
        assert set(body["execution"]) == {
            "execution_id",
            "phase",
            "admitted_at",
            "started_at",
            "completed_at",
        }
        assert body["execution"]["phase"] == (
            "started" if state == "started" else "completed"
        )
        if state == "started":
            assert body["records"] == []
        else:
            record = body["records"][0]
            assert record["work"]["objective_outcome"] == (
                "failed" if state == "complete_failed_notify" else "finished"
            )
            assert record["work"]["notify"] == (state == "complete_failed_notify")
            assert (record["work"]["message"] is not None) == (
                state == "complete_failed_notify"
            )
            assert record["delivery_status"] == (
                "unobserved" if state == "complete_failed_notify" else "not_requested"
            )
        assert (await client.get(f"{path}/missing-routine")).status_code == 404
        assert (await client.post(path, json={})).status_code == 405
        assert (
            await client.delete(f"{path}/{f.definitions[0].slug}")
        ).status_code == 405
        wrong = path.replace(f.scope.agent_id, "another-agent")
        assert (await client.get(wrong)).status_code == 404
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id="not-a-workspace-member", session_id="fixture-auth"
        )
        assert (await client.get(path)).status_code == 404
        assert (await client.get(f"{path}/{f.definitions[0].slug}")).status_code == 404


async def test_incomplete_read_remains_truthful_after_host_failure_and_retry_rebind(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A started occurrence is incomplete, not evidence of an active host Run."""
    seeded = await _seed(rdb_session_manager)
    f = seeded.routine
    user_id = await member(rdb_session_manager, f.scope)
    app = focused_chat_app(LIST_PATH, DETAIL_PATH)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=user_id, session_id="fixture-auth"
    )
    service = RoutineInspectionService(repository=inspection(rdb_session_manager))
    app.dependency_overrides[RoutineInspectionService] = lambda: service
    state = f.states[1]
    path = (
        f"/chat/v1/agents/{f.scope.agent_id}/sessions/{f.scope.session_id}"
        f"/routines/{state.context.candidate.slug}"
    )
    async with rdb_session_manager() as session:
        runs = await f.repository.runs.list_by_input_event_id(
            session, event_id=seeded.input_event_id
        )
        assert len(runs) == 1 and runs[0].status is AgentRunStatus.FAILED
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        failed = await client.get(path)
        assert failed.status_code == 200
        body = failed.json()
        assert body["execution"]["phase"] == "started"
        assert body["execution"]["completed_at"] is None
        assert body["records"] == []
        assert "current_run_id" not in body["execution"]
        retry = await _service(rdb_session_manager).create_idempotent_failed_run_retry(
            agent_id=f.scope.agent_id,
            session_id=f.scope.session_id,
            user_id=seeded.user_id,
            client_request_id="routine-inspection-retry",
            failed_event_id=seeded.failed_event_id,
            payload={"failed_event_id": seeded.failed_event_id},
        )
        assert retry.request.created
        async with rdb_session_manager() as session:
            runs = await f.repository.runs.list_by_input_event_id(
                session, event_id=seeded.input_event_id
            )
            assert len(runs) == 2
            assert runs[0].status is AgentRunStatus.FAILED
            assert runs[1].status is AgentRunStatus.PENDING
            rebound = await f.repository.states.get_occurrence(
                session,
                scope=f.scope,
                slug=state.context.candidate.slug,
                execution_id=state.context.execution_id,
            )
            assert rebound is not None
            assert rebound.state.current_run_id == runs[1].id
            assert rebound.state.phase == "started"
        pending = await client.get(path)
        assert pending.status_code == 200 and pending.json() == body
