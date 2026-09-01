FROM docker:29.7.2-cli@sha256:000bb62ff495f986c9f5578eb67cc2cb98b91138eda81d7762d5371eb8a497fe AS docker-cli

FROM nixos/nix:2.35.2@sha256:7a007c766426c1877758ddc5cb87a965ac131fc78c582ce0083d922d51ae945c AS nix-seed

ARG NIX_VERSION=2.35.2
ARG NIXPKGS_REVISION=c5c4a43b0e8056328ec4529f735cabdb8f1942bb
ARG NIX_SEED_GENERATION=nix-2.35.2-nixpkgs-c5c4a43b0e8056328ec4529f735cabdb8f1942bb

ENV NIX_VERSION=${NIX_VERSION}
ENV NIXPKGS_REVISION=${NIXPKGS_REVISION}
ENV SEED_GENERATION=${NIX_SEED_GENERATION}

COPY python/apps/azents-runtime-runner/docker/build-nix-seed.sh /usr/local/bin/build-nix-seed
RUN chmod +x /usr/local/bin/build-nix-seed \
    && /usr/local/bin/build-nix-seed

FROM python:3.14-slim@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83

COPY --from=ghcr.io/astral-sh/uv:0.12.6@sha256:88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d /uv /uvx /bin/
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

ENV DOCKER_API_VERSION=1.51

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
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

RUN docker --version | grep -F "Docker version 29.7.2" \
    && docker buildx version | grep -F "github.com/docker/buildx v0.36.1" \
    && docker compose version | grep -F "Docker Compose version v5.4.0" \
    && unshare --version \
    && test ! -e /var/run/azents-engine/docker.sock

WORKDIR /workspace/python/apps/azents-runtime-runner

COPY python/apps/azents-runtime-runner/pyproject.toml ./
COPY python/apps/azents-runtime-runner/uv.lock ./
COPY python/libs/azents-runtime-control /workspace/python/libs/azents-runtime-control
COPY python/apps/azents-runtime-runner/src ./src

RUN uv sync --frozen --no-dev

COPY python/apps/azents-runtime-runner/docker/azents-git-credential.sh /usr/local/bin/azents-git-credential
COPY python/apps/azents-runtime-runner/docker/azents-nix-profile.sh /etc/profile.d/azents-nix.sh
COPY --from=nix-seed --chown=1000:1000 /opt/azents/nix-seed /opt/azents/nix-seed
RUN chmod +x /usr/local/bin/azents-git-credential \
    && chmod 644 /etc/profile.d/azents-nix.sh \
    && git config --system credential.helper '!/usr/local/bin/azents-git-credential' \
    && git config --system credential.useHttpPath true

RUN groupadd --gid 1000 agent \
    && useradd --uid 1000 --gid 1000 -m -d /home/agent -s /bin/bash agent

ENV HOME=/home/agent
ENV PATH=/nix/var/state/azents-agent/profiles/profile/bin:/nix/var/nix/profiles/azents-release/bin:/usr/local/bin/corepack-shims:/home/agent/.local/bin:${PATH}
WORKDIR /workspace/python/apps/azents-runtime-runner

USER agent

CMD ["/workspace/python/apps/azents-runtime-runner/.venv/bin/python", "-m", "azents_runtime_runner.main"]
