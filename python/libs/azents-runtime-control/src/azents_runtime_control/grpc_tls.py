"""Shared gRPC client transport security configuration."""

import dataclasses
from collections.abc import Sequence

import grpc


@dataclasses.dataclass(frozen=True)
class GrpcClientTlsConfig:
    """Trusted root certificates for an authenticated gRPC server."""

    root_certificates: bytes

    def __post_init__(self) -> None:
        """Reject an empty trust bundle."""
        if not self.root_certificates.strip():
            raise ValueError("root_certificates must not be empty")


def create_grpc_aio_channel(
    endpoint: str,
    *,
    tls: GrpcClientTlsConfig | None,
    allow_insecure: bool,
    options: Sequence[tuple[str, int | str]] = (),
) -> grpc.aio.Channel:
    """Create a secure channel unless insecure transport is explicitly allowed."""
    if tls is not None:
        credentials = grpc.ssl_channel_credentials(
            root_certificates=tls.root_certificates
        )
        if options:
            return grpc.aio.secure_channel(endpoint, credentials, options=options)
        return grpc.aio.secure_channel(endpoint, credentials)
    if allow_insecure:
        if options:
            return grpc.aio.insecure_channel(endpoint, options=options)
        return grpc.aio.insecure_channel(endpoint)
    raise ValueError(
        "gRPC TLS configuration is required unless insecure transport is "
        "explicitly allowed"
    )


__all__ = ["GrpcClientTlsConfig", "create_grpc_aio_channel"]
