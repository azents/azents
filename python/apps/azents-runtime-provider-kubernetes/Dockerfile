FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

COPY --from=ghcr.io/astral-sh/uv:0.11.33@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /uvx /bin/

WORKDIR /workspace/python/apps/azents-runtime-provider-kubernetes

COPY python/apps/azents-runtime-provider-kubernetes/pyproject.toml ./
COPY python/apps/azents-runtime-provider-kubernetes/uv.lock ./
COPY python/libs/azents-runtime-control /workspace/python/libs/azents-runtime-control
COPY python/apps/azents-runtime-provider-kubernetes/src ./src

# Hotfix the stale probe contract in the deployed Provider image so it matches
# the immutable Docker 29.7.2 engine image while the source-level fix follows.
RUN sed -i "s/= '28.5.2\/1.51'/= '29.7.2\/1.55'/" \
      src/azents_runtime_provider_kubernetes/provider.py \
    && grep -F "= '29.7.2/1.55'" \
      src/azents_runtime_provider_kubernetes/provider.py \
    && uv sync --frozen --no-dev

RUN useradd -m -s /bin/bash appuser
USER appuser

CMD [".venv/bin/python", "-m", "azents_runtime_provider_kubernetes.main"]
