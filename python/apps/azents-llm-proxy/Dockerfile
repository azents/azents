FROM python:3.14-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8 AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.6@sha256:88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d /uv /bin/uv
WORKDIR /opt/azents/python/apps/azents-llm-proxy
COPY python/libs/azents-llm-contract /opt/azents/python/libs/azents-llm-contract
COPY python/apps/azents-llm-proxy/pyproject.toml python/apps/azents-llm-proxy/uv.lock python/apps/azents-llm-proxy/LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --no-install-project --no-build-package litellm
COPY python/apps/azents-llm-proxy/src ./src
# Refresh only the local app wheel; cached metadata must not hide source edits.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --offline --reinstall-package azents-llm-proxy

FROM python:3.14-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8
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
