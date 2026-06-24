"""Docker 이미지 경로 변환 테스트."""

import pytest

from azcommon.testing.images import get_docker_hub_image


def test_get_docker_hub_image_uses_public_ecr_for_postgres_without_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ECR_REGISTRY 가 없어도 Postgres 는 ECR Public mirror 를 사용합니다."""
    monkeypatch.delenv("ECR_REGISTRY", raising=False)

    image = get_docker_hub_image("postgres:18")

    assert image == "public.ecr.aws/docker/library/postgres:18"


def test_get_docker_hub_image_uses_configured_pull_through_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ECR_REGISTRY 가 있으면 기존 pull-through cache 경로를 우선합니다."""
    registry = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com"
    monkeypatch.setenv("ECR_REGISTRY", registry)

    image = get_docker_hub_image("postgres:18")

    assert image == f"{registry}/docker-hub/library/postgres:18"


def test_get_docker_hub_image_keeps_non_library_images_without_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ECR Public mirror 를 확정할 수 없는 이미지는 Docker Hub 경로를 유지합니다."""
    monkeypatch.delenv("ECR_REGISTRY", raising=False)

    image = get_docker_hub_image("rustfs/rustfs:1.0.0-alpha.90")

    assert image == "rustfs/rustfs:1.0.0-alpha.90"
