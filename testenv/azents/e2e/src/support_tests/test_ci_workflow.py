"""Contract tests for E2E CI workflow configuration."""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from support.consts import REPOSITORY_ROOT

_WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/ci.yaml"


def _step_block(workflow: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    end = workflow.find("\n      - name:", start + len(marker))
    return workflow[start:] if end == -1 else workflow[start:end]


def test_runner_browser_install_preserves_commands_and_uses_official_apt_mirror() -> (
    None
):
    """Only the existing Runner unit host changes mirror and observes each phase."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    job = workflow.split("  ci_python_run:\n", 1)[1].split(
        "\n  ci_python_migrations_run:\n", 1
    )[0]
    names = (
        "Select Ubuntu archive for Runner browser dependencies",
        "Install Runner Chromium engine",
        "Install Runner Firefox system dependencies",
        "Install Runner pinned Camoufox and model",
    )
    blocks = [_step_block(job, name) for name in names]
    assert [job.index(f"      - name: {name}\n") for name in names] == sorted(
        job.index(f"      - name: {name}\n") for name in names
    )
    for block in blocks:
        assert "if: matrix.project == 'python/apps/azents-runtime-runner'" in block
        assert "continue-on-error:" not in block
        assert "timeout-minutes:" not in block
    assert (
        "sudo -n python3 scripts/ci/apt_mirror.py --sources-root /etc/apt" in blocks[0]
    )
    for block, command in zip(
        blocks[1:],
        (
            "uv run patchright install --with-deps chromium",
            "uv run playwright install-deps firefox",
            "uv run python -m azents_runtime_runner.browser_install",
        ),
        strict=True,
    ):
        assert "working-directory: python/apps/azents-runtime-runner" in block
        assert block.splitlines()[-1].strip() == f"run: {command}"
    assert "      - name: Pytest\n" in job


def test_general_report_can_checkout_and_keeps_forks_read_only() -> None:
    """Job-scoped permissions retain source reads and bound comment publication."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    report = workflow.split("  ci_observability:\n", 1)[1].split(
        "\n  ci_typescript_run:\n", 1
    )[0]
    permissions = report.split("    permissions:\n", 1)[1].split("    steps:\n", 1)[0]
    assert "contents: read" in permissions
    assert "actions: read" in permissions
    comment = _step_block(report, "Update sticky CI observability comment")
    assert (
        "github.event.pull_request.head.repo.full_name == github.repository" in comment
    )
    assert "header: e2e-observability" in comment


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


