FROM docker:28.5.2-cli@sha256:625d9431a9f54c5a2bc90f24f0e1c3d55b1349fd857dd85035f98c2c9acbdd4d AS docker-cli

FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

COPY --from=ghcr.io/astral-sh/uv:0.11.1@sha256:fc93e9ecd7218e9ec8fba117af89348eef8fd2463c50c13347478769aaedd0ce /uv /uvx /bin/
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

ENV DOCKER_API_VERSION=1.51

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        bubblewrap \
        ca-certificates \
        curl \
        git \
        jq \
        sed \
        gawk \
        grep \
        findutils \
        coreutils \
        diffutils \
        patch \
        tree \
        util-linux \
        unzip \
        zip \
        tar \
        gzip \
        bzip2 \
        xz-utils \
        zstd \
        wget \
        dnsutils \
        iputils-ping \
        netcat-openbsd \
        build-essential \
        openssh-client \
        gnupg \
        vim-tiny \
        nano \
        libnspr4 \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2t64 \
        libxshmfence1 \
        libxfixes3 \
        libgtk-3-0 \
        fonts-liberation \
        less \
        file \
        bc \
        sqlite3 \
        graphviz \
    && rm -rf /var/lib/apt/lists/*

RUN chmod 4755 /usr/bin/bwrap

RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /usr/local/bin/corepack-shims \
    && corepack enable --install-directory /usr/local/bin/corepack-shims

RUN mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --break-system-packages \
        pandas \
        numpy \
        requests \
        httpx \
        pyyaml \
        toml \
        python-dotenv \
        openpyxl \
        xlsxwriter \
        csvkit \
        beautifulsoup4 \
        lxml \
        markdown \
        rich \
        pillow \
        matplotlib \
        click \
        tqdm \
        python-dateutil \
        pydantic \
        jinja2 \
        sympy \
        playwright

RUN playwright install-deps chromium

RUN docker --version | grep -F "Docker version 28.5.2" \
    && docker buildx version | grep -F "github.com/docker/buildx v0.29.1" \
    && docker compose version | grep -F "Docker Compose version v2.40.3" \
    && bwrap --version \
    && bwrap --help | grep -F -- "--seccomp" \
    && test -u /usr/bin/bwrap \
    && unshare --version \
    && test ! -e /var/run/azents-engine/docker.sock

WORKDIR /workspace/python/apps/azents-runtime-runner

COPY python/apps/azents-runtime-runner/pyproject.toml ./
COPY python/apps/azents-runtime-runner/uv.lock ./
COPY python/libs/azents-runtime-control /workspace/python/libs/azents-runtime-control
COPY python/apps/azents-runtime-runner/src ./src

RUN uv sync --frozen --no-dev

COPY python/apps/azents-runtime-runner/docker/azents-git-credential.sh /usr/local/bin/azents-git-credential
RUN chmod +x /usr/local/bin/azents-git-credential \
    && git config --system credential.helper '!/usr/local/bin/azents-git-credential' \
    && git config --system credential.useHttpPath true

RUN groupadd --gid 1000 agent \
    && useradd --uid 1000 --gid 1000 -m -d /home/agent -s /bin/bash agent

ENV HOME=/home/agent
ENV PATH=/usr/local/bin/corepack-shims:/home/agent/.local/bin:${PATH}
WORKDIR /workspace/python/apps/azents-runtime-runner

USER agent

CMD ["/workspace/python/apps/azents-runtime-runner/.venv/bin/python", "-m", "azents_runtime_runner.main"]
