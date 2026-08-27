FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

COPY --from=ghcr.io/astral-sh/uv:0.12.6@sha256:88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d /uv /uvx /bin/

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
