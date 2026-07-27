"""Fixed Gateway, Engine, and Runner image contract tests."""

from pathlib import Path

from azents_container_policy_gateway.compatibility import (
    DOCKER_API_VERSION_VALUE,
    DOCKER_CLI_VERSION,
    DOCKER_COMPOSE_VERSION,
    DOCKER_ENGINE_VERSION,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_ENGINE_DIGEST = (
    "sha256:2a232a42256f70d78e3cc5d2b5d6b3276710a0de0596c145f627ecfae90282ac"
)
_CLI_DIGEST = "sha256:625d9431a9f54c5a2bc90f24f0e1c3d55b1349fd857dd85035f98c2c9acbdd4d"


def test_engine_image_is_fixed_to_the_compatibility_tuple() -> None:
    dockerfile = (
        _REPOSITORY_ROOT / "images/azents-runtime-engine/Dockerfile"
    ).read_text()

    assert f"FROM docker:{DOCKER_ENGINE_VERSION}-dind@{_ENGINE_DIGEST}" in dockerfile
    assert f'io.azents.docker.api-version="{DOCKER_API_VERSION_VALUE}"' in dockerfile
    assert f'io.azents.docker.engine-version="{DOCKER_ENGINE_VERSION}"' in dockerfile
    assert "addgroup -g 1001 azents-gateway" in dockerfile


def test_runner_image_contains_only_the_fixed_public_gateway_clients() -> None:
    dockerfile = (
        _REPOSITORY_ROOT / "python/apps/azents-runtime-runner/Dockerfile"
    ).read_text()

    assert f"FROM docker:{DOCKER_CLI_VERSION}-cli@{_CLI_DIGEST}" in dockerfile
    assert "COPY --from=docker-cli /usr/local/bin/docker" in dockerfile
    assert "docker/cli-plugins/docker-compose" in dockerfile
    assert f"ENV DOCKER_API_VERSION={DOCKER_API_VERSION_VALUE}" in dockerfile
    assert "ENV DOCKER_BUILDKIT=0" in dockerfile
    assert "ENV COMPOSE_DOCKER_CLI_BUILD=0" in dockerfile
    assert f"Docker Compose version v{DOCKER_COMPOSE_VERSION}" in dockerfile
    assert "/var/run/azents-engine/docker.sock" in dockerfile


def test_gateway_image_runs_as_the_fixed_unprivileged_user() -> None:
    dockerfile = (
        _REPOSITORY_ROOT / "python/apps/azents-container-policy-gateway/Dockerfile"
    ).read_text()

    assert "useradd --uid 1001 --gid 1001" in dockerfile
    assert "USER 1001:1001" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert (
        "ln -s /workspace/python/apps/azents-container-policy-gateway/"
        ".venv/bin/azents-container-policy-gateway "
        "/usr/local/bin/azents-container-policy-gateway"
    ) in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/azents-container-policy-gateway"]' in dockerfile