def test_e2e_lanes_require_exact_current_run_producer_images_without_rebuild() -> None:
    """The existing Docker portfolio is handed off with no snapshot/build fallback."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    lane = workflow.split("  ci_e2e_run:\n", 1)[1].split("\n  ci_e2e_aggregate:\n", 1)[
        0
    ]
    assert "      - ci_docker_build_run\n" in lane
    assert "needs.ci_docker_build_run.result == 'success'" in lane
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in lane
    preparation = _step_block(lane, "Prepare exact images and existing prerequisites")
    assert "scripts.ci.e2e_images prepare" in preparation
    assert "GH_TOKEN: ${{ github.token }}" in preparation
    assert "actions: read" in lane.split("    steps:\n", 1)[0]
    assert "--root" in preparation and "--evidence" in preparation
    assert "continue-on-error:" not in preparation
    assert lane.index("Prepare exact images") < lane.index("Verify and load")
    load = _step_block(lane, "Verify and load exact CI image portfolio")
    assert "scripts.ci.e2e_images load" in load
    assert "--github-env" in load and "--evidence" in load
    assert "continue-on-error:" not in load
    assert lane.index("Verify and load") < lane.index("Run E2E lane")
    assert "e2e_snapshot_images.py" not in lane
    assert "Setup Docker Buildx" not in lane
    assert "AZENTS_E2E_DOCKER_BUILDER" not in lane


def test_exact_image_export_uses_existing_build_jobs_and_counts_all_overhead() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    producer = workflow.split("  ci_docker_build_run:\n", 1)[1].split(
        "\n  ci-docker-build:\n", 1
    )[0]
    assert producer.count("          - name: azents-") == 8
    assert "runs-on: ubuntu-latest" in producer
    assert "needs.changes.outputs.python_e2e == 'true'" in producer
    assert "needs.changes.outputs.web_e2e == 'true'" in producer
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in producer
    assert producer.index("Build ${{ matrix.name }}") < producer.index(
        "Export exact E2E image"
    )
    assert producer.index("Smoke ${{ matrix.name }}") < producer.index(
        "Export exact E2E image"
    )
    export = _step_block(producer, "Export exact E2E image")
    publish = _step_block(producer, "Publish exact E2E image")
    assert "scripts.ci.e2e_images export" in export
    assert "continue-on-error:" not in export
    assert "${{ github.run_id }}-${{ github.run_attempt }}" in publish
    assert "compression-level: 0" in publish
    assert "retention-days: 1" in publish
    assert "if-no-files-found: error" in publish
    assert "continue-on-error:" not in publish


@pytest.mark.parametrize("image", ["azents-runtime-runner", "azents-server"])
def test_ci_build_reads_only_existing_snapshot_runner_cache(
    tmp_path: Path, image: str
) -> None:
    """Use matching content-addressed layers without publishing a new cache."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    producer = workflow.split("  ci_docker_build_run:\n", 1)[1].split(
        "\n  ci-docker-build:\n", 1
    )[0]
    expose = _step_block(producer, "Expose existing Runtime Runner build cache")
    assert "if: matrix.name == 'azents-runtime-runner'" in expose
    assert "uses: ./.github/actions/expose-github-runtime" in expose
    script = textwrap.dedent(
        _step_block(producer, "Build ${{ matrix.name }}").split("        run: |\n", 1)[
            1
        ]
    )
    assert "--cache-to" not in script
    script = (
        script.replace("${{ matrix.name }}", image)
        .replace("${{ matrix.extra_context }}", "")
        .replace("${{ matrix.dockerfile }}", "fixture.Dockerfile")
        .replace("${{ matrix.image }}", image + ":ci")
    )
    tools = tmp_path / "bin"
    tools.mkdir()
    docker = tools / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGUMENTS"\n')
    docker.chmod(0o755)
    arguments = tmp_path / "arguments"
    subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        env={
            **os.environ,
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "ARGUMENTS": str(arguments),
        },
        check=True,
    )
    cache = (
        ["--cache-from", "type=gha,scope=azents-e2e-v1-azents-runtime-runner"]
        if image == "azents-runtime-runner"
        else []
    )
    assert arguments.read_text().splitlines() == [
        "buildx",
        "build",
        "--load",
        *cache,
        "-f",
        "fixture.Dockerfile",
        "-t",
        image + ":ci",
        ".",
    ]
    snapshot = (REPOSITORY_ROOT / ".github/workflows/snapshot.yaml").read_text()
    assert "e2e_cache_repository: azents-runtime-runner" in snapshot
    assert 'cache_scope="azents-e2e-v1-$cache_repository"' in snapshot
    assert (
        producer.index("Build ${{ matrix.name }}")
        < producer.index("Smoke ${{ matrix.name }}")
        < producer.index("Export exact E2E image")
        < producer.index("Publish exact E2E image")
    )


def test_component_contracts_publish_in_existing_typescript_job() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    job = workflow.split("  ci_typescript_run:\n", 1)[1].split(
        "\n  ci-typescript:\n", 1
    )[0]
    assert "runs-on: ubuntu-latest" in job
    assert "matrix:" not in job
    browser = _step_block(job, "Install component browser")
    assert "playwright install --with-deps chromium" in browser
    run = _step_block(job, "Web component contracts")
    assert "scripts.ci.run_component_tests" in run
    assert "continue-on-error:" not in run
    publish = _step_block(job, "Publish Web component test observability")
    assert "if: always()" in publish
    assert "name: typescript-web-components" in publish
    assert "directory: ${{ runner.temp }}/web-component-tests" in publish


def test_duration_gate_compares_base_once_without_retry() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    aggregate = workflow.split("  ci_e2e_aggregate:\n", 1)[1].split(
        "\n  ci-python-e2e:\n", 1
    )[0]
    gate = _step_block(aggregate, "Gate E2E duration against base")

    assert "support.ci_duration_gate gate" in gate
    assert "GH_TOKEN: ${{ github.token }}" in gate
    assert "github.event.pull_request.base.sha" in gate
    assert "--publish-status" not in gate
    assert "PUBLISH_STATUS" not in gate
    assert "statuses: write" not in aggregate.split("    steps:\n", 1)[0]
    assert gate.count("ci_duration_gate gate") == 1
    assert "gh run rerun" not in aggregate
    assert "DURATION_RESULT: ${{ steps.duration.outcome }}" in aggregate


