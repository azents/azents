"""Runtime interception trust preparation."""

import os
import re
import ssl
import tempfile
from collections.abc import Mapping
from pathlib import Path

_PUBLIC_CA_PATH = Path("/var/run/secrets/azents/runtime-network/ca.crt")
_SYSTEM_CA_BUNDLE_PATH = Path("/etc/ssl/certs/ca-certificates.crt")
_WRITABLE_CA_BUNDLE_PATH = Path("/var/run/azents-runtime/trust/ca-bundle.crt")
_CERTIFICATE_PATTERN = re.compile(
    rb"-----BEGIN CERTIFICATE-----\r?\n"
    rb".+?"
    rb"-----END CERTIFICATE-----\r?\n?",
    re.DOTALL,
)
_TRUST_ENVIRONMENT_NAMES = (
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "GIT_SSL_CAINFO",
    "NODE_EXTRA_CA_CERTS",
)


def prepare_runner_trust_environment() -> Mapping[str, str]:
    """Prepare interception trust only when the fixed public-CA mount exists."""
    if not _PUBLIC_CA_PATH.exists():
        return {}
    return prepare_trust_bundle(
        public_ca_path=_PUBLIC_CA_PATH,
        system_ca_bundle_path=_SYSTEM_CA_BUNDLE_PATH,
        writable_ca_bundle_path=_WRITABLE_CA_BUNDLE_PATH,
    )


def prepare_trust_bundle(
    *,
    public_ca_path: Path,
    system_ca_bundle_path: Path,
    writable_ca_bundle_path: Path,
) -> Mapping[str, str]:
    """Validate one public CA and append it to the image trust roots atomically."""
    public_ca_pem = public_ca_path.read_bytes()
    _validate_single_public_certificate(public_ca_pem)
    system_bundle = system_ca_bundle_path.read_bytes()
    if not system_bundle.strip():
        raise RuntimeError("Runner system CA bundle is empty")

    writable_ca_bundle_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    bundle = system_bundle.rstrip() + b"\n" + public_ca_pem.strip() + b"\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=writable_ca_bundle_path.parent,
        prefix=".ca-bundle.",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(bundle)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.chmod(0o600)
        ssl.create_default_context(cafile=temporary_path)
        temporary_path.replace(writable_ca_bundle_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    bundle_path = str(writable_ca_bundle_path)
    return {name: bundle_path for name in _TRUST_ENVIRONMENT_NAMES}


def _validate_single_public_certificate(public_ca_pem: bytes) -> None:
    if b"PRIVATE KEY" in public_ca_pem:
        raise RuntimeError("Runner interception trust must not contain a private key")
    matches = list(_CERTIFICATE_PATTERN.finditer(public_ca_pem))
    if len(matches) != 1:
        raise RuntimeError(
            "Runner interception trust must contain exactly one certificate"
        )
    prefix = public_ca_pem[: matches[0].start()]
    suffix = public_ca_pem[matches[0].end() :]
    if prefix.strip() or suffix.strip():
        raise RuntimeError("Runner interception trust contains unexpected PEM data")
    try:
        ssl.PEM_cert_to_DER_cert(matches[0].group().decode("ascii"))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=matches[0].group().decode("ascii"))
    except (UnicodeDecodeError, ValueError, ssl.SSLError) as error:
        raise RuntimeError(
            "Runner interception trust certificate is invalid"
        ) from error
