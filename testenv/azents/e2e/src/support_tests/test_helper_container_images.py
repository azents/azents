"""Regression coverage for E2E Python helper container images."""

import importlib.util
import sys
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest

from support.consts import REPOSITORY_ROOT

_CONFTEST_PATH = REPOSITORY_ROOT / "testenv/azents/e2e/src/tests/conftest.py"
_CONFTEST_SPEC = importlib.util.spec_from_file_location(
    "e2e_helper_container_conftest",
    _CONFTEST_PATH,
)
assert _CONFTEST_SPEC is not None
assert _CONFTEST_SPEC.loader is not None
_CONFTEST_MODULE = importlib.util.module_from_spec(_CONFTEST_SPEC)
sys.modules[_CONFTEST_SPEC.name] = _CONFTEST_MODULE
_CONFTEST_SPEC.loader.exec_module(_CONFTEST_MODULE)


class _FakeDockerContainer:
    """Record the image used by a fluent testcontainers fixture."""

    created_images: list[str] = []

    def __init__(self, image: str, **kwargs: object) -> None:
        del kwargs
        self.created_images.append(image)

    def __getattr__(self, name: str) -> Any:
        del name
        return lambda *args, **kwargs: self

    def __enter__(self) -> "_FakeDockerContainer":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def get_container_host_ip(self) -> str:
        return "127.0.0.1"

    def get_exposed_port(self, port: int) -> int:
        return port


@pytest.mark.parametrize(
    ("fixture_name", "fixture_kwargs"),
    [
        (
            "openai_proxy_container",
            {
                "container_network": object(),
                "mock_openai_container": object(),
            },
        ),
        (
            "github_validation_proxy_container",
            {"container_network": object()},
        ),
        (
            "slack_provider_fake_container",
            {"container_network": object()},
        ),
    ],
)
def test_python_helpers_reuse_prepared_server_image(
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
    fixture_kwargs: dict[str, object],
) -> None:
    """Local helper services must not add a standalone Docker Hub image pull."""
    prepared_image = "azents-server:e2e-prepared"
    _FakeDockerContainer.created_images = []
    monkeypatch.setattr(
        _CONFTEST_MODULE,
        "DockerContainer",
        _FakeDockerContainer,
    )
    monkeypatch.setattr(
        _CONFTEST_MODULE.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200),
    )
    fixture = getattr(_CONFTEST_MODULE, fixture_name)
    generator: Generator[object, None, None] = fixture.__wrapped__(
        **fixture_kwargs,
        azents_server_image=prepared_image,
    )

    next(generator)
    with pytest.raises(StopIteration):
        next(generator)

    assert _FakeDockerContainer.created_images == [prepared_image]
