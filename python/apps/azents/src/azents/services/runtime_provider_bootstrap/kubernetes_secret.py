"""Kubernetes Secret adapter for bootstrap-owned Provider credentials."""

import base64
import binascii
from typing import Protocol

from kubernetes_asyncio.client.models.v1_secret import V1Secret
from kubernetes_asyncio.client.rest import ApiException

_PROVIDER_ID_ANNOTATION = "azents.io/runtime-provider-id"


class KubernetesSecretApi(Protocol):
    """Narrow Kubernetes Secret operations required by credential bootstrap."""

    async def read_namespaced_secret(
        self,
        *,
        name: str,
        namespace: str,
    ) -> V1Secret:
        """Read one Secret."""
        ...

    async def patch_namespaced_secret(
        self,
        *,
        name: str,
        namespace: str,
        body: dict[str, object],
    ) -> V1Secret:
        """Patch one Secret."""
        ...


async def read_runtime_provider_credential(
    api: KubernetesSecretApi,
    *,
    namespace: str,
    secret_name: str,
    secret_key: str,
) -> str | None:
    """Read one optional Provider credential from a pre-created Secret."""
    try:
        secret = await api.read_namespaced_secret(
            name=secret_name,
            namespace=namespace,
        )
    except ApiException as error:
        if error.status == 404:
            raise RuntimeError(
                "Runtime Provider credential target Secret does not exist."
            ) from error
        raise
    encoded = (secret.data or {}).get(secret_key)
    if encoded is None:
        return None
    try:
        credential = base64.b64decode(encoded, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ValueError(
            "Runtime Provider credential Secret contains invalid data."
        ) from error
    if not credential:
        raise ValueError("Runtime Provider credential Secret is empty.")
    return credential


async def write_runtime_provider_credential(
    api: KubernetesSecretApi,
    *,
    namespace: str,
    secret_name: str,
    secret_key: str,
    provider_logical_id: str,
    credential: str,
) -> None:
    """Patch one credential key without replacing unrelated Secret data."""
    await api.patch_namespaced_secret(
        name=secret_name,
        namespace=namespace,
        body={
            "metadata": {
                "annotations": {
                    _PROVIDER_ID_ANNOTATION: provider_logical_id,
                }
            },
            "data": {
                secret_key: base64.b64encode(credential.encode()).decode(),
            },
        },
    )
