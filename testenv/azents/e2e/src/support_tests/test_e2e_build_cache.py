"""Unit coverage for E2E image cache configuration."""

import importlib.util
import inspect
import json
import re
import sys
import threading
from pathlib import Path

import pytest

from support.ci_observability import parse_image_build_timings
from support.consts import REPOSITORY_ROOT
from tests import conftest as e2e_conftest

_CONFTEST_PATH = REPOSITORY_ROOT / "testenv/azents/e2e/src/tests/conftest.py"
_CONFTEST_SPEC = importlib.util.spec_from_file_location(
    "e2e_build_cache_conftest",
    _CONFTEST_PATH,
)
assert _CONFTEST_SPEC is not None
assert _CONFTEST_SPEC.loader is not None
_CONFTEST_MODULE = importlib.util.module_from_spec(_CONFTEST_SPEC)
sys.modules[_CONFTEST_SPEC.name] = _CONFTEST_MODULE
_CONFTEST_SPEC.loader.exec_module(_CONFTEST_MODULE)
_SNAPSHOT_WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/snapshot.yaml"


def test_gha_cache_options_are_per_image_and_import_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Images retaining the remote path use per-image import-only scopes."""
    monkeypatch.setenv(_CONFTEST_MODULE._DOCKER_BUILDER_ENV, "e2e-builder")
    monkeypatch.setenv(
        _CONFTEST_MODULE._GHA_DOCKER_CACHE_SCOPE_PREFIX_ENV,
        "azents-e2e-v1",
    )

    cache_from, cache_to, backend, scope = (
        _CONFTEST_MODULE._get_e2e_image_cache_options("azents-runtime-runner")
    )

    assert cache_from == [
        {"type": "gha", "scope": "azents-e2e-v1-azents-runtime-runner"}
    ]
    assert cache_to is None
    assert backend == "gha"
    assert scope == "azents-e2e-v1-azents-runtime-runner"

    _, cache_to, _, _ = _CONFTEST_MODULE._get_e2e_image_cache_options(
        "azents-runtime-runner"
    )

    assert cache_to is None


def test_gha_cache_requires_the_named_buildx_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GHA cache configuration cannot silently use Docker's default builder."""
    monkeypatch.delenv(_CONFTEST_MODULE._DOCKER_BUILDER_ENV, raising=False)
    monkeypatch.setenv(
        _CONFTEST_MODULE._GHA_DOCKER_CACHE_SCOPE_PREFIX_ENV,
        "azents-e2e-v1",
    )

    with pytest.raises(
        RuntimeError,
        match="AZENTS_E2E_DOCKER_GHA_CACHE_SCOPE_PREFIX requires "
        "AZENTS_E2E_DOCKER_BUILDER",
    ):
        _CONFTEST_MODULE._get_e2e_image_cache_options("azents-runtime-runner")


