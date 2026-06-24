---
title: "Azents rename phase 3: Python backend and runtime protocol"
created: 2026-05-26
tags: [backend, engine, api, documentation]
---

# Azents rename phase 3: Python backend and runtime protocol

## Scope

This phase renames backend/runtime Python packages, Python module imports,
runtime environment variable names, and runtime-control protobuf package names
from Azents to Azents.

This phase does not rename TypeScript apps/packages, Dart mobile code, Helm,
ArgoCD, Dockerfiles outside Python app images, generated OpenAPI clients, or
durable data resources.

## Source documents

- Design: `docs/azents/design/azents-rename-plan.md`
- Multi-phase plan: `docs/azents/plans/azents-rename-implementation-plan.md`
- Tracking issue: <https://github.com/azents/azents/issues/4079>

## Expected changes

### Python package paths

Rename these Python app/lib project paths:

- `python/apps/azents` -> `python/apps/azents`
- `python/apps/azents-discord-gateway` -> `python/apps/azents-discord-gateway`
- `python/apps/azents-runtime-provider-docker` -> `python/apps/azents-runtime-provider-docker`
- `python/apps/azents-runtime-provider-kubernetes` -> `python/apps/azents-runtime-provider-kubernetes`
- `python/apps/azents-runtime-runner` -> `python/apps/azents-runtime-runner`
- `python/libs/azents-runtime-control` -> `python/libs/azents-runtime-control`

Generated OpenAPI client libraries are intentionally left for the generated
client phase:

- `python/libs/azents-public-client`
- `python/libs/azents-admin-client`

### Python module names

Rename importable modules:

- `azents` -> `azents`
- `azents_runtime_control` -> `azents_runtime_control`
- `azents_runtime_provider_docker` -> `azents_runtime_provider_docker`
- `azents_runtime_provider_kubernetes` -> `azents_runtime_provider_kubernetes`
- `azents_runtime_runner` -> `azents_runtime_runner`

The standalone Discord gateway module name is currently `discord_gateway` and
does not need a Python import-module rename.

### Python package metadata

Update `pyproject.toml`, `uv.lock`, Dockerfile paths, and local source paths for
the renamed Python projects. Runtime app dependencies should use Azents package
names after the rename.

### Runtime environment variables

Rename runtime and backend environment variable names to `AZ_*` with no old
prefix aliases:

- `AZ_*` -> `AZ_*`
- `AZENTS_*` -> `AZ_*`
- Runtime provider/runner env vars such as `AZENTS_RUNTIME_CONTROL_ENDPOINT`
  become `AZ_RUNTIME_CONTROL_ENDPOINT`.
- Backend settings use `env_prefix="AZ_"`.

Before final durable data cutover, `AZ_RDB_*` and `AZ_WORKSPACE_S3_*` may still
point at existing Azents durable resources. This phase must not create or
rename RDS/S3 resources.

### Protobuf

Rename proto path/package:

- `proto/azents/runtime_control/v1/*.proto` ->
  `proto/azents/runtime_control/v1/*.proto`
- `package azents.runtime_control.v1;` ->
  `package azents.runtime_control.v1;`

Regenerate generated protobuf Python files in the renamed runtime-control lib.

## Expected exclusions

- Do not rename `docs/azents` or `testenv/azents` paths in this phase.
- Do not rename TypeScript packages or imports in this phase.
- Do not edit generated OpenAPI client code in this phase.
- Do not create Azents RDS, S3, RustFS, or database users.
- Do not add compatibility aliases for `AZ_*` or `AZENTS_*`.

## Verification

Run the strongest feasible subset:

```bash
cd python/apps/azents && uv run ruff check --fix . && uv run ruff format .
cd python/apps/azents && uv run pyright
cd python/apps/azents-runtime-provider-kubernetes && uv run pytest
cd python/apps/azents-runtime-runner && uv run pytest
cd python/libs/azents-runtime-control && uv run pytest
```

Also run targeted scans:

```bash
rg -n 'from azents|import azents|azents_runtime|AZENTS_|AZ_' python/apps/azents python/apps/azents-runtime-* python/libs/azents-runtime-control proto/azents
```

Some stale `azents` references may remain outside this phase by design,
especially docs, testenv, TypeScript, generated clients, and infra.
