"""Kubernetes Runtime Provider credential Secret adapter tests."""

import base64
from typing import NamedTuple

import pytest
from kubernetes_asyncio.client.models.v1_secret import V1Secret

from .kubernetes_secret import (
    read_runtime_provider_credential,
    write_runtime_provider_credential,
)


class _SecretRead(NamedTuple):
    """Exact identity requested by a credential read."""

    name: str
    namespace: str


class _SecretPatch(NamedTuple):
    """Exact identity and payload submitted by a credential patch."""

    name: str
    namespace: str
    body: dict[str, object]


class _SecretApi:
    """Concrete awaitable adapter independent of SDK method declaration syntax."""

    def __init__(self, secret: V1Secret) -> None:
        self.secret = secret
        self.reads: list[_SecretRead] = []
        self.patches: list[_SecretPatch] = []

    async def read_namespaced_secret(self, *, name: str, namespace: str) -> V1Secret:
        """Record a completed read and return the configured Secret."""
        self.reads.append(_SecretRead(name=name, namespace=namespace))
        return self.secret

    async def patch_namespaced_secret(
        self, *, name: str, namespace: str, body: dict[str, object]
    ) -> V1Secret:
        """Record an awaited patch without contacting Kubernetes."""
        self.patches.append(_SecretPatch(name=name, namespace=namespace, body=body))
        return self.secret


async def test_reads_existing_credential() -> None:
    """The adapter decodes only the configured Secret key."""
    api = _SecretApi(
        V1Secret(
            data={
                "provider-credential": base64.b64encode(b"credential-value").decode(),
                "unrelated": base64.b64encode(b"preserved").decode(),
            }
        )
    )

    credential = await read_runtime_provider_credential(
        api,
        namespace="azents",
        secret_name="provider-secret",
        secret_key="provider-credential",
    )

    assert credential == "credential-value"
    assert api.reads == [_SecretRead(name="provider-secret", namespace="azents")]
    assert api.patches == []


async def test_rejects_empty_credential() -> None:
    """An explicitly empty Secret key cannot authenticate a Provider."""
    api = _SecretApi(V1Secret(data={"provider-credential": ""}))

    with pytest.raises(ValueError, match="empty"):
        await read_runtime_provider_credential(
            api,
            namespace="azents",
            secret_name="provider-secret",
            secret_key="provider-credential",
        )

    assert api.reads == [_SecretRead(name="provider-secret", namespace="azents")]
    assert api.patches == []


async def test_patches_only_target_key_and_provider_annotation() -> None:
    """Credential persistence does not replace unrelated Secret data."""
    api = _SecretApi(V1Secret())

    await write_runtime_provider_credential(
        api,
        namespace="azents",
        secret_name="provider-secret",
        secret_key="provider-credential",
        provider_logical_id="system-kubernetes",
        credential="new-credential",
    )

    assert api.reads == []
    assert api.patches == [
        _SecretPatch(
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
    ]
