"""Optional native mutation contracts, separate from complete read-only backends."""

import dataclasses
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from azents.core.vfs import VfsLocation, parse_vfs_exact_uri, parse_vfs_search_uri
from azents.services.vfs_read import (
    VfsReadAuthorityValidator,
    VfsReadBackend,
    VfsReadContext,
    VfsReadError,
)


class VfsMutationError(ValueError):
    """Stable mutation rejection with no implication of Runtime fallback."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclasses.dataclass(frozen=True)
class VfsMutationCapabilities:
    """Ordinary mutation and all-or-none patch are independently declared."""

    mutation: bool
    atomic_patch: bool


@dataclasses.dataclass(frozen=True)
class VfsWriteRequest:
    location: VfsLocation
    content: str
    overwrite: bool


@dataclasses.dataclass(frozen=True)
class VfsEditRequest:
    location: VfsLocation
    old_string: str
    new_string: str
    replace_all: bool


@dataclasses.dataclass(frozen=True)
class VfsDeleteRequest:
    location: VfsLocation


type VfsMutationRequest = VfsWriteRequest | VfsEditRequest | VfsDeleteRequest


@dataclasses.dataclass(frozen=True)
class VfsAtomicPatchRequest:
    """Canonical base and exact V4A bytes; backend preflights every target."""

    base: VfsLocation
    patch: str


@dataclasses.dataclass(frozen=True)
class VfsFileObservation:
    """Per-target actual content observed in this execution."""

    uri: str
    content: str | None


@dataclasses.dataclass(frozen=True)
class VfsMutationPreconditions:
    """Exact target observations frozen before queued operations await."""

    files: tuple[VfsFileObservation, ...]


@dataclasses.dataclass(frozen=True)
class VfsMutationInvocation:
    """Canonical tool-call identity; it does not grant file access."""

    tool_call_id: str


@dataclasses.dataclass(frozen=True)
class VfsMutationResult:
    """Safe metadata for a committed current-file mutation."""

    uris: tuple[str, ...]
    file_count: int
    byte_count: int


@runtime_checkable
class VfsMutationBackend[PrincipalT = VfsReadContext](Protocol):
    """Optional ordinary write/edit/delete interface, with no read-backend stubs."""

    def freeze_mutation(
        self, principal: PrincipalT, request: VfsMutationRequest
    ) -> VfsMutationPreconditions:
        """Capture existing-target evidence before any queued operation awaits I/O."""
        ...

    async def mutate(
        self,
        principal: PrincipalT,
        request: VfsMutationRequest,
        preconditions: VfsMutationPreconditions,
        invocation: VfsMutationInvocation,
    ) -> VfsMutationResult:
        """Reauthorize and commit natively, without Runtime materialization."""
        ...


@runtime_checkable
class VfsAtomicPatchBackend[PrincipalT = VfsReadContext](Protocol):
    """Separately optional patch support; single-file mutation needs no patch stub."""

    def freeze_patch(
        self, principal: PrincipalT, request: VfsAtomicPatchRequest
    ) -> VfsMutationPreconditions:
        """Validate all targets in one domain and freeze their read evidence."""
        ...

    async def atomic_patch(
        self,
        principal: PrincipalT,
        request: VfsAtomicPatchRequest,
        preconditions: VfsMutationPreconditions,
        invocation: VfsMutationInvocation,
    ) -> VfsMutationResult:
        """Commit all hunks and files or change nothing."""
        ...


@dataclasses.dataclass(frozen=True)
class VfsBackendRegistration[PrincipalT = VfsReadContext]:
    """One native backend's explicit optional interfaces and capability claims."""

    read_backend: VfsReadBackend[PrincipalT]
    mutation_backend: VfsMutationBackend[PrincipalT] | None
    patch_backend: VfsAtomicPatchBackend[PrincipalT] | None
    capabilities: VfsMutationCapabilities

    def __post_init__(self) -> None:
        actual_mutation = isinstance(self.read_backend, VfsMutationBackend)
        actual_patch = isinstance(self.read_backend, VfsAtomicPatchBackend)
        if (
            self.capabilities.mutation != actual_mutation
            or self.capabilities.atomic_patch != actual_patch
            or (self.mutation_backend is not None) != actual_mutation
            or (self.patch_backend is not None) != actual_patch
            or (
                self.mutation_backend is not None
                and self.mutation_backend is not self.read_backend
            )
            or (
                self.patch_backend is not None
                and self.patch_backend is not self.read_backend
            )
        ):
            raise ValueError(
                "VFS mutation capabilities do not match native interfaces."
            )


