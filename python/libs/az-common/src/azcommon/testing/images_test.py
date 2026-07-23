"""Docker image path conversion tests."""

from azcommon.testing.images import get_docker_hub_image


def test_get_docker_hub_image_keeps_postgres_on_docker_hub() -> None:
    """Postgres stays on Docker Hub because ECR Public tag coverage is incomplete."""
    image = get_docker_hub_image("postgres:18")

    assert image == "postgres:18"


def test_get_docker_hub_image_keeps_non_library_images() -> None:
    """Images without a known ECR Public mirror stay on Docker Hub."""
    image = get_docker_hub_image("rustfs/rustfs:1.0.0-alpha.90")

    assert image == "rustfs/rustfs:1.0.0-alpha.90"
