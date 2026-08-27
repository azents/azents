FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

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