def test_web_lane_has_one_isolated_stack_and_retains_the_complete_plan() -> None:
    """Bound in-runner contention without changing scope, retries or authority."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    lane = workflow.split("  ci_e2e_run:\n", 1)[1].split("\n  ci_e2e_aggregate:\n", 1)[
        0
    ]
    run = _step_block(lane, "Run E2E lane")
    assert "parallel_args=()" in run
    assert "if [ \"$AZENTS_E2E_IMAGE_BUILD_PROFILE\" = 'web' ]; then" in run
    assert "-n 1 --dist loadfile --no-loadscope-reorder --max-worker-restart=0" in run
    assert 'mapfile -t test_files < "e2e-plan/${{ matrix.plan_file }}"' in run
    assert '"${test_files[@]}"' in run
    assert "-p scripts.ci.pytest_timing -p support.e2e_parallel" in run
    assert 'exit "$pytest_status"' in run
    assert "pytest_execution=(-n 2 --dist loadfile --max-worker-restart=0)" in workflow
    capacity = _step_block(lane, "Capture E2E runner capacity")
    diagnostics = _step_block(lane, "Capture E2E diagnostics")
    assert (
        'capture_runner_observation "$report_dir/runner-cpu.json" lscpu --json'
        in capacity
    )
    assert "if: always()" in diagnostics
    assert "for resource in cpu memory io; do" in capacity
    assert "for resource in cpu memory io; do" in diagnostics
    assert '"/proc/pressure/${resource}"' in capacity
    assert '"/proc/pressure/${resource}"' in diagnostics
    assert "runner-memory-before.txt" in capacity
    assert "runner-memory-after.txt" in diagnostics


@pytest.mark.parametrize("observation_exit", [0, 9])
def test_runner_observations_preserve_pytest_failure_and_remaining_diagnostics(
    tmp_path: Path, observation_exit: int
) -> None:
    """Execute the real shell blocks with unavailable optional capacity tools."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("lscpu", "free", "cat"):
        tool = tools / name
        tool.write_text(
            f"#!/bin/sh\nprintf 'resource observation\\n'\nexit {observation_exit}\n"
        )
        tool.chmod(0o755)
    for name, body in {
        "docker": "printf 'docker diagnostics retained\\n'",
        "python": "printf 'summary retained\\n'",
        "uv": ('printf \'%s\\n\' "$@" > "$RUNNER_TEMP/pytest-args.txt"\nexit 17'),
    }.items():
        tool = tools / name
        tool.write_text(f"#!/bin/sh\n{body}\n")
        tool.chmod(0o755)
    repository = tmp_path / "repository"
    (repository / "testenv/azents/e2e").mkdir(parents=True)
    (repository / "e2e-plan").mkdir()
    (repository / "e2e-plan/web.txt").write_text("test_first.py\ntest_second.py\n")
    env = {
        **os.environ,
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_WORKSPACE": str(repository),
        "AZENTS_E2E_IMAGE_BUILD_PROFILE": "web",
    }

    def execute(name: str) -> subprocess.CompletedProcess[str]:
        step = _step_block(workflow, name)
        script = textwrap.dedent(step.split("        run: |\n", 1)[1])
        script = (
            script.replace("${{ matrix.lane }}", "web-1")
            .replace("${{ matrix.plan_file }}", "web.txt")
            .replace("${{ job.status }}", "failure")
        )
        return subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=repository,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    assert execute("Capture E2E runner capacity").returncode == 0
    assert execute("Run E2E lane").returncode == 17
    diagnostics = execute("Capture E2E diagnostics")
    assert diagnostics.returncode == 0
    assert "summary retained" in diagnostics.stdout
    args = (tmp_path / "pytest-args.txt").read_text().splitlines()
    assert args[-2:] == ["test_first.py", "test_second.py"]
    root = tmp_path / "e2e-observability/web-1"
    observations = list(root.glob("runner-*"))
    assert len(observations) == 9
    for observation in observations:
        assert ("Observation unavailable" in observation.read_text()) == (
            observation_exit != 0
        )
    assert "docker diagnostics retained" in (root / "docker-ps.txt").read_text()


def test_comment_and_status_are_rechecked_when_base_ci_completes() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    comment = workflow.split("  ci_observability:\n", 1)[1].split(
        "\n  ci_typescript_run:\n", 1
    )[0]
    recheck = (
        REPOSITORY_ROOT / ".github/workflows/e2e-duration-recheck.yaml"
    ).read_text(encoding="utf-8")

    assert "scripts/ci/workflow_report.py" in comment
    assert "ci-workflow/summary.md" in comment
    assert "ci-observability" in comment
    assert "e2e-duration-gate/summary.md" in comment
    assert "pull_request_target:" in recheck
    assert "workflow_run:" in recheck
    assert 'workflows: ["CI"]' in recheck
    assert "types: [completed]" in recheck
    assert "github.event_name == 'workflow_run'" in recheck
    assert "github.event.workflow_run.head_sha" in recheck
    assert "support.ci_duration_gate targets" in recheck
    assert '--completed-sha "$WORKFLOW_HEAD_SHA"' in recheck
    assert "WORKFLOW_HEAD_SHA:" in recheck
    assert "WORKFLOW_HEAD_BRANCH:" not in recheck
    assert "WORKFLOW_RUN_ID:" not in recheck
    assert "base=main" not in recheck
    assert "github.event.changes.base != null" in recheck
    assert 'cron: "*/15 * * * *"' in recheck
    assert "pull-requests: write" in recheck
    assert "group: e2e-duration-reevaluation" in recheck
    assert "cancel-in-progress: false" in recheck
    assert "queue: max" in recheck
    assert "support.ci_duration_gate recheck" in recheck
    assert "gh workflow run" not in recheck
