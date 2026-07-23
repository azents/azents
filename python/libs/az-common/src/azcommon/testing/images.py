"""Docker image utilities for testing."""

_PUBLIC_ECR_DOCKER_HUB_LIBRARY = "public.ecr.aws/docker/library"
_PUBLIC_ECR_LIBRARY_IMAGES = frozenset({"redis"})


def _split_image_name(image: str) -> tuple[str, str | None]:
    image_without_digest = image.split("@", maxsplit=1)[0]
    name_and_tag = image_without_digest.rsplit(":", maxsplit=1)
    if len(name_and_tag) == 1 or "/" in name_and_tag[-1]:
        return image_without_digest, None
    return name_and_tag[0], name_and_tag[1]


def get_docker_hub_image(image: str) -> str:
    """Return the Docker image reference to use for tests.

    Use ECR Public only for known official library mirrors whose tags are
    consistently available; keep all other images on Docker Hub.

    Args:
        image: Docker Hub image name, for example ``rustfs/rustfs:latest``.

    Returns:
        Image reference to pull.
    """
    image_name, image_tag = _split_image_name(image)
    if "/" not in image_name and image_name in _PUBLIC_ECR_LIBRARY_IMAGES:
        tag_suffix = f":{image_tag}" if image_tag else ""
        return f"{_PUBLIC_ECR_DOCKER_HUB_LIBRARY}/{image_name}{tag_suffix}"

    return image
