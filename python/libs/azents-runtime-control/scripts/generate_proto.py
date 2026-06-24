"""Agent Runtime Control protobuf Python code generation script."""

from __future__ import annotations

import pathlib
import re

import grpc_tools
from grpc_tools import protoc

_GRPC_HEADER = (
    "# ruff: noqa\n"
    "# pyright: reportAttributeAccessIssue=false, reportCallIssue=false, "
    "reportUnknownArgumentType=false, reportUnknownMemberType=false, "
    "reportUnknownParameterType=false, reportUnknownVariableType=false\n"
)
_PB2_HEADER = (
    "# ruff: noqa\n"
    "# pyright: reportAttributeAccessIssue=false, reportCallIssue=false, "
    "reportUnknownArgumentType=false, reportUnknownMemberType=false, "
    "reportUnknownVariableType=false\n"
)


def main() -> None:
    """Generate protobuf/gRPC Python modules."""
    root = pathlib.Path(__file__).resolve().parents[1]
    repo_root = root.parents[2]
    proto_root = repo_root / "proto"
    grpc_tools_proto = pathlib.Path(grpc_tools.__file__).parent / "_proto"
    out_dir = root / "src" / "azents_runtime_control" / "proto"
    for proto_file in (
        proto_root
        / "azents"
        / "runtime_control"
        / "v1"
        / "runtime_provider_control.proto",
        proto_root
        / "azents"
        / "runtime_control"
        / "v1"
        / "runtime_runner_control.proto",
    ):
        result = protoc.main(
            [
                "grpc_tools.protoc",
                f"-I{proto_file.parent}",
                f"-I{proto_root}",
                f"-I{grpc_tools_proto}",
                f"--python_out={out_dir}",
                f"--grpc_python_out={out_dir}",
                str(proto_file),
            ],
        )
        if result != 0:
            raise SystemExit(result)
        _fix_generated_imports(proto_file, out_dir)


def _fix_generated_imports(proto_file: pathlib.Path, out_dir: pathlib.Path) -> None:
    module_name = f"{proto_file.stem}_pb2"
    grpc_file = out_dir / f"{module_name}_grpc.py"
    content = grpc_file.read_text()
    content = re.sub(
        rf"^import {re.escape(module_name)} as (.+)$",
        rf"from . import {module_name} as \1",
        content,
        flags=re.MULTILINE,
    )
    grpc_file.write_text(_GRPC_HEADER + content)

    pb2_file = out_dir / f"{module_name}.py"
    pb2_file.write_text(_PB2_HEADER + pb2_file.read_text())


if __name__ == "__main__":
    main()
