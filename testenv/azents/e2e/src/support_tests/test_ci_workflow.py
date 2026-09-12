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
