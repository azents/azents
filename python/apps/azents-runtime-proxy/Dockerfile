FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

COPY --from=ghcr.io/astral-sh/uv:0.12.6@sha256:88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d /uv /uvx /bin/

WORKDIR /workspace/python/apps/azents-runtime-proxy

COPY python/apps/azents-runtime-proxy/pyproject.toml ./
COPY python/apps/azents-runtime-proxy/uv.lock ./
COPY python/apps/azents-runtime-proxy/src ./src

RUN uv sync --frozen --no-dev

RUN groupadd --gid 1000 azents-proxy \
    && useradd --uid 1000 --gid 1000 -m -d /home/azents-proxy -s /usr/sbin/nologin azents-proxy \
    && mkdir -p /var/run/azents-proxy \
    && chown azents-proxy:azents-proxy /var/run/azents-proxy

ENV HOME=/home/azents-proxy
ENV PYTHONDONTWRITEBYTECODE=1
ENV AZ_RUNTIME_PROXY_MITMPROXY_CONFDIR=/var/run/azents-proxy/mitmproxy

USER azents-proxy

CMD ["/workspace/python/apps/azents-runtime-proxy/.venv/bin/python", "-m", "azents_runtime_proxy.main", "run"]
