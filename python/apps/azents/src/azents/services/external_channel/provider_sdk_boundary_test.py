"""Repository absence checks for the provider SDK migration boundary."""

import ast
import re
from pathlib import Path

_EXTERNAL_CHANNEL_ROOT = Path(__file__).parent
_ALLOWED_PROVIDER_HTTP_FILES = {
    "discord_api.py",  # G1 individual Guild command create
    "discord_delivery.py",  # G2 bounded multipart file message create
    "discord_files.py",  # G3 Discord CDN attachment bytes
    "slack_events.py",  # G4 private download and G5 external upload bytes
    "discord_testenv.py",  # injected credential-free fixture control plane
}
_DISCORD_ROUTE_LITERAL_ALLOWED_FILES = {
    "discord_api.py",
    "discord_delivery.py",
    "discord_endpoint.py",
    "discord_testenv.py",  # injected fixture control paths, not provider API routes
    "ingestion_history.py",  # browser navigation permalink, not provider API I/O
}
_PROVIDER_HTTP_CALL = re.compile(
    r"\b(?:http_client|client)\.(?:get|post|put|patch|delete|request|stream)\("
)
_DISCORD_ROUTE_LITERAL = re.compile(
    r"/(?:api/v\d+/)?(?:applications|channels|guilds|oauth2|users|gateway)(?:/|\b)"
)
_SECOND_DISCORD_SDKS = {"hikari", "nextcord", "disnake", "interactions"}


def _runtime_files() -> list[Path]:
    return [
        path
        for path in _EXTERNAL_CHANNEL_ROOT.glob("*.py")
        if not path.name.endswith("_test.py")
    ]


def test_runtime_has_no_private_discord_sdk_imports_or_global_mutation() -> None:
    violations: list[str] = []
    for path in _runtime_files():
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {
                "discord.http",
                "discord.gateway",
            }:
                violations.append(f"{path.name}:{node.lineno}:{node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in {"discord.http", "discord.gateway"}:
                        violations.append(f"{path.name}:{node.lineno}:{alias.name}")
        if "Route.BASE" in source or "DEFAULT_GATEWAY" in source:
            violations.append(f"{path.name}:SDK global endpoint mutation")

    assert violations == []


def test_runtime_has_no_second_discord_sdk() -> None:
    violations: list[str] = []
    for path in _runtime_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.append(node.module)
            for module in modules:
                if module.split(".", 1)[0] in _SECOND_DISCORD_SDKS:
                    violations.append(
                        f"{path.name}:{getattr(node, 'lineno', 0)}:{module}"
                    )

    assert violations == []


def test_provider_http_calls_remain_inside_the_closed_gap_allowlist() -> None:
    violations = [
        path.name
        for path in _runtime_files()
        if path.name not in _ALLOWED_PROVIDER_HTTP_FILES
        and _PROVIDER_HTTP_CALL.search(path.read_text())
    ]

    assert violations == []


def test_discord_provider_route_literals_remain_inside_g1_g2_boundaries() -> None:
    violations = [
        path.name
        for path in _runtime_files()
        if path.name not in _DISCORD_ROUTE_LITERAL_ALLOWED_FILES
        and _DISCORD_ROUTE_LITERAL.search(path.read_text())
    ]

    assert violations == []
