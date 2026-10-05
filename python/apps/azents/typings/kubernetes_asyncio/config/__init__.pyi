"""Type stubs for kubernetes_asyncio.config.

Declare kubeconfig loading and in-cluster configuration operations.
"""

from typing import Any

from kubernetes_asyncio.client import ApiClient

async def new_client_from_config_dict(
    config_dict: dict[str, Any] | None = None,
    context: str | None = None,
    **kwargs: Any,
) -> ApiClient: ...
async def load_kube_config(
    config_file: str | None = None,
    context: str | None = None,
    **kwargs: Any,
) -> None: ...
def load_incluster_config() -> None: ...
