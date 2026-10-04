"""Local credential-protocol fixtures with synthetic token values."""

import os
import subprocess
from pathlib import Path

import pytest

_HELPER = Path(__file__).parents[1] / "docker/azents-git-credential.sh"


@pytest.mark.parametrize(
    ("environment", "owner", "expected"),
    [
        (
            {
                "GITHUB_INSTALLATION_MAP": (
                    '{"owner":{"env":"GITHUB_TOKEN_INSTALLATION_1","id":1}}'
                ),
                "GITHUB_TOKEN_INSTALLATION_1": "synthetic-installation-token",
                "GH_TOKEN": "synthetic-fallback",
            },
            "OwNeR",
            "synthetic-installation-token",
        ),
        (
            {"GITHUB_INSTALLATION_MAP": "[]", "GH_TOKEN": "synthetic-fallback"},
            "owner",
            "synthetic-fallback",
        ),
        (
            {"GITHUB_INSTALLATION_MAP": "null", "GH_TOKEN": "synthetic-fallback"},
            "owner",
            "synthetic-fallback",
        ),
        (
            {"GITHUB_INSTALLATION_MAP": "{", "GH_TOKEN": "synthetic-fallback"},
            "owner",
            "synthetic-fallback",
        ),
        (
            {
                "GITHUB_INSTALLATION_MAP": '{"owner":{"env":1}}',
                "GH_TOKEN": "synthetic-fallback",
            },
            "owner",
            "synthetic-fallback",
        ),
        (
            {
                "GITHUB_INSTALLATION_MAP": '{"owner":{"env":""}}',
                "GITHUB_TOKEN": "synthetic-fallback",
            },
            "owner",
            "synthetic-fallback",
        ),
        (
            {
                "GITHUB_INSTALLATION_MAP": '{"other":{"env":"MISSING"}}',
                "GH_TOKEN": "synthetic-first",
                "GITHUB_TOKEN": "synthetic-second",
            },
            "owner",
            "synthetic-first",
        ),
        ({}, "owner", None),
    ],
)
def test_validated_installation_routes_preserve_fallback(
    environment: dict[str, str], owner: str, expected: str | None
) -> None:
    """Owner selection operates on validated entries without diagnostic output."""
    result = subprocess.run(
        ["/bin/sh", str(_HELPER), "get"],
        input=f"protocol=https\nhost=github.com\npath={owner}/repo.git\n\n",
        env=_synthetic_environment(environment),
        text=True,
        capture_output=True,
        check=True,
    )
    expected_output = (
        ""
        if expected is None
        else (
            "protocol=https\nhost=github.com\n"
            f"username=x-access-token\npassword={expected}\n"
        )
    )
    assert result.stdout == expected_output
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("operation", "host"),
    [("store", "github.com"), ("get", "example.invalid")],
)
def test_noncredential_boundaries_emit_nothing(operation: str, host: str) -> None:
    result = subprocess.run(
        ["/bin/sh", str(_HELPER), operation],
        input=f"protocol=https\nhost={host}\npath=owner/repo.git\n\n",
        env=_synthetic_environment({"GH_TOKEN": "synthetic-token"}),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == ""
    assert result.stderr == ""


def _synthetic_environment(values: dict[str, str]) -> dict[str, str]:
    """Exclude inherited GitHub credentials from local protocol fixtures."""
    return {
        **{
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("GH_", "GITHUB_"))
        },
        **values,
    }