class VfsMutationRegistry[PrincipalT = VfsReadContext]:
    """Immutable mount registration, with no synthetic writer for read-only mounts."""

    def __init__(
        self, registrations: Sequence[VfsBackendRegistration[PrincipalT]]
    ) -> None:
        self._registrations: dict[str, VfsBackendRegistration[PrincipalT]] = {}
        for registration in registrations:
            mount = registration.read_backend.mount
            if parse_vfs_search_uri(f"azents://{mount}").mount != mount:
                raise ValueError("Noncanonical VFS mutation mount registration.")
            if mount in self._registrations:
                raise ValueError(f"Duplicate VFS mutation mount: {mount}")
            self._registrations[mount] = registration

    def get(self, mount: str) -> VfsBackendRegistration[PrincipalT]:
        registration = self._registrations.get(mount)
        if registration is None:
            raise VfsMutationError(
                "unsupported_mount", "VFS mutation mount is unavailable."
            )
        return registration

    @property
    def writable_mounts(self) -> tuple[str, ...]:
        """Return only declared native ordinary writers, without backend I/O."""
        return tuple(
            sorted(
                mount
                for mount, registration in self._registrations.items()
                if registration.capabilities.mutation
            )
        )

    @property
    def patch_mounts(self) -> tuple[str, ...]:
        """Return declared all-or-none patch backends."""
        return tuple(
            sorted(
                mount
                for mount, registration in self._registrations.items()
                if registration.capabilities.atomic_patch
            )
        )


@dataclasses.dataclass(frozen=True)
class AdmittedVfsMutation[PrincipalT = VfsReadContext]:
    """Frozen operation, distinct from live backend observations after admission."""

    principal: PrincipalT
    backend: VfsMutationBackend[PrincipalT]
    request: VfsMutationRequest
    preconditions: VfsMutationPreconditions
    invocation: VfsMutationInvocation


@dataclasses.dataclass(frozen=True)
class AdmittedVfsPatch[PrincipalT = VfsReadContext]:
    principal: PrincipalT
    backend: VfsAtomicPatchBackend[PrincipalT]
    request: VfsAtomicPatchRequest
    preconditions: VfsMutationPreconditions
    invocation: VfsMutationInvocation


@dataclasses.dataclass(frozen=True)
class VfsMutationRouter[PrincipalT = VfsReadContext]:
    """Capability-first admission, frozen evidence and separate authority checks."""

    registry: VfsMutationRegistry[PrincipalT]
    authority_validator: VfsReadAuthorityValidator[PrincipalT]

    def admit(
        self,
        principal: PrincipalT,
        request: VfsMutationRequest,
        *,
        tool_call_id: str,
    ) -> AdmittedVfsMutation[PrincipalT]:
        canonical = parse_vfs_exact_uri(request.location.canonical)
        if canonical != request.location:
            raise VfsMutationError(
                "invalid_path", "VFS mutation path is not canonical."
            )
        registration = self.registry.get(canonical.mount)
        backend = registration.mutation_backend
        if backend is None:
            raise VfsMutationError("unsupported_operation", "VFS mount is read-only.")
        preconditions = backend.freeze_mutation(principal, request)
        return AdmittedVfsMutation(
            principal=principal,
            backend=backend,
            request=request,
            preconditions=preconditions,
            invocation=VfsMutationInvocation(tool_call_id),
        )

    async def execute(
        self, admitted: AdmittedVfsMutation[PrincipalT]
    ) -> VfsMutationResult:
        try:
            await self.authority_validator.validate(admitted.principal)
        except VfsReadError as error:
            raise VfsMutationError(error.code, error.message) from None
        return await admitted.backend.mutate(
            admitted.principal,
            admitted.request,
            admitted.preconditions,
            admitted.invocation,
        )

    def admit_patch(
        self,
        principal: PrincipalT,
        request: VfsAtomicPatchRequest,
        *,
        tool_call_id: str,
    ) -> AdmittedVfsPatch[PrincipalT]:
        if parse_vfs_search_uri(request.base.canonical) != request.base:
            raise VfsMutationError("invalid_path", "VFS patch base is not canonical.")
        backend = self.registry.get(request.base.mount).patch_backend
        if backend is None:
            raise VfsMutationError(
                "unsupported_operation", "VFS mount does not support atomic patch."
            )
        return AdmittedVfsPatch(
            principal=principal,
            backend=backend,
            request=request,
            preconditions=backend.freeze_patch(principal, request),
            invocation=VfsMutationInvocation(tool_call_id),
        )

    async def execute_patch(
        self, admitted: AdmittedVfsPatch[PrincipalT]
    ) -> VfsMutationResult:
        await self.authority_validator.validate(admitted.principal)
        return await admitted.backend.atomic_patch(
            admitted.principal,
            admitted.request,
            admitted.preconditions,
            admitted.invocation,
        )
