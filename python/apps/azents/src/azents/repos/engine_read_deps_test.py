"""Dependency graph checks for required concrete completed Engine collaborators."""

from typing import Annotated

from fastapi import Depends
from fastapi.dependencies.utils import get_dependant

from azents.repos.engine_read import (
    EngineInvokeReadRepository,
    EngineModelReadRepository,
    EngineToolkitReadRepository,
)
from azents.repos.engine_read_deps import (
    get_engine_invoke_read_repository,
    get_engine_model_read_repository,
    get_engine_toolkit_read_repository,
)
from azents.repos.worker_executor_read import WorkerExecutorReadRepository
from azents.services.agent_wait import AgentWaitService
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.model_metadata import ModelMetadataService


def _endpoint(
    invoke: Annotated[
        EngineInvokeReadRepository, Depends(get_engine_invoke_read_repository)
    ],
    model: Annotated[
        EngineModelReadRepository, Depends(get_engine_model_read_repository)
    ],
    toolkit: Annotated[
        EngineToolkitReadRepository, Depends(get_engine_toolkit_read_repository)
    ],
    tokens: Annotated[EngineRuntimeTokenResolver, Depends(EngineRuntimeTokenResolver)],
    metadata: Annotated[ModelMetadataService, Depends(ModelMetadataService)],
    wait: Annotated[AgentWaitService, Depends(AgentWaitService)],
    worker_reads: Annotated[
        WorkerExecutorReadRepository, Depends(WorkerExecutorReadRepository)
    ],
) -> None:
    """Expose the actual dependency graphs without fake optional collaborators."""


def test_completed_dependency_graph_builds_without_session_query_schema_leaks() -> None:
    graph = get_dependant(path="/phase32", call=_endpoint)
    assert len(graph.dependencies) == 7
    assert not graph.query_params and not graph.body_params
