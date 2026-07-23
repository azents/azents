"""Kubernetes Runtime Provider credential Secret adapter tests."""

import base64
from typing import cast
from unittest.mock import AsyncMock

import pytest
from kubernetes_asyncio.client.models.v1_secret import V1Secret

from .kubernetes_secret import (
    KubernetesSecretApi,
    read_runtime_provider_credential,
    write_runtime_provider_credential,
)


async def test_reads_existing_credential() -> None:
    """The adapter decodes only the configured Secret key."""
    api = AsyncMock()
    api.read_namespaced_secret.return_value = V1Secret(
        data={
            "provider-credential": base64.b64encode(b"credential-value").decode(),
            "unrelated": base64.b64encode(b"preserved").decode(),
        }
    )

    credential = await read_runtime_provider_credential(
        cast(KubernetesSecretApi, api),
        namespace="azents",
        secret_name="provider-secret",
        secret_key="provider-credential",
    )

    assert credential == "credential-value"


async def test_rejects_empty_credential() -> None:
    """An explicitly empty Secret key cannot authenticate a Provider."""
    api = AsyncMock()
    api.read_namespaced_secret.return_value = V1Secret(data={"provider-credential": ""})

    with pytest.raises(ValueError, match="empty"):
        await read_runtime_provider_credential(
            cast(KubernetesSecretApi, api),
            namespace="azents",
            secret_name="provider-secret",
            secret_key="provider-credential",
        )


async def test_patches_only_target_key_and_provider_annotation() -> None:
    """Credential persistence does not replace unrelated Secret data."""
    api = AsyncMock()

    await write_runtime_provider_credential(
        cast(KubernetesSecretApi, api),
        namespace="azents",
        secret_name="provider-secret",
        secret_key="provider-credential",
        provider_logical_id="system-kubernetes",
        credential="new-credential",
    )

    api.patch_namespaced_secret.assert_awaited_once_with(
        name="provider-secret",
        namespace="azents",
        body={
            "metadata": {
                "annotations": {
                    "azents.io/runtime-provider-id": "system-kubernetes",
                }
            },
            "data": {
                "provider-credential": base64.b64encode(b"new-credential").decode(),
            },
        },
    )
