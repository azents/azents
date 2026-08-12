FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

COPY --from=ghcr.io/astral-sh/uv:0.11.1@sha256:fc93e9ecd7218e9ec8fba117af89348eef8fd2463c50c13347478769aaedd0ce /uv /uvx /bin/

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
