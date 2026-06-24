FROM public.ecr.aws/docker/library/python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /uvx /bin/

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
    && useradd --uid 1000 --gid 1000 -m -d /workspace/agent -s /bin/bash agent

ENV HOME=/workspace/agent
ENV PATH=/usr/local/bin/corepack-shims:/workspace/agent/.local/bin:${PATH}
WORKDIR /workspace/agent

USER agent

CMD ["/workspace/python/apps/azents-runtime-runner/.venv/bin/python", "-m", "azents_runtime_runner.main"]
