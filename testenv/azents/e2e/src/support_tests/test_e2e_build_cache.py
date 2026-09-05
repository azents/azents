"""Unit coverage for E2E image cache configuration."""

import importlib.util
import sys
import threading
from pathlib import Path

import pytest

from support.consts import REPOSITORY_ROOT

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


def test_gha_cache_imports_every_image_and_exports_only_owned_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GHA cache scopes are per image and use max-mode only for the owner."""
    monkeypatch.setenv(_CONFTEST_MODULE._DOCKER_BUILDER_ENV, "e2e-builder")
    monkeypatch.setenv(
        _CONFTEST_MODULE._GHA_DOCKER_CACHE_SCOPE_PREFIX_ENV,
        "azents-e2e-v1",
    )
    monkeypatch.setenv(
        _CONFTEST_MODULE._GHA_DOCKER_CACHE_WRITE_REPOSITORIES_ENV,
        "azents-server,azents-web",
    )

    cache_from, cache_to, backend, scope = (
        _CONFTEST_MODULE._get_e2e_image_cache_options("azents-server")
    )

    assert cache_from == [{"type": "gha", "scope": "azents-e2e-v1-azents-server"}]
    assert cache_to == {
        "type": "gha",
        "scope": "azents-e2e-v1-azents-server",
        "mode": "max",
        "ignore-error": "true",
    }
    assert backend == "gha"
    assert scope == "azents-e2e-v1-azents-server"

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
        _CONFTEST_MODULE._get_e2e_image_cache_options("azents-server")


def test_build_passes_gha_cache_options_to_buildx_and_records_duration(
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
    monkeypatch.setenv(
        _CONFTEST_MODULE._GHA_DOCKER_CACHE_WRITE_REPOSITORIES_ENV,
        "azents-server",
    )
    monkeypatch.setenv(_CONFTEST_MODULE._E2E_ARTIFACT_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(_CONFTEST_MODULE.pow_docker, "build", fake_build)

    _CONFTEST_MODULE._build_e2e_image(
        image_tag="azents-e2e:test",
        dockerfile=REPOSITORY_ROOT / "azents.Dockerfile",
        cache_repository="azents-server",
    )

    assert build_arguments["builder"] == "e2e-builder"
    assert build_arguments["cache_from"] == [
        {"type": "gha", "scope": "azents-e2e-v1-azents-server"}
    ]
    assert build_arguments["cache_to"] == {
        "type": "gha",
        "scope": "azents-e2e-v1-azents-server",
        "mode": "max",
        "ignore-error": "true",
    }
    assert '"completed": true' in (tmp_path / "image-build-timings.jsonl").read_text(
        encoding="utf-8"
    )


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
    assert build_arguments["cache_from"] is None
    assert build_arguments["cache_to"] is None
    assert build_arguments["builder"] == "default"


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
        cache_repository: str,
        build_contexts: dict[str, str] | None = None,
    ) -> None:
        del image_tag, dockerfile, build_contexts
        calls.append((cache_repository, threading.get_ident()))
        barrier.wait()

    monkeypatch.setattr(_CONFTEST_MODULE, "_build_e2e_image", fake_build)

    images = _CONFTEST_MODULE._prepare_e2e_images("required")

    assert set(images) == {
        "azents-server",
        "azents-runtime-runner",
        "azents-runtime-provider-docker",
    }
    assert {repository for repository, _ in calls} == set(images)
    assert len({thread_id for _, thread_id in calls}) == 3


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
        cache_repository: str,
        build_contexts: dict[str, str] | None = None,
    ) -> None:
        del image_tag, dockerfile, build_contexts
        calls.append(cache_repository)

    monkeypatch.setattr(_CONFTEST_MODULE, "_build_e2e_image", fake_build)

    images = _CONFTEST_MODULE._prepare_e2e_images("required")

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

    images = _CONFTEST_MODULE._prepare_e2e_images("required")

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
        _CONFTEST_MODULE._prepare_e2e_images("unknown")


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
    )

    assert (tmp_path / "image-build-timings.jsonl").read_text(encoding="utf-8") == (
        '{"build_mode": "full", "cache_backend": "gha", '
        '"cache_export_enabled": true, '
        '"cache_scope": "azents-e2e-v1-azents-server", "completed": true, '
        '"duration_seconds": 12.346, "image": "azents-server"}\n'
    )
