"""Durable client tool-call admission identity."""


def tool_call_external_id(run_id: str, call_id: str) -> str:
    """Return the deterministic durable identity for one client tool call."""
    return f"tool-call:{run_id}:{call_id}"