def test_build_passes_import_only_gha_cache_to_buildx_and_records_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Builds receive GHA cache options and write safe completion evidence."""
    build_arguments: dict[str, object] = {}

    def fake_build(**kwargs: object) -> None:
        build_arguments.update(kwargs)

    monkeypatch.setenv(_CONFTEST_MODULE._DOCKER_BUILDER_ENV, "e2e-builder")
    monkeypatch.setenv(
        _CONFTEST_MODULE._GHA_DOCKER_CACHE_SCOPE_PREFIX_ENV,
        "azents-e2e-v1",
    )
    monkeypatch.setenv(_CONFTEST_MODULE._E2E_ARTIFACT_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(_CONFTEST_MODULE.pow_docker, "build", fake_build)

    _CONFTEST_MODULE._build_e2e_image(
        image_tag="azents-runtime-runner-e2e:test",
        dockerfile=(REPOSITORY_ROOT / "python/apps/azents-runtime-runner/Dockerfile"),
        cache_repository="azents-runtime-runner",
    )

    assert build_arguments["builder"] == "e2e-builder"
    assert build_arguments["cache_from"] == [
        {"type": "gha", "scope": "azents-e2e-v1-azents-runtime-runner"}
    ]
    assert build_arguments["cache_to"] is None
    timings = (tmp_path / "image-build-timings.jsonl").read_text(encoding="utf-8")
    assert '"cache_export_enabled": false' in timings
    assert '"completed": true' in timings


def test_snapshot_workflow_owns_every_e2e_gha_cache_scope() -> None:
    """Snapshot writers cover every configured scope and actual remote reader."""
    workflow = _SNAPSHOT_WORKFLOW_PATH.read_text(encoding="utf-8")
    writer_repositories = set(
        re.findall(r"            e2e_cache_repository: (azents-[a-z-]+)", workflow)
    )
    configured_repositories = {
        image_build.cache_repository
        for image_build in _CONFTEST_MODULE._E2E_IMAGE_BUILD_PROFILES["web"]
    }
    remote_reader_repositories = configured_repositories - {"azents-server"}

    assert writer_repositories == configured_repositories
    assert remote_reader_repositories <= writer_repositories
    assert "azents-server" not in remote_reader_repositories
    assert 'cache_repository="${{ matrix.e2e_cache_repository }}"' in workflow
    assert 'cache_scope="azents-e2e-v1-$cache_repository"' in workflow
    assert '"type=gha,scope=$cache_scope,mode=max,ignore-error=true"' in workflow


def test_server_source_overlay_uses_snapshot_base_without_remote_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source-only server changes replace app source over the pulled base image."""
    build_arguments: dict[str, object] = {}

    def fake_build(**kwargs: object) -> None:
        build_arguments.update(kwargs)

    monkeypatch.setenv(
        _CONFTEST_MODULE._SERVER_SOURCE_OVERLAY_BASE_ENV,
        "azents-server:e2e-base-snapshot",
    )
    monkeypatch.setattr(_CONFTEST_MODULE.pow_docker, "build", fake_build)

    _CONFTEST_MODULE._build_configured_e2e_image(
        _CONFTEST_MODULE._SERVER_IMAGE_BUILD,
        "azents-e2e:test",
    )

    assert build_arguments["file"] == str(
        REPOSITORY_ROOT / "azents-e2e-server-overlay.Dockerfile"
    )
    assert build_arguments["builder"] == "default"
    assert build_arguments["build_args"] == {
        "BASE_IMAGE": "azents-server:e2e-base-snapshot"
    }
    assert build_arguments["cache_from"] is None
    assert build_arguments["cache_to"] is None


def test_server_full_build_uses_local_buildkit_without_remote_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A changed dependency image keeps the full build but skips slower GHA import."""
    build_arguments: dict[str, object] = {}

    def fake_build(**kwargs: object) -> None:
        build_arguments.update(kwargs)

    monkeypatch.delenv(
        _CONFTEST_MODULE._SERVER_SOURCE_OVERLAY_BASE_ENV,
        raising=False,
    )
    monkeypatch.setenv(_CONFTEST_MODULE._DOCKER_BUILDER_ENV, "e2e-builder")
    monkeypatch.setenv(
        _CONFTEST_MODULE._GHA_DOCKER_CACHE_SCOPE_PREFIX_ENV,
        "azents-e2e-v1",
    )
    monkeypatch.setenv(_CONFTEST_MODULE._E2E_ARTIFACT_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(_CONFTEST_MODULE.pow_docker, "build", fake_build)

    _CONFTEST_MODULE._build_configured_e2e_image(
        _CONFTEST_MODULE._SERVER_IMAGE_BUILD,
        "azents-e2e:test",
    )

    assert build_arguments["file"] == str(REPOSITORY_ROOT / "azents.Dockerfile")
    assert build_arguments["builder"] == "default"
    assert build_arguments["cache_from"] is None
    assert build_arguments["cache_to"] is None
    timing = json.loads(
        (tmp_path / "image-build-timings.jsonl").read_text(encoding="utf-8")
    )
    assert timing["image"] == "azents-server"
    assert timing["build_mode"] == "full"
    assert timing["cache_backend"] == "docker-local:default"
    assert timing["cache_scope"] is None
    assert timing["cache_export_enabled"] is False
    assert timing["completed"] is True


def test_server_source_overlay_replaces_the_complete_application_directory() -> None:
    """Deleted application files cannot survive from the predecessor snapshot."""
    dockerfile = (REPOSITORY_ROOT / "azents-e2e-server-overlay.Dockerfile").read_text(
        encoding="utf-8"
    )

    remove_position = dockerfile.index('RUN rm -rf "${ROOT_DIR}/python/apps/azents"')
    copy_position = dockerfile.index(
        'COPY python/apps/azents/ "${ROOT_DIR}/python/apps/azents/"'
    )

    assert remove_position < copy_position


def test_required_profile_builds_independent_images_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The required CI profile overlaps all independent product image builds."""
    barrier = threading.Barrier(3, timeout=5)
    calls: list[tuple[str, int]] = []
    for image_build in _CONFTEST_MODULE._CORE_E2E_IMAGE_BUILDS:
        monkeypatch.delenv(image_build.environment_variable, raising=False)

    def fake_build(
        *,
        image_tag: str,
        dockerfile: Path,
        cache_repository: str | None,
        build_contexts: dict[str, str] | None = None,
        observability_image: str | None = None,
        build_mode: str = "full",
        builder_override: str | None = None,
        cache_backend_override: str | None = None,
    ) -> None:
        del (
            image_tag,
            dockerfile,
            build_contexts,
            build_mode,
            builder_override,
            cache_backend_override,
        )
        repository = observability_image or cache_repository
        assert repository is not None
        calls.append((repository, threading.get_ident()))
        barrier.wait()

    monkeypatch.setattr(_CONFTEST_MODULE, "_build_e2e_image", fake_build)

    with _CONFTEST_MODULE._e2e_image_preparation("required") as preparation:
        images = preparation.join(preparation.selected_images)

    assert set(images) == {
        "azents-server",
        "azents-runtime-runner",
        "azents-runtime-provider-docker",
    }
    assert {repository for repository, _ in calls} == set(images)
    assert len({thread_id for _, thread_id in calls}) == 3


