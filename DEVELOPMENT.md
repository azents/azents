# Azents Development

This guide covers the local development commands and repository layout for
contributors working on Azents.

## Repository Structure

| Path | Purpose |
| --- | --- |
| `python/apps/azents/` | Azents API server, worker, scheduler, and domain logic |
| `python/apps/azents-runtime-runner/` | Runtime runner image and entrypoint |
| `python/apps/azents-runtime-provider-docker/` | Docker runtime provider |
| `python/apps/azents-runtime-provider-kubernetes/` | Kubernetes runtime provider |
| `python/libs/az-common/` | Shared Python utilities |
| `python/libs/azents-runtime-control/` | Runtime control protocol/client |
| `python/libs/azents-public-client/` | Generated Python public API client |
| `python/libs/azents-admin-client/` | Generated Python admin API client |
| `typescript/apps/azents-web/` | Main Azents web application |
| `typescript/apps/azents-admin-web/` | Admin web application |
| `typescript/apps/azents-site/` | Public Azents website |
| `typescript/packages/azents-public-client/` | Generated TypeScript public API client |
| `typescript/packages/azents-admin-client/` | Generated TypeScript admin API client |
| `testenv/azents/` | Local fixtures, prerequisite checks, and E2E substrate |
| `docs/azents/` | ADR, design notes, and living specs |
| `infra/charts/azents/` | Helm chart |
| `proto/azents/` | Runtime control protobuf definitions |

## Local Development

Start local dependencies:

```console
$ docker compose -f docker-compose.azents.yaml up -d
```

Run the backend:

```console
$ cd python/apps/azents
$ uv run python -m azents
```

For Redis-free single-process operation, use the all-in-one backend without reload:

```console
$ cd python/apps/azents
$ AZ_SESSION_BROKER_BACKEND=memory uv run python src/cli/devserver.py
```

This shares memory-backed Session routing, broadcast/live state and Runtime
coordination across APIs, Worker, Scheduler and Runtime Control. Redis does not
need to be running. PostgreSQL, object storage and the usual trusted Runtime
Control/Transfer configuration are still required. Memory state is disposable on
restart; durable recovery remains PostgreSQL-backed. `--reload` and standalone
role processes reject this mode because they cannot share the memory owners.
The default `AZ_SESSION_BROKER_BACKEND=redis` is unchanged for distributed runs.

Run the web app:

```console
$ cd typescript
$ pnpm install
$ pnpm run dev --filter=@azents/web
```

Run the public website:

```console
$ cd typescript
$ pnpm install
$ pnpm run dev --filter=@azents/site
```

## Quality Checks

Python backend:

```console
$ cd python/apps/azents
$ uv run ruff check --fix .
$ uv run ruff format .
$ uv run ty check --error-on-warning
```

Python shared library:

```console
$ cd python/libs/az-common
$ uv run ruff check --fix .
$ uv run ruff format .
$ uv run ty check --error-on-warning
```

TypeScript workspace:

```console
$ cd typescript
$ pnpm run format
$ pnpm run lint
$ pnpm run typecheck
```

Azents E2E:

```console
$ cd testenv/azents/e2e
$ uv run pytest ./src
```

## OpenAPI Clients

Backend OpenAPI specs are emitted from `python/apps/azents/specs/` and consumed
by Python and TypeScript generated clients.

```console
$ cd python/apps/azents
$ uv run python src/cli/dump_openapi.py

$ cd ../../../typescript
$ pnpm run generate --filter=@azents/public-client --filter=@azents/admin-client
```

## Deployment Artifacts

- Container images are built from the Azents Dockerfiles in this repository.
- The Helm chart lives at `infra/charts/azents/`.
- The public project website lives at `typescript/apps/azents-site/`.
