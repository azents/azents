"""Docker image utilities for testing.

CI can use an ECR pull-through cache when configured. Local environments use
Docker Hub directly.
"""

import os

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

    When ECR_REGISTRY is set, use the configured ECR pull-through cache.
    Otherwise, only use ECR Public for known official library mirrors whose
    tags are consistently available; keep all other images on Docker Hub.

    Args:
        image: Docker Hub image name, for example ``rustfs/rustfs:latest``.

    Returns:
        Image reference to pull.
    """
    ecr_registry = os.environ.get("ECR_REGISTRY")
    if ecr_registry:
        if "/" not in image:
            image = f"library/{image}"
        return f"{ecr_registry}/docker-hub/{image}"

    image_name, image_tag = _split_image_name(image)
    if "/" not in image_name and image_name in _PUBLIC_ECR_LIBRARY_IMAGES:
        tag_suffix = f":{image_tag}" if image_tag else ""
        return f"{_PUBLIC_ECR_DOCKER_HUB_LIBRARY}/{image_name}{tag_suffix}"

    return image
