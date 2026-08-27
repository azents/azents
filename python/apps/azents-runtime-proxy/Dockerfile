FROM python:3.14-slim@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83

COPY --from=ghcr.io/astral-sh/uv:0.11.33@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /uvx /bin/

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
