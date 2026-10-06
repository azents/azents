"""One generic mutation tool surface over separate native Runtime/VFS adapters."""

import dataclasses
from collections.abc import Callable, Mapping
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, ValidationError

from azents.core.vfs import (
    VfsLocation,
    VfsUriError,
    parse_vfs_exact_uri,
    parse_vfs_search_uri,
)
from azents.engine.run.client_tool_compatibility import ClientToolModelProfile
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
    FunctionToolSpec,
    FunctionToolWireVariant,
)
from azents.engine.tooling.execution_context import ClientToolExecutionContext
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.apply_patch import (
    GPT_V4A_APPLY_PATCH_PROMPT,
    GPT_V4A_PLAINTEXT_CUSTOM_APPLY_PATCH_PROMPT,
    ApplyPatchInput,
    ApplyPatchPlaintextInputError,
    parse_plaintext_custom_apply_patch_input,
)
from azents.engine.tools.delete_file import DeleteFileInput
from azents.engine.tools.edit import EditInput
from azents.engine.tools.write import WriteInput
from azents.services.vfs_mutation import (
    VfsAtomicPatchRequest,
    VfsDeleteRequest,
    VfsEditRequest,
    VfsMutationError,
    VfsMutationRequest,
    VfsMutationRouter,
    VfsWriteRequest,
)
from azents.services.vfs_read import VfsReadContext, VfsReadError


@runtime_checkable
class RuntimeMutationToolProvider(Protocol):
    """Optional lazy Runtime bridge for the generic file-tool owner."""

    def make_mutation_tools(self) -> list[FunctionTool]:
        """Return guarded adapters without resolving or starting Runtime."""
        ...


class RoutedWriteInput(WriteInput):
    path: str = Field(
        description="Absolute Runtime path or canonical writable VFS URI."
    )


class RoutedEditInput(EditInput):
    path: str = Field(
        description="Absolute Runtime path or canonical writable VFS URI."
    )


class RoutedDeleteInput(DeleteFileInput):
    path: str = Field(
        description="Absolute Runtime path or canonical writable VFS URI."
    )


class RoutedApplyPatchInput(ApplyPatchInput):
    base_path: str = Field(
        description=(
            "Absolute Runtime directory or canonical atomic-writable VFS base URI."
        )
    )


@dataclasses.dataclass(frozen=True)
class RoutedMutationTools[PrincipalT = VfsReadContext]:
    """Freeze VFS evidence before awaiting, with no rejected-VFS Runtime fallback."""

    principal: PrincipalT
    router: VfsMutationRouter[PrincipalT]
    runtime_tools: Mapping[str, FunctionTool]
    execution_context_provider: Callable[[], ClientToolExecutionContext]

    def tools(self) -> list[FunctionTool]:
        """Expose each ordinary generic name exactly once when an adapter exists."""

        async def write(input: RoutedWriteInput) -> str | FunctionToolResult:
            if input.path.startswith("azents://"):
                return await self._vfs(
                    "write",
                    VfsWriteRequest(
                        _location(input.path), input.content, input.overwrite
                    ),
                )
            return await self._runtime("write", input.path, input.model_dump_json())

        async def edit(input: RoutedEditInput) -> str | FunctionToolResult:
            if input.path.startswith("azents://"):
                return await self._vfs(
                    "edit",
                    VfsEditRequest(
                        _location(input.path),
                        input.old_string,
                        input.new_string,
                        input.replace_all,
                    ),
                )
            return await self._runtime("edit", input.path, input.model_dump_json())

        async def delete(input: RoutedDeleteInput) -> str | FunctionToolResult:
            if input.path.startswith("azents://"):
                return await self._vfs(
                    "delete", VfsDeleteRequest(_location(input.path))
                )
            return await self._runtime("delete", input.path, input.model_dump_json())

        native = {
            "write": make_tool(
                write,
                name="write",
                description=(
                    "Write UTF-8 text to an absolute Runtime path "
                    "or a writable azents:// URI. "
                    "VFS overwrite requires a prior read in this execution; "
                    "unsupported "
                    "or read-only VFS mounts are rejected without Runtime fallback."
                ),
            ),
            "edit": make_tool(
                edit,
                name="edit",
                description=(
                    "Replace exact text in an absolute Runtime file "
                    "or a writable VFS file. "
                    "Read an existing VFS file first; stale read identity or ambiguous "
                    "context changes nothing. Runtime retains its native edit behavior."
                ),
            ),
            "delete": make_tool(
                delete,
                name="delete",
                description=(
                    "Delete an absolute Runtime file or a writable VFS file. "
                    "Read an existing VFS file first. "
                    "Read-only mounts cannot be deleted."
                ),
            ),
        }
        tools = [
            tool
            for name, tool in native.items()
            if self.router.registry.writable_mounts or name in self.runtime_tools
        ]
        if self.router.registry.patch_mounts or "apply_patch" in self.runtime_tools:
            tools.append(
                FunctionTool(
                    spec=FunctionToolSpec(
                        name="apply_patch",
                        description=(
                            "Apply strict V4A under an absolute Runtime directory "
                            "or one authorized atomic-writable VFS base. VFS changes "
                            "all files together or none; Runtime retains "
                            "its native staging and possible partial commit."
                        ),
                        input_schema=RoutedApplyPatchInput.model_json_schema(),
                    ),
                    handler=_RoutedPatchHandler(self),
                    required_client_tool_model_profile=ClientToolModelProfile.V4A_PATCH,
                    wire_variants=(
                        FunctionToolWireVariant(
                            "json_function", GPT_V4A_APPLY_PATCH_PROMPT
                        ),
                        FunctionToolWireVariant(
                            "plaintext_custom",
                            GPT_V4A_PLAINTEXT_CUSTOM_APPLY_PATCH_PROMPT,
                        ),
                    ),
                )
            )
        return tools

    async def _vfs(
        self, name: Literal["write", "edit", "delete"], request: VfsMutationRequest
    ) -> str:
        try:
            # Reject capabilities before requesting call context or backend I/O.
            registration = self.router.registry.get(request.location.mount)
            if registration.mutation_backend is None:
                raise VfsMutationError(
                    "unsupported_operation", "VFS mount is read-only."
                )
            execution = self.execution_context_provider()
            admitted = self.router.admit(
                self.principal, request, tool_call_id=execution.call_id
            )
            result = await self.router.execute(admitted)
        except (VfsMutationError, VfsReadError) as error:
            raise FunctionToolError(
                error.message,
                metadata={"kind": "vfs_mutation_failure", "code": error.code},
            ) from None
        return (
            f"VFS {name} committed: {', '.join(result.uris)} "
            f"({result.file_count} current files, "
            f"{result.byte_count} UTF-8 bytes)."
        )

    async def _runtime(
        self, name: str, path: str, arguments: str
    ) -> str | FunctionToolResult:
        if not path.startswith("/") or "://" in path:
            raise FunctionToolError(
                "Use an absolute Runtime path or canonical azents:// URI."
            )
        tool = self.runtime_tools.get(name)
        if tool is None:
            raise FunctionToolError(
                "Runtime file mutation is unavailable in this execution."
            )
        return await tool.handler(arguments)