def test_required_upload_gateway_does_not_require_web_images() -> None:
    """Workspace upload TLS support stays outside the Web image profile."""
    gateway_dependencies = set(
        inspect.signature(
            _CONFTEST_MODULE.azents_workspace_upload_gateway_container
        ).parameters
    )
    runtime_control_dependencies = set(
        inspect.signature(_CONFTEST_MODULE.azents_runtime_control_container).parameters
    )

    assert gateway_dependencies == {
        "container_network",
        "rustfs_container",
        "azents_web_gateway_tls_material",
    }
    assert "azents_workspace_upload_gateway_container" in runtime_control_dependencies
    assert "azents_admin_gateway_container" not in runtime_control_dependencies


def test_parallel_profile_reuses_preconfigured_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured immutable image is excluded from the concurrent build batch."""
    for image_build in _CONFTEST_MODULE._CORE_E2E_IMAGE_BUILDS:
        monkeypatch.delenv(image_build.environment_variable, raising=False)
    monkeypatch.setenv("AZENTS_E2E_SERVER_IMAGE", "registry/azents-server:test")
    calls: list[str] = []

    def fake_build(
        *,
        image_tag: str,
        dockerfile: Path,
        cache_repository: str | None,
        build_contexts: dict[str, str] | None = None,
        observability_image: str | None = None,
        build_mode: str = "full",
        builder_override: str | None = None,
        cache_backend_override: str | None = None,
    ) -> None:
        del (
            image_tag,
            dockerfile,
            build_contexts,
            build_mode,
            builder_override,
            cache_backend_override,
        )
        repository = observability_image or cache_repository
        assert repository is not None
        calls.append(repository)

    monkeypatch.setattr(_CONFTEST_MODULE, "_build_e2e_image", fake_build)

    with _CONFTEST_MODULE._e2e_image_preparation("required") as preparation:
        images = preparation.join(preparation.selected_images)

    assert images["azents-server"] == "registry/azents-server:test"
    assert set(calls) == {
        "azents-runtime-runner",
        "azents-runtime-provider-docker",
    }


def test_parallel_profile_accepts_fully_preconfigured_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fully prebuilt CI lane does not create an empty executor."""
    for image_build in _CONFTEST_MODULE._CORE_E2E_IMAGE_BUILDS:
        monkeypatch.setenv(
            image_build.environment_variable,
            f"registry/{image_build.cache_repository}:test",
        )

    with _CONFTEST_MODULE._e2e_image_preparation("required") as preparation:
        images = preparation.join(preparation.selected_images)

    assert images == {
        image_build.cache_repository: (f"registry/{image_build.cache_repository}:test")
        for image_build in _CONFTEST_MODULE._CORE_E2E_IMAGE_BUILDS
    }


def test_parallel_profile_rejects_unknown_suite() -> None:
    """CI cannot silently select an incomplete image portfolio."""
    with pytest.raises(
        RuntimeError,
        match="Unsupported AZENTS_E2E_IMAGE_BUILD_PROFILE",
    ):
        _CONFTEST_MODULE._e2e_image_preparation("unknown")


