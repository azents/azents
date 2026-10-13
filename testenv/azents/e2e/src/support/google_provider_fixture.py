"""Ephemeral fixed-host TLS prerequisite, isolated from product configuration."""

import dataclasses
import datetime
from pathlib import Path

import certifi
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from testcontainers.core.container import DockerContainer

from support.google_provider_fake import HOSTS

CONTAINER_ROOT = "/e2e-google"


@dataclasses.dataclass(frozen=True)
class GoogleProviderFixture:
    container: DockerContainer
    material_root: Path
    control_url: str


def write_material(root: Path) -> None:
    """Create test-only signing identities and a TLS CA for exact fixture hosts."""
    now = datetime.datetime.now(datetime.UTC)
    for label in ("tls", "identity"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Google E2E")]
        )
        builder = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=2))
        )
        if label == "tls":
            builder = builder.add_extension(
                x509.BasicConstraints(ca=True, path_length=None), critical=True
            ).add_extension(
                x509.SubjectAlternativeName([x509.DNSName(host) for host in HOSTS]),
                critical=False,
            )
        certificate = builder.sign(key, hashes.SHA256())
        (root / (label + ".key")).write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        (root / (label + ".pem")).write_bytes(
            certificate.public_bytes(serialization.Encoding.PEM)
        )
        (root / (label + ".key")).chmod(0o600)
    (root / "trust.pem").write_bytes(
        Path(certifi.where()).read_bytes() + (root / "tls.pem").read_bytes()
    )


def configure_trust(
    container: DockerContainer, fixture: GoogleProviderFixture | None
) -> None:
    if fixture is None:
        return
    container.with_volume_mapping(
        str(fixture.material_root / "trust.pem"), CONTAINER_ROOT + "/trust.pem", "ro"
    )
    container.with_env("SSL_CERT_FILE", CONTAINER_ROOT + "/trust.pem")
    container.with_env("REQUESTS_CA_BUNDLE", CONTAINER_ROOT + "/trust.pem")