@dataclasses.dataclass(frozen=True)
class _RoutedPatchHandler[PrincipalT]:
    """Both wire dialects route before any native Runtime resolution."""

    owner: RoutedMutationTools[PrincipalT]

    async def __call__(self, arguments: str) -> str | FunctionToolResult:
        try:
            input = RoutedApplyPatchInput.model_validate_json(arguments)
        except ValidationError as error:
            raise FunctionToolError(str(error)) from None
        return await self._execute(input)

    async def execute_plaintext_custom(
        self, arguments: str
    ) -> str | FunctionToolResult:
        try:
            input = parse_plaintext_custom_apply_patch_input(arguments)
        except ApplyPatchPlaintextInputError as error:
            raise FunctionToolError(
                "Invalid apply_patch plaintext input.",
                metadata={
                    "kind": "apply_patch_input_failure",
                    "phase": "transport",
                    "reason": error.reason,
                    "applied": [],
                    "not_attempted": [],
                    "exact": True,
                },
            ) from None
        return await self._execute(input)

    async def _execute(self, input: ApplyPatchInput) -> str | FunctionToolResult:
        if not input.base_path.startswith("azents://"):
            return await self.owner._runtime(
                "apply_patch", input.base_path, input.model_dump_json()
            )
        try:
            base = parse_vfs_search_uri(input.base_path)
            registration = self.owner.router.registry.get(base.mount)
            if registration.patch_backend is None:
                raise VfsMutationError(
                    "unsupported_operation", "VFS mount does not support atomic patch."
                )
            execution = self.owner.execution_context_provider()
            admitted = self.owner.router.admit_patch(
                self.owner.principal,
                VfsAtomicPatchRequest(base, input.patch),
                tool_call_id=execution.call_id,
            )
            result = await self.owner.router.execute_patch(admitted)
        except VfsUriError as error:
            raise FunctionToolError(
                str(error),
                metadata={"kind": "apply_patch_failure", "reason": "invalid_path"},
            ) from None
        except (VfsMutationError, VfsReadError) as error:
            raise FunctionToolError(
                error.message,
                metadata={
                    "kind": "apply_patch_failure",
                    "phase": "preflight",
                    "reason": error.code,
                    "applied": [],
                    "not_attempted": [],
                    "exact": True,
                },
            ) from None
        return FunctionToolResult(
            output=(
                f"Applied atomic VFS patch: {len(result.uris)} file(s) "
                "\n" + "\n".join(result.uris)
            ),
            metadata={
                "kind": "apply_patch_result",
                "backend": "vfs",
                "files": list(result.uris),
                "file_count": result.file_count,
                "byte_count": result.byte_count,
            },
        )


def _location(path: str) -> VfsLocation:
    """Normalize canonical-URI rejection into ordinary safe tool feedback."""
    try:
        return parse_vfs_exact_uri(path)
    except VfsUriError as error:
        raise FunctionToolError(
            str(error),
            metadata={"kind": "vfs_mutation_failure", "code": "invalid_path"},
        ) from None
