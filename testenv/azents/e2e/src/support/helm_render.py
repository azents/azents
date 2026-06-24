"""Helm render verify helper."""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from support.consts import REPOSITORY_ROOT


@dataclass(frozen=True)
class HelmRenderResult:
    """Helm render run result."""

    available: bool
    rendered: str
    command: tuple[str, ...]
    skip_reason: str | None = None


def helm_available() -> bool:
    """current environmentt helm binary t t checkt."""
    return shutil.which("helm") is not None


def render_azents_chart(
    *,
    values_file: Path | None = None,
    require_helm: bool = False,
) -> HelmRenderResult:
    """azents Helm chart t template t."""
    chart_dir = REPOSITORY_ROOT / "infra/charts/azents"
    command = ["helm", "template", "azents", str(chart_dir)]
    if values_file is not None:
        command.extend(["--values", str(values_file)])
    if not helm_available():
        if require_helm:
            raise RuntimeError(
                "helm is required for provider-controller render verification."
            )
        return HelmRenderResult(
            available=False,
            rendered="",
            command=tuple(command),
            skip_reason="helm binary is not installed",
        )

    completed = subprocess.run(  # noqa: S603
        command,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return HelmRenderResult(
        available=True,
        rendered=completed.stdout,
        command=tuple(command),
    )


def assert_helm_output_redacted(rendered: str, sensitive_values: set[str]) -> None:
    """rendered manifest t secret literal t t checkt."""
    leaked = sorted(value for value in sensitive_values if value and value in rendered)
    if leaked:
        raise AssertionError("Rendered Helm output contains sensitive literal values.")


def assert_provider_controller_render_contract(rendered: str, *, enabled: bool) -> None:
    """provider controller optional render contract t checkt."""
    marker = "azents-runtime-provider-kubernetes"
    if enabled and marker not in rendered:
        raise AssertionError("Provider controller resources were not rendered.")
    if not enabled and marker in rendered:
        raise AssertionError("Provider controller resources rendered while disabled.")
