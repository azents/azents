"""Agent Runtime Control protobuf Python code generation script."""

from __future__ import annotations

import pathlib
import re
import subprocess

import grpc_tools
from grpc_tools import protoc

_GENERATED_HEADER = "# ruff: noqa\n"


def main() -> None:
    """Generate protobuf/gRPC Python modules."""
    root = pathlib.Path(__file__).resolve().parents[1]
    repo_root = root.parents[2]
    proto_root = repo_root / "proto"
    grpc_tools_proto = pathlib.Path(grpc_tools.__file__).parent / "_proto"
    out_dir = root / "src" / "azents_runtime_control" / "proto"
    generated_files: list[pathlib.Path] = []
    for proto_file in (
        proto_root
        / "azents"
        / "runtime_control"
        / "v1"
        / "runtime_configuration.proto",
        proto_root
        / "azents"
        / "runtime_control"
        / "v1"
        / "runtime_provider_control.proto",
        proto_root
        / "azents"
        / "runtime_control"
        / "v1"
        / "runtime_runner_terminal.proto",
        proto_root
        / "azents"
        / "runtime_control"
        / "v1"
        / "runtime_runner_control.proto",
        proto_root
        / "azents"
        / "runtime_control"
        / "v1"
        / "runtime_runner_transfer.proto",
        proto_root
        / "azents"
        / "runtime_control"
        / "v1"
        / "runtime_transfer_coordinator.proto",
    ):
        result = protoc.main(
            [
                "grpc_tools.protoc",
                f"-I{proto_file.parent}",
                f"-I{proto_root}",
                f"-I{grpc_tools_proto}",
                f"--python_out={out_dir}",
                f"--grpc_python_out={out_dir}",
                f"--mypy_out={out_dir}",
                f"--mypy_grpc_out={out_dir}",
                str(proto_file),
            ],
        )
        if result != 0:
            raise SystemExit(result)
        generated_files.extend(_fix_generated_imports(proto_file, out_dir))
    subprocess.run(
        ["ruff", "format", *(str(path) for path in generated_files)],
        check=True,
        cwd=root,
    )


def _fix_generated_imports(
    proto_file: pathlib.Path,
    out_dir: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    module_name = f"{proto_file.stem}_pb2"
    grpc_file = out_dir / f"{module_name}_grpc.py"
    pb2_file = out_dir / f"{module_name}.py"
    grpc_stub = out_dir / f"{module_name}_grpc.pyi"
    pb2_stub = out_dir / f"{module_name}.pyi"
    for generated_file in (grpc_file, pb2_file, grpc_stub, pb2_stub):
        content = generated_file.read_text()
        content = re.sub(
            r"^from azents\.runtime_control\.v1 import (.+)$",
            r"from . import \1",
            content,
            flags=re.MULTILINE,
        )
        content = re.sub(
            r"^import (\w+_pb2) as (.+)$",
            r"from . import \1 as \2",
            content,
            flags=re.MULTILINE,
        )
        if generated_file.suffix == ".pyi":
            content = content.replace("  # noqa: Y015", "")
        generated_file.write_text(_GENERATED_HEADER + content)
    return pb2_file, grpc_file, pb2_stub, grpc_stub


if __name__ == "__main__":
    main()
