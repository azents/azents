"""Safe metadata and disposable TLS material for the representative Proxy E2E."""

import datetime
import ipaddress
from dataclasses import dataclass
from pathlib import Path

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pydantic import BaseModel, TypeAdapter
from testcontainers.core.container import DockerContainer

RESOLVER_KEY = "synthetic-e2e-resolver-only-credential-32-characters"


class ProviderObservation(BaseModel):
    model: str
    account_hash: str
    max_output_tokens: int | None
    streaming: bool


_OBSERVATIONS = TypeAdapter(list[ProviderObservation])


@dataclass(frozen=True)
class ProxyFixture:
    base_url: str
    control_url: str
    certificate: Path
    container: DockerContainer

    def journal(self) -> list[ProviderObservation]:
        response = requests.get(
            self.control_url + "/fixture/journal",
            verify=str(self.certificate),
            timeout=10,
        )
        response.raise_for_status()
        return _OBSERVATIONS.validate_json(response.content)

    def release(self) -> None:
        response = requests.post(
            self.control_url + "/fixture/release",
            verify=str(self.certificate),
            timeout=10,
        )
        response.raise_for_status()


def write_tls_material(directory: Path, host: str) -> None:
    """A self-signed test CA authenticates both inside- and outside-container host."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Proxy E2E authority facade")]
    )
    names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    try:
        names.append(x509.IPAddress(ipaddress.ip_address(host)))
    except ValueError:
        names.append(x509.DNSName(host))
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .sign(key, hashes.SHA256())
    )
    directory.chmod(0o755)
    cert_path, key_path = directory / "certificate.pem", directory / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    # Synthetic disposable material must be readable by the nonroot product UID.
    cert_path.chmod(0o644)
    key_path.chmod(0o644)
