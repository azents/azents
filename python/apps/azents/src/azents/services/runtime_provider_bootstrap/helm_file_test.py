"""Helm-file Runtime Provider bootstrap adapter tests."""

from pathlib import Path

import pytest

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderKind,
)

from .helm_file import (
    HelmFileRuntimeProviderBootstrapAdapter,
    RuntimeProviderBootstrapSourceDocumentError,
)

_SOURCE_KEY = "helm/default/azents"
_DIGEST = "a" * 64


def _write_source(path: Path, providers: str) -> None:
    """Write one Helm adapter source document fixture."""
    path.write_text(
        f"""apiVersion: azents.io/v1
source:
  key: {_SOURCE_KEY}
  revision: {_DIGEST}
  digest: {_DIGEST}
providers:
{providers}
""",
        encoding="utf-8",
    )


async def test_reads_enabled_kubernetes_declaration(tmp_path: Path) -> None:
    """A Helm document becomes one adapter-neutral non-secret declaration."""
    source_path = tmp_path / "providers.yaml"
    _write_source(
        source_path,
        """  - declarationKey: runtime-provider-kubernetes
    providerId: system-kubernetes
    kind: kubernetes
    initial:
      displayName: Kubernetes
      enabled: true
      availabilityMode: platform_wide
      setAsPlatformDefaultWhenUnset: true
    authentication:
      method: kubernetes_service_account
      subject: system:serviceaccount:azents:azents-runtime-provider
      namespace: azents
      serviceAccountName: azents-runtime-provider
      audience: azents-runtime-control
""",
    )

    snapshot = await HelmFileRuntimeProviderBootstrapAdapter(
        source_key=_SOURCE_KEY,
        path=source_path,
    ).read_snapshot()

    assert snapshot.source_key == _SOURCE_KEY
    assert snapshot.source_digest == _DIGEST
    assert len(snapshot.declarations) == 1
    declaration = snapshot.declarations[0]
    assert declaration.provider_logical_id == "system-kubernetes"
    assert declaration.kind == RuntimeProviderKind.KUBERNETES
    assert (
        declaration.availability_mode == RuntimeProviderAvailabilityMode.PLATFORM_WIDE
    )
    assert declaration.creation_seeds == {"set_as_platform_default_when_unset": True}
    assert declaration.authentication is not None
    assert declaration.authentication.subject == (
        "system:serviceaccount:azents:azents-runtime-provider"
    )
    assert declaration.authentication.audience == "azents-runtime-control"


async def test_reads_authoritative_empty_source(tmp_path: Path) -> None:
    """A disabled Kubernetes Provider remains an authoritative empty snapshot."""
    source_path = tmp_path / "providers.yaml"
    _write_source(source_path, "  []")

    snapshot = await HelmFileRuntimeProviderBootstrapAdapter(
        source_key=_SOURCE_KEY,
        path=source_path,
    ).read_snapshot()

    assert snapshot.declarations == ()


async def test_rejects_mismatched_service_account_subject(tmp_path: Path) -> None:
    """A typed authentication declaration must match its namespace and name."""
    source_path = tmp_path / "providers.yaml"
    _write_source(
        source_path,
        """  - declarationKey: runtime-provider-kubernetes
    providerId: system-kubernetes
    kind: kubernetes
    initial:
      displayName: Kubernetes
      enabled: true
      availabilityMode: platform_wide
    authentication:
      method: kubernetes_service_account
      subject: system:serviceaccount:wrong:subject
      namespace: azents
      serviceAccountName: azents-runtime-provider
      audience: azents-runtime-control
""",
    )

    with pytest.raises(RuntimeProviderBootstrapSourceDocumentError) as raised:
        await HelmFileRuntimeProviderBootstrapAdapter(
            source_key=_SOURCE_KEY,
            path=source_path,
        ).read_snapshot()

    assert raised.value.code == "source_file_invalid"


@pytest.mark.parametrize(
    ("document", "code"),
    (
        (
            """apiVersion: azents.io/v1
source:
  key: helm/other/azents
  revision: revision
  digest: digest
providers: []
""",
            "source_key_mismatch",
        ),
        (
            """apiVersion: azents.io/v1
source:
  key: helm/default/azents
  revision: revision
  digest: digest
providers:
  - declarationKey: runtime-provider-kubernetes
    providerId: system-kubernetes
    kind: kubernetes
    initial:
      displayName: Kubernetes
      enabled: true
      availabilityMode: platform_wide
      secret: forbidden
""",
            "source_file_invalid",
        ),
        ("apiVersion: [", "source_file_malformed"),
    ),
)
async def test_rejects_invalid_source_document(
    tmp_path: Path,
    document: str,
    code: str,
) -> None:
    """Malformed or secret-bearing source documents never reconcile."""
    source_path = tmp_path / "providers.yaml"
    source_path.write_text(document, encoding="utf-8")

    with pytest.raises(RuntimeProviderBootstrapSourceDocumentError) as raised:
        await HelmFileRuntimeProviderBootstrapAdapter(
            source_key=_SOURCE_KEY,
            path=source_path,
        ).read_snapshot()

    assert raised.value.code == code
