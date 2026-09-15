"""Contract tests for public release workflow configuration."""

from support.consts import REPOSITORY_ROOT

_WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/release.yaml"


def _step_block(workflow: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    end = workflow.find("\n      - name:", start + len(marker))
    return workflow[start:] if end == -1 else workflow[start:end]


def test_release_validation_requires_main_without_source_chart_lockstep() -> None:
    """One-click publication keeps source identity without a version-bump PR."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    step = _step_block(workflow, "Validate version, channel, and source")

    assert """if [ "$GITHUB_REF" != 'refs/heads/main' ]; then""" in step
    assert "Releases must run from the main branch" in step
    assert "Chart.yaml" not in step
    assert "Chart version/appVersion must both" not in step


def test_release_chart_uses_and_validates_requested_version_before_push() -> None:
    """The packaged chart receives and verifies the requested release version."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    step = _step_block(workflow, "Package, validate, and push chart")

    assert '--version "$CHART_VERSION"' in step
    assert '--app-version "$CHART_VERSION"' in step
    assert 'chart_metadata="$(helm show chart "$chart_path")"' in step
    assert '"$actual_version" != "$CHART_VERSION"' in step
    assert '"$actual_app_version" != "$CHART_VERSION"' in step
    assert step.index("chart_metadata=") < step.index('helm push "$chart_path"')
