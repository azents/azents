"""kubernetes_asyncio.config 타입 스텁.

kubeconfig 로드 및 in-cluster config 관련 함수를 선언한다.
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
