"""Unit coverage for E2E image cache configuration."""

import importlib.util
import sys
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
        '{"cache_backend": "gha", "cache_export_enabled": true, '
        '"cache_scope": "azents-e2e-v1-azents-server", "completed": true, '
        '"duration_seconds": 12.346, "image": "azents-server"}\n'
    )