def test_image_build_observability_excludes_runtime_cache_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Timing evidence records only safe cache metadata."""
    monkeypatch.setenv(_CONFTEST_MODULE._E2E_ARTIFACT_DIR_ENV, str(tmp_path))
    _CONFTEST_MODULE._write_e2e_image_build_observability(
        cache_repository="azents-server",
        cache_backend="gha",
        cache_scope="azents-e2e-v1-azents-server",
        cache_export_enabled=True,
        completed=True,
        duration_seconds=12.34567,
        started_at_monotonic=100.0,
        finished_at_monotonic=112.34567,
    )

    assert (tmp_path / "image-build-timings.jsonl").read_text(encoding="utf-8") == (
        '{"build_mode": "full", "cache_backend": "gha", '
        '"cache_export_enabled": true, '
        '"cache_scope": "azents-e2e-v1-azents-server", "completed": true, '
        '"duration_seconds": 12.346, "finished_at_monotonic": 112.34567, '
        '"image": "azents-server", "started_at_monotonic": 100.0}\n'
    )
    records = parse_image_build_timings(tmp_path / "image-build-timings.jsonl")
    assert len(records) == 1
    assert records[0]["started_at_monotonic"] == 100.0
    assert records[0]["finished_at_monotonic"] == 112.34567
    assert records[0]["duration_seconds"] == 12.346


def test_web_profile_submits_each_selected_current_worktree_build_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Web portfolio retains its five-way concurrency without duplicate builds."""
    builds = _CONFTEST_MODULE._E2E_IMAGE_BUILD_PROFILES["web"]
    barrier = threading.Barrier(5, timeout=5)
    calls: list[tuple[str, str]] = []
    lock = threading.Lock()
    for image in builds:
        monkeypatch.delenv(image.environment_variable, raising=False)

    def build(image: e2e_conftest._E2EImageBuild, tag: str) -> None:
        with lock:
            calls.append((image.cache_repository, tag))
        barrier.wait()

    monkeypatch.setattr(_CONFTEST_MODULE, "_build_configured_e2e_image", build)
    with _CONFTEST_MODULE._e2e_image_preparation("web") as preparation:
        images = preparation.join(preparation.selected_images)
        assert preparation.join(preparation.selected_images) == images
    assert len(calls) == len(images) == 5
    assert dict(calls) == images


def test_unprofiled_image_resolution_remains_focused_and_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No selected portfolio exists locally until an image is explicitly requested."""
    monkeypatch.delenv("AZENTS_E2E_WEB_IMAGE", raising=False)
    calls: list[str] = []

    def build(image: e2e_conftest._E2EImageBuild, tag: str) -> None:
        calls.append(tag)

    monkeypatch.setattr(_CONFTEST_MODULE, "_build_configured_e2e_image", build)
    with _CONFTEST_MODULE._e2e_image_preparation(None) as preparation:
        assert preparation.join(preparation.selected_images) == {}
        assert calls == []
        image = _CONFTEST_MODULE._resolve_e2e_image(
            _CONFTEST_MODULE._WEB_IMAGE_BUILD, {}
        )
        assert calls == [image]
    assert preparation.futures == {}


def test_preparation_captures_environment_before_build_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prepared image references do not drift if the environment changes later."""
    for image in _CONFTEST_MODULE._CORE_E2E_IMAGE_BUILDS:
        monkeypatch.setenv(
            image.environment_variable, f"verified-{image.cache_repository}"
        )
    preparation = _CONFTEST_MODULE._e2e_image_preparation("required")
    monkeypatch.setenv("AZENTS_E2E_SERVER_IMAGE", "unverified-later")
    with preparation:
        assert preparation.join(["azents-server"]) == {
            "azents-server": "verified-azents-server"
        }
        assert preparation.futures == {}


def test_image_observability_io_failure_preserves_failed_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Diagnostic filesystem failures cannot replace the authoritative build error."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    monkeypatch.setenv(_CONFTEST_MODULE._E2E_ARTIFACT_DIR_ENV, str(blocked))
    primary = ValueError("authoritative build failure")

    def failed_build(**kwargs: object) -> None:
        raise primary

    monkeypatch.setattr(_CONFTEST_MODULE.pow_docker, "build", failed_build)
    with pytest.warns(UserWarning, match="Failed to write E2E image observability"):
        with pytest.raises(ValueError) as captured:
            _CONFTEST_MODULE._build_e2e_image(
                image_tag="current-server:test",
                dockerfile=REPOSITORY_ROOT / "azents.Dockerfile",
                cache_repository=None,
            )
    assert captured.value is primary
