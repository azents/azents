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
    assert "semver_pattern=" in step
    assert '[[ ! "$VERSION" =~ $semver_pattern ]]' in step
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


def test_release_notes_build_a_single_sorted_stream_from_image_metadata() -> None:
    """Release-note generation passes a filter, not an option-like string, to jq."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    step = _step_block(workflow, "Build release notes")

    assert "jq -rs '. | sort_by(.component)[]" in step
    assert "image-metadata/*.json" in step
    assert """printf -- '- `oci://ghcr.io/azents/charts/azents:%s`""" in step


def test_release_dispatch_runs_after_publication_with_generic_metadata() -> None:
    """A configured downstream receives immutable release artifact metadata."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    download_step = _step_block(
        workflow, "Download release image metadata for dispatch"
    )
    payload_step = _step_block(workflow, "Build release payload")
    dispatch_step = _step_block(workflow, "Dispatch downstream release")
    skip_step = _step_block(workflow, "Skip downstream release dispatch")

    dispatch_job = workflow.index("  dispatch-release:\n")
    assert workflow.index("  github-release:\n") < dispatch_job
    assert "      - github-release" in workflow[dispatch_job:]
    assert "DOWNSTREAM_DEPLOY_REPOSITORY" in workflow[dispatch_job:]
    assert "DOWNSTREAM_DEPLOY_TOKEN" in workflow[dispatch_job:]
    assert "DOWNSTREAM_RELEASE_EVENT_TYPE" in workflow[dispatch_job:]
    assert "'azents_release_published'" in workflow[dispatch_job:]

    configured_condition = (
        "env.HAS_DOWNSTREAM_TOKEN == 'true' && env.DOWNSTREAM_REPOSITORY != ''"
    )
    assert configured_condition in download_step
    assert configured_condition in payload_step
    assert configured_condition in dispatch_step
    assert "schemaVersion: 1" in payload_step
    assert '--arg repository "$GITHUB_REPOSITORY"' in payload_step
    assert '--arg ref "$GITHUB_REF"' in payload_step
    assert '--arg sha "$GITHUB_SHA"' in payload_step
    assert "tag: .version" in payload_step
    assert "sort_by(.component)" in payload_step
    assert '"/repos/${DOWNSTREAM_REPOSITORY}/dispatches"' in dispatch_step
    assert (
        "env.HAS_DOWNSTREAM_TOKEN != 'true' || env.DOWNSTREAM_REPOSITORY == ''"
        in skip_step
    )
