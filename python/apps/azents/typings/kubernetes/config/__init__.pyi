"""kubernetes.config — kubeconfig 관련 타입 정의."""

from typing import Any

from kubernetes.client import ApiClient

def new_client_from_config_dict(
    config_dict: dict[str, Any],
    context: str | None = None,
    **kwargs: Any,
) -> ApiClient: ...
