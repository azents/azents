"""Docker image path conversion tests."""

import pytest

from azcommon.testing.images import get_docker_hub_image


def test_get_docker_hub_image_keeps_postgres_on_docker_hub_without_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Postgres stays on Docker Hub because ECR Public tag coverage is incomplete."""
    monkeypatch.delenv("ECR_REGISTRY", raising=False)

    image = get_docker_hub_image("postgres:18")

    assert image == "postgres:18"


def test_get_docker_hub_image_uses_configured_pull_through_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ECR_REGISTRY keeps using the configured pull-through cache path."""
    registry = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com"
    monkeypatch.setenv("ECR_REGISTRY", registry)

    image = get_docker_hub_image("postgres:18")

    assert image == f"{registry}/docker-hub/library/postgres:18"


def test_get_docker_hub_image_keeps_non_library_images_without_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Images without a known ECR Public mirror stay on Docker Hub."""
    monkeypatch.delenv("ECR_REGISTRY", raising=False)

    image = get_docker_hub_image("rustfs/rustfs:1.0.0-alpha.90")

    assert image == "rustfs/rustfs:1.0.0-alpha.90"
