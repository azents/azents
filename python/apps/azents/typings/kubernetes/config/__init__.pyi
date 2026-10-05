"""kubernetes.config — kubeconfig type definitions."""

from typing import Any

from kubernetes.client import ApiClient

def new_client_from_config_dict(
    config_dict: dict[str, Any],
    context: str | None = None,
    **kwargs: Any,
) -> ApiClient: ...
