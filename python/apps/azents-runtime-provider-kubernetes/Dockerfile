FROM python:3.14-slim@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83

COPY --from=ghcr.io/astral-sh/uv:0.11.33@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /uvx /bin/

WORKDIR /workspace/python/apps/azents-runtime-provider-kubernetes

COPY python/apps/azents-runtime-provider-kubernetes/pyproject.toml ./
COPY python/apps/azents-runtime-provider-kubernetes/uv.lock ./
COPY python/libs/azents-runtime-control /workspace/python/libs/azents-runtime-control
COPY python/apps/azents-runtime-provider-kubernetes/src ./src

RUN uv sync --frozen --no-dev

RUN useradd -m -s /bin/bash appuser
USER appuser

CMD [".venv/bin/python", "-m", "azents_runtime_provider_kubernetes.main"]
