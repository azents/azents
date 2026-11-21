FROM python:3.15.2-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.6@sha256:88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d /uv /bin/uv
WORKDIR /opt/azents/python/apps/azents-llm-proxy
COPY python/libs/azents-llm-contract /opt/azents/python/libs/azents-llm-contract
COPY python/apps/azents-llm-proxy/pyproject.toml python/apps/azents-llm-proxy/uv.lock python/apps/azents-llm-proxy/LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --no-install-project --no-build-package litellm
COPY python/apps/azents-llm-proxy/src ./src
# Refresh only the local app wheel; cached metadata must not hide source edits.
# Build backends may need downloading when a cached layer outlives its uv cache.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --reinstall-package azents-llm-proxy

FROM python:3.15.2-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
ENV PYTHONUNBUFFERED=1 PYTHON_DOTENV_DISABLED=1 LITELLM_LOCAL_MODEL_COST_MAP=True
ENV PATH="/opt/azents/python/apps/azents-llm-proxy/.venv/bin:$PATH"
COPY --from=build /opt/azents/python/apps/azents-llm-proxy/.venv /opt/azents/python/apps/azents-llm-proxy/.venv
COPY python/apps/azents-llm-proxy/NOTICE.md /usr/share/doc/azents-llm-proxy/NOTICE.md
COPY python/apps/azents-llm-proxy/LICENSE /usr/share/doc/azents-llm-proxy/LICENSE
RUN mkdir -p /usr/share/doc/azents-llm-proxy /home/proxy \
    && python -m azents_llm_proxy.audit > /usr/share/doc/azents-llm-proxy/inventory.json \
    && chown 65532:65532 /home/proxy
ENV HOME=/home/proxy
USER 65532:65532
WORKDIR /home/proxy
EXPOSE 4000
ENTRYPOINT ["python", "-m", "azents_llm_proxy"]
