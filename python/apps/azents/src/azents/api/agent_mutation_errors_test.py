"""Authorized lifecycle conflicts have safe stable HTTP bodies."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.agent_mutation_errors import register_agent_mutation_errors
from azents.core.agent_mutation import AgentMutationReadOnly, AgentMutationTargetMissing


@pytest.mark.parametrize(
    "error,status,detail",
    [
        (
            AgentMutationReadOnly,
            409,
            {
                "code": "agent_decommissioning",
                "message": "Agent is being deleted and is read-only.",
            },
        ),
        (AgentMutationTargetMissing, 404, "Agent not found."),
    ],
)
def test_lifecycle_error_response(
    error: type[Exception], status: int, detail: str | dict[str, str]
) -> None:
    app = FastAPI()
    register_agent_mutation_errors(app)

    @app.post("/mutation")
    async def mutation() -> None:
        raise error("Internal diagnostic must never be exposed")

    with TestClient(app) as client:
        response = client.post("/mutation")
    assert response.status_code == status
    assert response.json() == {"detail": detail}
