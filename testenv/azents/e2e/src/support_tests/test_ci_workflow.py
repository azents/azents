"""Contract tests for E2E CI workflow configuration."""

from support.consts import REPOSITORY_ROOT

_WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/ci.yaml"


def _step_block(workflow: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    end = workflow.find("\n      - name:", start + len(marker))
    return workflow[start:] if end == -1 else workflow[start:end]


def test_timing_cache_restore_keys_support_reruns_and_later_runs() -> None:
    """Restores prefer the current attempt and retain rolling history fallbacks."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    for step_name in (
        "Restore E2E timing baseline",
        "Restore E2E timing history",
    ):
        step = _step_block(workflow, step_name)

        assert "${{ github.run_id }}-${{ github.run_attempt }}" in step
        assert (
            "format('e2e-pr-timing-baseline-{0}-', github.event.pull_request.head.sha)"
        ) in step
        assert "\n            e2e-timing-baseline-" in step


def test_timing_cache_save_keys_are_unique_per_attempt() -> None:
    """Successful PR and main reruns publish distinct rolling cache entries."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    pr_save = _step_block(workflow, "Save same-SHA PR E2E timing baseline")
    main_save = _step_block(workflow, "Save E2E timing baseline")

    assert (
        "e2e-pr-timing-baseline-${{ github.event.pull_request.head.sha }}"
        "-${{ github.run_id }}-${{ github.run_attempt }}"
    ) in pr_save
    assert (
        "key: e2e-timing-baseline-${{ github.run_id }}-${{ github.run_attempt }}"
    ) in main_save


def test_e2e_aggregate_artifact_download_fails_closed_without_retry() -> None:
    """Fail the required aggregate when its only artifact download fails."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    aggregate = workflow.split("  ci_e2e_aggregate:\n", 1)[1].split(
        "\n  ci-python-e2e:\n", 1
    )[0]
    download = _step_block(aggregate, "Download E2E observability artifacts")

    assert download.count("actions/download-artifact@") == 1
    assert "continue-on-error:" not in download
    assert "Retry E2E observability artifact download" not in aggregate
    assert aggregate.count("      - name: Download E2E observability artifacts") == 1


def test_workflow_dispatch_detects_changes_from_first_parent() -> None:
    """Manual runs classify image changes against the checked-out first parent."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    base_step = _step_block(workflow, "Resolve changed-scope base")
    filter_step = _step_block(workflow, "Compute changed scopes")

    assert 'base="$GITHUB_REF"' in base_step
    assert "if [ \"$GITHUB_EVENT_NAME\" = 'workflow_dispatch' ]; then" in base_step
    assert 'base="$(git rev-parse "$GITHUB_SHA^")"' in base_step
    assert "base: ${{ steps.change_base.outputs.base }}" in filter_step


def test_web_lane_prefetches_all_snapshots_and_skips_unused_buildx() -> None:
    """Web E2E reuses every unchanged image and builds only on fallback."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    base_step = _step_block(workflow, "Resolve E2E snapshot base")
    prefetch_step = _step_block(
        workflow,
        "Start direct E2E snapshot image preparation",
    )
    buildx_step = _step_block(workflow, "Setup Docker Buildx")
    runtime_step = _step_block(workflow, "Expose GitHub Actions runtime")

    assert "if: matrix.suite == 'required'" not in base_step
    assert "AZENTS_E2E_WEB_IMAGE_CHANGED:" in prefetch_step
    assert "AZENTS_E2E_ADMIN_WEB_IMAGE_CHANGED:" in prefetch_step
    assert "AZENTS_E2E_IMAGE_BUILD_PROFILE: ${{ matrix.suite }}" in prefetch_step
    assert "matrix.suite == 'web'" not in buildx_step
    assert "matrix.suite == 'web'" not in runtime_step


def test_duration_gate_compares_base_once_without_retry() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    aggregate = workflow.split("  ci_e2e_aggregate:\n", 1)[1].split(
        "\n  ci-python-e2e:\n", 1
    )[0]
    gate = _step_block(aggregate, "Gate E2E duration against base")

    assert "support.ci_duration_gate gate" in gate
    assert "GH_TOKEN: ${{ github.token }}" in gate
    assert "github.event.pull_request.base.sha" in gate
    assert "--publish-status" in gate
    assert "statuses: write" in aggregate.split("    steps:\n", 1)[0]
    assert gate.count("ci_duration_gate gate") == 1
    assert "gh run rerun" not in aggregate
    assert "DURATION_RESULT: ${{ steps.duration.outcome }}" in aggregate


def test_comment_and_status_are_rechecked_when_base_ci_completes() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    comment = workflow.split("  ci_e2e_observability_comment:\n", 1)[1].split(
        "\n  ci_typescript_run:\n", 1
    )[0]
    recheck = (
        REPOSITORY_ROOT / ".github/workflows/e2e-duration-recheck.yaml"
    ).read_text(encoding="utf-8")

    assert "## E2E CI observability" in comment
    assert "Commit:" in comment
    assert "Workflow run and full artifacts" in comment
    assert "e2e-duration-gate/summary.md" in comment
    assert "pull_request_target:" in recheck
    assert "workflow_run:" in recheck
    assert 'workflows: ["CI"]' in recheck
    assert "types: [completed]" in recheck
    assert "github.event_name == 'workflow_run'" in recheck
    assert "github.event.workflow_run.head_branch" in recheck
    assert "github.event.workflow_run.head_sha" in recheck
    assert "select(.base.sha" in recheck
    assert recheck.count(".head.repo.full_name") == 2
    assert "WORKFLOW_HEAD_BRANCH:" in recheck
    assert "WORKFLOW_HEAD_SHA:" in recheck
    assert "WORKFLOW_RUN_ID:" in recheck
    assert "actions/runs/${WORKFLOW_RUN_ID}/pull_requests" in recheck
    assert "github.event.changes.base != null" in recheck
    assert 'cron: "*/15 * * * *"' in recheck
    assert "pull-requests: write" in recheck
    assert "support.ci_duration_gate recheck" in recheck
    assert "gh workflow run" not in recheck
