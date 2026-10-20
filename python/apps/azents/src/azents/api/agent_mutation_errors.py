"""Translate lifecycle conflicts without disclosing internal deletion diagnostics."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from azents.core.agent_mutation import AgentMutationReadOnly, AgentMutationTargetMissing


async def _read_only(_request: Request, _error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": {
                "code": "agent_decommissioning",
                "message": "Agent is being deleted and is read-only.",
            }
        },
    )


async def _missing(_request: Request, _error: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Agent not found."})


def register_agent_mutation_errors(app: FastAPI) -> None:
    """Install typed conflict translation, not an HTTP-only lifecycle guard."""
    app.add_exception_handler(AgentMutationReadOnly, _read_only)
    app.add_exception_handler(AgentMutationTargetMissing, _missing)
