"""Regression tests for the Runtime Control package import boundary."""

import ast
from pathlib import Path

from azents_runtime_control.grpc_provider_client import GrpcProviderControlClient
from azents_runtime_control.provider import ProviderRegistration


def test_package_root_does_not_reexport_child_module_symbols() -> None:
    """Keep child-module definitions at their defining import paths."""
    package_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "azents_runtime_control"
        / "__init__.py"
    )
    tree = ast.parse(package_root.read_text())
    child_symbol_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (
            node.level > 0 or (node.module or "").startswith("azents_runtime_control.")
        )
    ]

    assert not child_symbol_imports


def test_provider_symbols_remain_available_from_defining_modules() -> None:
    """Direct imports preserve the existing Provider client and contract types."""
    assert GrpcProviderControlClient.__module__ == (
        "azents_runtime_control.grpc_provider_client"
    )
    assert ProviderRegistration.__module__ == "azents_runtime_control.provider"
