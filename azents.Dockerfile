FROM python:3.14-bookworm@sha256:ecac9e212daacda8a702eae372fceebc0ee36f5805abe087880367e8d061fa5b AS base

ARG ROOT_DIR=/app

ENV VIRTUAL_ENV="${ROOT_DIR}/.venv"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.6@sha256:88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d /uv /uvx /bin/

WORKDIR $ROOT_DIR

# Install dependencies
ENV UV_CACHE_DIR=/tmp/uv_cache
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT="${VIRTUAL_ENV}"
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files
COPY python/apps/azents/pyproject.toml $ROOT_DIR/python/apps/azents/
COPY python/apps/azents/uv.lock $ROOT_DIR/python/apps/azents/

# Install dependencies
ARG DEV=false
WORKDIR $ROOT_DIR/python/apps/azents
RUN --mount=type=cache,target=$UV_CACHE_DIR \
    --mount=type=bind,source=python/libs/az-common,target=$ROOT_DIR/python/libs/az-common \
    --mount=type=bind,source=python/libs/azents-runtime-control,target=$ROOT_DIR/python/libs/azents-runtime-control \
    if [ "$DEV" ]; then \
    uv sync --frozen --no-install-project; \
    else \
    uv sync --frozen --no-dev --no-install-project; \
    fi

FROM base AS runtime

# Copy virtual environment
COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

# Copy source code
COPY python/apps/azents/ $ROOT_DIR/python/apps/azents/
COPY python/libs/az-common/ $ROOT_DIR/python/libs/az-common/
COPY python/libs/azents-runtime-control/ $ROOT_DIR/python/libs/azents-runtime-control/

WORKDIR $ROOT_DIR/python/apps/azents

ENV PYTHONPATH="${ROOT_DIR}/python/apps/azents/src"
CMD ["./bin/apiserver.sh"]
