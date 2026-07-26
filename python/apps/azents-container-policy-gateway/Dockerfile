FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

COPY --from=ghcr.io/astral-sh/uv:0.11.1@sha256:fc93e9ecd7218e9ec8fba117af89348eef8fd2463c50c13347478769aaedd0ce /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace/python/apps/azents-container-policy-gateway

COPY python/apps/azents-container-policy-gateway/pyproject.toml ./
COPY python/apps/azents-container-policy-gateway/uv.lock ./
COPY python/libs/azents-runtime-control /workspace/python/libs/azents-runtime-control
COPY python/apps/azents-container-policy-gateway/src ./src

RUN uv sync --frozen --no-dev \
    && groupadd --gid 1001 gateway \
    && useradd --uid 1001 --gid 1001 --no-create-home --home-dir /nonexistent gateway

USER 1001:1001

ENTRYPOINT ["/workspace/python/apps/azents-container-policy-gateway/.venv/bin/azents-container-policy-gateway"]
CMD ["serve"]
