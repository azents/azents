"""Absence and finite recovery-closure checks for the removal-first snapshot."""

import ast
from pathlib import Path

_REPOSITORIES = Path(__file__).parent


_EXPECTED_HIERARCHY_OWNERS = {
    "subagent_tool_operations.py": {
        "spawn",
        "send_message",
        "followup_task",
        "interrupt",
    },
    "chat_operations.py": {"archive_agent_session", "restore_agent_session"},
    "chat_write_operations.py": {"request_session_stop"},
    "archived_session_purge_operations.py": {"prepare_root", "finalize"},
    "agent_decommission_operations.py": {"retire_root_tree"},
    "owner_lifecycle_operations.py": {"retire_root_tree"},
    "worker_session.py": {
        "cancel_pending_agent_run",
        "mark_session_agent_runs_terminal",
        "mark_agent_run_terminal_if_running",
        "mark_agent_run_stopped_for_user_stop",
    },
    "engine_run_finalization_operation.py": {
        "interrupt_before_turn",
        "complete_polled_run",
        "complete_model_run",
        "interrupt_after_tool_stop_if_running",
        "interrupt_turn_limit",
        "interrupt_model_stream",
        "complete_committed_scheduled_result",
    },
    "failed_run_finalization_operation.py": {"finalize"},
    "terminal_finalization.py": {"finalize_run"},
    "subagent_terminal_result.py": {"deliver_one"},
}


def test_hierarchy_retry_is_limited_to_complete_owning_operation_closure() -> None:
    observed: dict[str, set[str]] = {}
    for path in _REPOSITORIES.rglob("*.py"):
        if path.name.endswith("_test.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if any(
                isinstance(decorator, ast.Name)
                and decorator.id == "retry_hierarchy_operation"
                for decorator in node.decorator_list
            ):
                observed.setdefault(str(path.relative_to(_REPOSITORIES)), set()).add(
                    node.name
                )
    assert observed == _EXPECTED_HIERARCHY_OWNERS
    assert sum(len(entries) for entries in observed.values()) == 25


def test_inventoried_nonwaiting_acquisition_surfaces_are_removed() -> None:
    paths = [
        "agent_session/__init__.py",
        "historical_memory_consolidation/authority.py",
        "historical_memory_consolidation/drafts.py",
        "historical_memory_consolidation/lifecycle.py",
        "historical_memory_consolidation/cutover.py",
        "external_account_link/__init__.py",
        "external_account_oauth/repository.py",
        "external_channel/model_settings.py",
        "external_channel/repository.py",
    ]
    refusals: list[str] = []
    for relative in paths:
        path = _REPOSITORIES / relative
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "pg_try_advisory_xact_lock"
            ) or any(
                keyword.arg == "nowait"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            ):
                refusals.append(f"{relative}:{node.lineno}")
    assert not refusals, refusals
    assert (
        "lock_by_id_nowait"
        not in (_REPOSITORIES / "agent_session/__init__.py").read_text()
    )
