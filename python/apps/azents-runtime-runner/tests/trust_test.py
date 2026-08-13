"""Runtime interception trust tests."""

import ssl
from pathlib import Path

import pytest

from azents_runtime_runner.execution import DirectExecutionBackend
from azents_runtime_runner.trust import prepare_trust_bundle

_TRUST_ENVIRONMENT_NAMES = (
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "GIT_SSL_CAINFO",
    "NODE_EXTRA_CA_CERTS",
)
_TEST_PUBLIC_CERTIFICATE = """-----BEGIN CERTIFICATE-----
MIIDMTCCAhmgAwIBAgIUOi1CujoGK+9MKHXNjtgMVdXIdtowDQYJKoZIhvcNAQEL
BQAwIDEeMBwGA1UEAwwVYXplbnRzLXJ1bm5lci10ZXN0LWNhMB4XDTI2MDgxMjEx
NDUzMloXDTM2MDgwOTExNDUzMlowIDEeMBwGA1UEAwwVYXplbnRzLXJ1bm5lci10
ZXN0LWNhMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAplqlOVhksDre
ypvgzrV12L1Vx9pUmzCs8RacA0HtBPZoI0ONOC11Uk3iA2lClWqVIpbD4ef7WTlQ
OvNxBKKYuXf5XLIDxIXsv8UAy3glKPuqj48jf36wq8DklSotJAHAWLddnrbp32k+
xd9kDeao1VOEFWzPDxxjZikdHrOojZejy9AGHKIhT86zsvjI54mF83lGqSRo/efh
AJ27Y3qnXbBsDoepWsa02bQ45O5pl1P4ozQomuGUj8wRn+wNPi5DAfaAN0fGt8IY
qzQvvEB43DZLjLgUNDjmR9EIzm3HG7zcM+evzzFKlBKRWmUKXZMkQLWnTGp90pKo
GP8SbsJ0KwIDAQABo2MwYTAdBgNVHQ4EFgQU21ThJcxQ5nnmU4k448vnwquX3dsw
HwYDVR0jBBgwFoAU21ThJcxQ5nnmU4k448vnwquX3dswDwYDVR0TAQH/BAUwAwEB
/zAOBgNVHQ8BAf8EBAMCAQYwDQYJKoZIhvcNAQELBQADggEBAA+WM0u31xOiyZGM
PGWo/VTg8ruUt2mAfjjci1RinFoqo/PLsJNGI6Yt9tnoKafOtKPXr0Neqygiz4sg
llwpTqZXLm+QcAMlaTzglI7EpPCknnH1v1nguDHTfwGWzXexwq1pth0xD7Ssx7ep
8ZvG+EkkqxE9XTwV1QMT53MP5Ej6LA5kZxbSnK04eVQtvM7NpbP1OiV8lwrQjbzj
CYHMkgkNZXYfL71jfw5Y/NjJn+oSaWuH36wFGCGoGt6zJy54QQROTCIahC6P4X09
W1rOFbdheZKyaQLEPVCLV2XgttJCPFbH4/Y3+WQkPdOeCK9WVF++PcQ5WLsUbF1u
b95IQVg=
-----END CERTIFICATE-----
"""


def test_prepare_trust_bundle_preserves_system_roots_and_exports_all_clients(
    tmp_path: Path,
) -> None:
    public_ca = tmp_path / "mounted" / "ca.crt"
    public_ca.parent.mkdir()
    public_ca.write_text(_TEST_PUBLIC_CERTIFICATE)
    system_bundle = tmp_path / "system-ca.crt"
    system_bundle.write_text(_TEST_PUBLIC_CERTIFICATE)
    writable_bundle = tmp_path / "runtime" / "ca-bundle.crt"

    environment = prepare_trust_bundle(
        public_ca_path=public_ca,
        system_ca_bundle_path=system_bundle,
        writable_ca_bundle_path=writable_bundle,
    )

    assert writable_bundle.read_bytes().startswith(system_bundle.read_bytes().strip())
    assert writable_bundle.read_bytes().endswith(public_ca.read_bytes().strip() + b"\n")
    assert writable_bundle.stat().st_mode & 0o777 == 0o600
    assert environment == {
        name: str(writable_bundle) for name in _TRUST_ENVIRONMENT_NAMES
    }
    ssl.create_default_context(cafile=writable_bundle)
    assert not list(writable_bundle.parent.glob(".ca-bundle.*"))


@pytest.mark.parametrize(
    "content",
    [
        "not a certificate",
        _TEST_PUBLIC_CERTIFICATE + _TEST_PUBLIC_CERTIFICATE,
        _TEST_PUBLIC_CERTIFICATE
        + "-----BEGIN PRIVATE KEY-----\nprivate\n-----END PRIVATE KEY-----\n",
    ],
)
def test_prepare_trust_bundle_rejects_invalid_or_private_material(
    tmp_path: Path,
    content: str,
) -> None:
    public_ca = tmp_path / "ca.crt"
    public_ca.write_text(content)
    system_bundle = tmp_path / "system-ca.crt"
    system_bundle.write_text(_TEST_PUBLIC_CERTIFICATE)

    with pytest.raises(RuntimeError):
        prepare_trust_bundle(
            public_ca_path=public_ca,
            system_ca_bundle_path=system_bundle,
            writable_ca_bundle_path=tmp_path / "output" / "ca-bundle.crt",
        )

    assert not (tmp_path / "output" / "ca-bundle.crt").exists()


def test_direct_execution_backend_protects_provider_owned_trust_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", "/runner/default-ca.crt")
    backend = DirectExecutionBackend(
        inherited_environment={
            name: "/runtime/ca-bundle.crt" for name in _TRUST_ENVIRONMENT_NAMES
        }
    )

    environment = backend.agent_environment(
        workspace_path="/workspace",
        operation_environment={
            "SSL_CERT_FILE": "/operation/bypass-ca.crt",
            "TOOL_TOKEN": "tool-token",
        },
    )

    assert environment["TOOL_TOKEN"] == "tool-token"
    assert all(
        environment[name] == "/runtime/ca-bundle.crt"
        for name in _TRUST_ENVIRONMENT_NAMES
    )


def test_direct_execution_backend_without_trust_inputs_adds_no_trust_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in _TRUST_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)

    environment = DirectExecutionBackend().agent_environment(
        workspace_path="/workspace",
        operation_environment={},
    )

    assert all(name not in environment for name in _TRUST_ENVIRONMENT_NAMES)
