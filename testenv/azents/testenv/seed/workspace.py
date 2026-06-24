"""Workspace seeding helpers.

`Workspace` is constructed with `TestenvConfig` and exposes `create()`. The
public client can create a workspace without a separate add_member call in this
Phase 3 feasibility path.

Normally use this through `TestenvClient.workspace`.
"""

from dataclasses import dataclass

from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest

from testenv.runtime_config import TestenvConfig

from .client import public_client
from .types import User
from .types import Workspace as WorkspaceModel
from .unique import unique


@dataclass(frozen=True)
class Workspace:
    """Workspace seed service used by `TestenvClient.workspace`."""

    config: TestenvConfig

    def create(
        self,
        owner: User,
        *,
        handle: str | None = None,
        name: str | None = None,
    ) -> WorkspaceModel:
        """Create a workspace with `POST /workspace/v1/workspaces`.

        When handle/name are None, generate them with a unique() suffix. Use
        owner.access_token as the Bearer token.
        """
        suffix = unique()
        actual_handle = handle if handle is not None else f"ws-{suffix}"
        actual_name = name if name is not None else f"Test WS {suffix}"

        api = WorkspaceV1Api(public_client(self.config))
        api.workspace_v1_create_workspace(
            CreateWorkspaceRequest(
                workspace_name=actual_name,
                workspace_handle=actual_handle,
                owner_name=f"Owner {suffix}",
            ),
            _headers={"Authorization": f"Bearer {owner.access_token}"},
        )

        return WorkspaceModel(handle=actual_handle, name=actual_name, owner=owner)
