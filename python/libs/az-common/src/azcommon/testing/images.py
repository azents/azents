"""Docker image utilities for testing.

CI 환경에서는 ECR pull-through cache를 사용하고,
로컬 환경에서는 Docker Hub를 직접 사용합니다.
"""

import os

_PUBLIC_ECR_DOCKER_HUB_LIBRARY = "public.ecr.aws/docker/library"
_PUBLIC_ECR_LIBRARY_IMAGES = frozenset({"postgres", "redis"})


def _split_image_name(image: str) -> tuple[str, str | None]:
    image_without_digest = image.split("@", maxsplit=1)[0]
    name_and_tag = image_without_digest.rsplit(":", maxsplit=1)
    if len(name_and_tag) == 1 or "/" in name_and_tag[-1]:
        return image_without_digest, None
    return name_and_tag[0], name_and_tag[1]


def get_docker_hub_image(image: str) -> str:
    """Docker 이미지 경로를 반환합니다.

    ECR_REGISTRY 환경변수가 설정된 경우 ECR pull-through cache를 사용합니다.
    그렇지 않으면 Docker Hub pull rate limit 을 피하기 위해 ECR Public 에
    mirror 가 있는 official library 이미지는 ECR Public 을 사용합니다.

    Args:
        image: Docker Hub 이미지 이름 (예: "rustfs/rustfs:latest")

    Returns:
        실제 사용할 이미지 경로
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
