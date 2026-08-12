"""Persistent logical-Runtime interception CA generation and validation."""

import dataclasses
import hashlib
import re
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID, ObjectIdentifier

from azents_runtime_provider_kubernetes.owned_resources import validate_runtime_id

CA_PROFILE_VERSION = 1
CA_COMBINED_SECRET_KEY = "mitmproxy-ca.pem"
CA_PUBLIC_SECRET_KEY = "ca.crt"
_CA_PROFILE_OID = ObjectIdentifier("1.3.6.1.4.1.57264.1.1")
_CA_VALIDITY = timedelta(days=365)
_COMBINED_CA_PATTERN = re.compile(
    rb"\A"
    rb"(?P<private>-----BEGIN PRIVATE KEY-----\r?\n.+?"
    rb"-----END PRIVATE KEY-----\r?\n)"
    rb"(?P<certificate>-----BEGIN CERTIFICATE-----\r?\n.+?"
    rb"-----END CERTIFICATE-----\r?\n?)"
    rb"\Z",
    re.DOTALL,
)
_PUBLIC_CERTIFICATE_PATTERN = re.compile(
    rb"\A"
    rb"(?P<certificate>-----BEGIN CERTIFICATE-----\r?\n.+?"
    rb"-----END CERTIFICATE-----\r?\n?)"
    rb"\Z",
    re.DOTALL,
)


class InvalidRuntimeCa(ValueError):
    """Existing logical-Runtime CA material failed validation."""


@dataclasses.dataclass(frozen=True)
class RuntimeCaMaterial:
    """Validated public and proxy-only CA material."""

    profile_version: int
    combined_pem: bytes
    public_certificate_pem: bytes
    fingerprint: str
    not_valid_before: datetime
    not_valid_after: datetime


def generate_runtime_ca(runtime_id: str, *, now: datetime) -> RuntimeCaMaterial:
    """Generate initial CA material for a logical Runtime."""
    _require_aware_utc(now)
    subject = _expected_subject(validate_runtime_id(runtime_id))
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + _CA_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                private_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.UnrecognizedExtension(
                _CA_PROFILE_OID,
                str(CA_PROFILE_VERSION).encode("ascii"),
            ),
            critical=False,
        )
        .sign(private_key=private_key, algorithm=hashes.SHA256())
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = certificate.public_bytes(serialization.Encoding.PEM)
    return _material(
        combined_pem=private_pem + public_pem,
        public_pem=public_pem,
        certificate=certificate,
    )


def validate_runtime_ca(
    runtime_id: str,
    *,
    combined_pem: bytes,
    public_certificate_pem: bytes,
    expected_fingerprint: str | None,
) -> RuntimeCaMaterial:
    """Validate existing CA identity without regeneration."""
    safe_runtime_id = validate_runtime_id(runtime_id)
    try:
        combined_match = _COMBINED_CA_PATTERN.fullmatch(combined_pem)
        public_match = _PUBLIC_CERTIFICATE_PATTERN.fullmatch(public_certificate_pem)
        if combined_match is None or public_match is None:
            raise InvalidRuntimeCa("Runtime CA PEM is malformed")
        private_key = serialization.load_pem_private_key(
            combined_match.group("private"),
            password=None,
        )
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise InvalidRuntimeCa("Runtime CA private key must be RSA")
        certificate = x509.load_pem_x509_certificate(
            combined_match.group("certificate")
        )
        public_certificate = x509.load_pem_x509_certificate(
            public_match.group("certificate")
        )
    except (TypeError, ValueError, x509.DuplicateExtension) as error:
        raise InvalidRuntimeCa("Runtime CA PEM is malformed") from error
    certificate_public_key = certificate.public_key()
    if not isinstance(certificate_public_key, rsa.RSAPublicKey):
        raise InvalidRuntimeCa("Runtime CA certificate key must be RSA")
    if (
        private_key.key_size != 3072
        or certificate_public_key.key_size != 3072
        or private_key.public_key().public_numbers()
        != certificate_public_key.public_numbers()
    ):
        raise InvalidRuntimeCa("Runtime CA key and certificate mismatch")
    if certificate.public_bytes(serialization.Encoding.DER) != (
        public_certificate.public_bytes(serialization.Encoding.DER)
    ):
        raise InvalidRuntimeCa("Runtime CA public certificate mismatch")
    if certificate.subject != _expected_subject(safe_runtime_id):
        raise InvalidRuntimeCa("Runtime CA subject identity mismatch")
    if certificate.issuer != certificate.subject:
        raise InvalidRuntimeCa("Runtime CA must be self-issued")
    _validate_extensions(certificate)
    signature_hash_algorithm = certificate.signature_hash_algorithm
    if not isinstance(signature_hash_algorithm, hashes.SHA256):
        raise InvalidRuntimeCa("Runtime CA signature algorithm mismatch")
    try:
        certificate_public_key.verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            padding.PKCS1v15(),
            signature_hash_algorithm,
        )
    except InvalidSignature as error:
        raise InvalidRuntimeCa("Runtime CA self-signature is invalid") from error
    material = _material(
        combined_pem=combined_pem,
        public_pem=public_certificate_pem,
        certificate=certificate,
    )
    if (
        expected_fingerprint is not None
        and material.fingerprint != expected_fingerprint
    ):
        raise InvalidRuntimeCa("Runtime CA fingerprint mismatch")
    return material


def runtime_ca_secret_data(material: RuntimeCaMaterial) -> dict[str, bytes]:
    """Build the exact Secret data with public/private separation."""
    return {
        CA_COMBINED_SECRET_KEY: material.combined_pem,
        CA_PUBLIC_SECRET_KEY: material.public_certificate_pem,
    }


def _expected_subject(runtime_id: str) -> x509.Name:
    return x509.Name(
        (
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Azents"),
            x509.NameAttribute(
                NameOID.ORGANIZATIONAL_UNIT_NAME,
                "Runtime Interception CA",
            ),
            x509.NameAttribute(
                NameOID.COMMON_NAME,
                f"azents-runtime-{runtime_id}",
            ),
        )
    )


def _validate_extensions(certificate: x509.Certificate) -> None:
    try:
        constraints = certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
        usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
        profile = certificate.extensions.get_extension_for_oid(_CA_PROFILE_OID).value
    except x509.ExtensionNotFound as error:
        raise InvalidRuntimeCa("Runtime CA profile extension is missing") from error
    if not constraints.ca or constraints.path_length != 0:
        raise InvalidRuntimeCa("Runtime CA basic constraints mismatch")
    if not usage.key_cert_sign or not usage.crl_sign:
        raise InvalidRuntimeCa("Runtime CA key usage mismatch")
    if not isinstance(profile, x509.UnrecognizedExtension) or profile.value != str(
        CA_PROFILE_VERSION
    ).encode("ascii"):
        raise InvalidRuntimeCa("Runtime CA profile version mismatch")


def _material(
    *,
    combined_pem: bytes,
    public_pem: bytes,
    certificate: x509.Certificate,
) -> RuntimeCaMaterial:
    return RuntimeCaMaterial(
        profile_version=CA_PROFILE_VERSION,
        combined_pem=combined_pem,
        public_certificate_pem=public_pem,
        fingerprint=hashlib.sha256(
            certificate.public_bytes(serialization.Encoding.DER)
        ).hexdigest(),
        not_valid_before=certificate.not_valid_before_utc,
        not_valid_after=certificate.not_valid_after_utc,
    )


def _require_aware_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Runtime CA generation time must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError("Runtime CA generation time must resolve to UTC")
