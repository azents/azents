# Azents Python Projects

This directory contains Azents Python applications and libraries.

```text
python/
├── apps/
│   ├── azents/                              # API server, worker, scheduler, CLI
│   ├── azents-runtime-runner/               # Runtime runner image
│   ├── azents-runtime-provider-docker/      # Docker runtime provider
│   └── azents-runtime-provider-kubernetes/  # Kubernetes runtime provider
└── libs/
    ├── az-common/                           # Shared utilities
    ├── azents-runtime-control/              # Runtime control protocol/client
    ├── azents-public-client/                # Generated public API client
    └── azents-admin-client/                 # Generated admin API client
```

## Commands

Run commands from the relevant subproject directory.

```console
$ uv run ruff check --fix .
$ uv run ruff format .
$ uv run pyright
$ uv run pytest
```

Backend development server:

```console
$ cd python/apps/azents
$ uv run python -m azents
```

OpenAPI dump:

```console
$ cd python/apps/azents
$ uv run python src/cli/dump_openapi.py
```

## Dependency Rules

- Apps may depend on libraries under `python/libs/`.
- Apps must not depend on other apps.
- Generated clients should be regenerated from OpenAPI specs instead of edited manually.
