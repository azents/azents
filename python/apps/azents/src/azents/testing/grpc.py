"""Typed gRPC test doubles."""

from collections.abc import Iterable, Mapping, Sequence
from typing import NoReturn

import grpc

type GrpcMetadata = grpc.aio.Metadata | Sequence[tuple[str, str | bytes]]


class FakeGrpcContext[RequestT, ResponseT](
    grpc.aio.ServicerContext[RequestT, ResponseT]
):
    """Provide a concrete typed gRPC service context for direct-call tests."""

    def __init__(
        self,
        *,
        metadata: GrpcMetadata = (),
        peer: str = "test-peer",
    ) -> None:
        self._metadata = (
            metadata
            if isinstance(metadata, grpc.aio.Metadata)
            else grpc.aio.Metadata(*metadata)
        )
        self._peer = peer
        self._cancelled = False
        self._code: grpc.StatusCode | None = None
        self._details = ""
        self._trailing_metadata = grpc.aio.Metadata()

    async def read(self) -> RequestT:
        """Reject reads not configured by the test."""
        raise NotImplementedError

    async def write(self, message: ResponseT) -> None:
        """Reject writes not configured by the test."""
        del message
        raise NotImplementedError

    async def send_initial_metadata(self, initial_metadata: GrpcMetadata) -> None:
        """Accept initial metadata without transport side effects."""
        del initial_metadata

    async def abort(
        self,
        code: grpc.StatusCode,
        details: str = "",
        trailing_metadata: GrpcMetadata = (),
    ) -> NoReturn:
        """Raise instead of aborting a real RPC."""
        del trailing_metadata
        raise RuntimeError(f"{code.name}: {details}")

    async def abort_with_status(self, status: grpc.Status) -> NoReturn:
        """Raise instead of aborting a real RPC."""
        raise RuntimeError(str(status))

    def set_trailing_metadata(self, trailing_metadata: GrpcMetadata) -> None:
        """Record trailing metadata."""
        self._trailing_metadata = (
            trailing_metadata
            if isinstance(trailing_metadata, grpc.aio.Metadata)
            else grpc.aio.Metadata(*trailing_metadata)
        )

    def invocation_metadata(self) -> grpc.aio.Metadata:
        """Return configured request metadata."""
        return self._metadata

    def set_code(self, code: grpc.StatusCode) -> None:
        """Record the response status code."""
        self._code = code

    def set_details(self, details: str) -> None:
        """Record response details."""
        self._details = details

    def set_compression(self, compression: grpc.Compression) -> None:
        """Accept compression configuration without transport side effects."""
        del compression

    def disable_next_message_compression(self) -> None:
        """Accept message compression changes without transport side effects."""

    def peer(self) -> str:
        """Return the configured peer identity."""
        return self._peer

    def peer_identities(self) -> Iterable[bytes] | None:
        """Return no authenticated transport identities."""
        return None

    def peer_identity_key(self) -> str | None:
        """Return no authenticated transport identity key."""
        return None

    def auth_context(self) -> Mapping[str, Iterable[bytes]]:
        """Return an empty transport authentication context."""
        return {}

    def cancelled(self) -> bool:
        """Return whether the test marked the RPC as cancelled."""
        return self._cancelled

    def set_cancelled(self, cancelled: bool) -> None:
        """Set the test cancellation state."""
        self._cancelled = cancelled
