FROM public.ecr.aws/docker/library/python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /uvx /bin/

WORKDIR /workspace/python/apps/azents-runtime-provider-docker

COPY python/apps/azents-runtime-provider-docker/pyproject.toml ./
COPY python/apps/azents-runtime-provider-docker/uv.lock ./
COPY python/libs/azents-runtime-control /workspace/python/libs/azents-runtime-control
COPY python/apps/azents-runtime-provider-docker/src ./src

RUN uv sync --frozen --no-dev

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 -m -s /bin/bash appuser
USER appuser

CMD [".venv/bin/python", "-m", "azents_runtime_provider_docker.main"]
