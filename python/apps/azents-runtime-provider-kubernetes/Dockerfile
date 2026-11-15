FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

COPY --from=ghcr.io/astral-sh/uv:0.12.6@sha256:88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d /uv /uvx /bin/

WORKDIR /workspace/python/apps/azents-runtime-provider-kubernetes

COPY python/apps/azents-runtime-provider-kubernetes/pyproject.toml ./
COPY python/apps/azents-runtime-provider-kubernetes/uv.lock ./
COPY python/libs/azents-runtime-control /workspace/python/libs/azents-runtime-control
COPY python/apps/azents-runtime-provider-kubernetes/src ./src

RUN uv sync --frozen --no-dev

RUN useradd -m -s /bin/bash appuser
USER appuser

CMD [".venv/bin/python", "-m", "azents_runtime_provider_kubernetes.main"]
