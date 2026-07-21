# Project Rules for Azents

Azents is an AI agent platform. This repository contains the backend, runtime providers, web frontends, test substrate, documentation, and Helm chart.

## Language Rule

- Write all git-tracked artifacts in English.
- Intentional non-English text is allowed only when the artifact itself is localized text or a locale sample.
- Record project decisions, design notes, comments, documentation, commit-facing text, and code-facing text in English even when chat discussion happened in another language.

## Repository Structure

| Path | Purpose |
| --- | --- |
| `python/apps/azents/` | Backend API server, worker, scheduler, CLI, DB schemas |
| `python/apps/azents-runtime-runner/` | Runtime runner image and entrypoint |
| `python/apps/azents-runtime-provider-docker/` | Docker runtime provider |
| `python/apps/azents-runtime-provider-kubernetes/` | Kubernetes runtime provider |
| `python/libs/az-common/` | Shared Python utilities |
| `python/libs/azents-runtime-control/` | Runtime control protocol/client |
| `python/libs/azents-public-client/` | Generated Python public API client |
| `python/libs/azents-admin-client/` | Generated Python admin API client |
| `typescript/apps/azents-web/` | Main web app |
| `typescript/apps/azents-admin-web/` | Admin web app |
| `typescript/packages/azents-public-client/` | Generated TypeScript public API client |
| `typescript/packages/azents-admin-client/` | Generated TypeScript admin API client |
| `testenv/azents/` | Fixture/prerequisite support and E2E tests |
| `docs/azents/` | ADR, design, issues, notes, plans, and living specs |
| `infra/charts/azents/` | Helm chart |
| `proto/azents/` | Runtime control protobuf definitions |

## Conventions System

Detailed coding rules live under `.claude/conventions/` and are indexed by `.claude/rules/`.

- Always start with `.claude/rules/conventions.md`.
- For Python work, also read `.claude/rules/python-conventions.md` when relevant.
- For TypeScript work, also read `.claude/rules/typescript-conventions.md` when relevant.
- For test substrate work, read `.claude/rules/testenv-conventions.md`.
- For infrastructure/Helm work, read `.claude/rules/infra-conventions.md`.
- Do not bulk-read every convention body. Read only bodies whose title applies to the change.

## Development Environment

```console
$ docker compose -f docker-compose.azents.yaml up -d
```

Backend:

```console
$ cd python/apps/azents
$ uv run python -m azents
```

Web:

```console
$ cd typescript
$ pnpm install
$ pnpm run dev --filter=@azents/web
```

## Python Commands

Run commands from the relevant Python subproject directory.

```console
$ uv run ruff check --fix .
$ uv run ruff format .
$ uv run pyright
$ uv run pytest
```

Azents-specific backend commands:

```console
$ cd python/apps/azents
$ uv run python src/cli/dump_openapi.py
$ uv run python -m azents
```

## TypeScript Commands

Run from `typescript/`.

```console
$ pnpm install
$ pnpm run format
$ pnpm run lint
$ pnpm run typecheck
$ pnpm run build
$ pnpm run dev --filter=@azents/web
$ pnpm run dev --filter=@azents/admin-web
```

## Azents Documentation System

The azents project uses the Living Spec system:

- **Requirements** (`docs/azents/requirements/`) — confirmed user needs and acceptance criteria for one development snapshot. Implemented Requirements are immutable.
- **SPEC.md** (`docs/azents/spec/`) — current system behavior. Update when code changes.
- **ADR** (`docs/azents/adr/`) — append-only decision history. Implemented/adopted ADRs are immutable.
- **Design** (`docs/azents/design/`) — development-time design documents. Do not rewrite implemented design documents as living specs; current behavior belongs in spec docs.

New feature-design snapshots use one shared `{word}-{YYMMDD}-{slug}.md` basename across Requirements, ADR, and Design. Use `{word}-{YYMMDD}` as the snapshot ID and typed references such as `<snapshot>/REQ-N`, `<snapshot>/ADR-DN`, and `<snapshot>/DESIGN`. Existing numbered ADRs, Design filenames, and legacy references remain unchanged.

Always read `docs/azents/spec/` first for current behavior. Read Requirements, ADRs, and design documents only when product intent, rationale, or historical context is needed.

When modifying azents-scoped areas:

- Update related spec files directly in the same PR when needed.
- For new feature design, confirm a Requirements document before creating its same-basename ADR or Design.
- When a large feature is split into stacked phases, run spec review once in a separate phase right before QA.
- For hard-to-reverse design decisions, record the accepted decision, rejected options, and risks in an ADR or appropriate design/spec document.

Detailed documentation rules: `docs/azents/AGENTS.md`.

## Agent Teams Guidelines

Consider using an agent team for complex work, especially when changes span three or more independent modules, multiple apps, or require security/performance/test review.

File ownership guidance:

- Backend modules under `python/apps/azents/src/azents/` can be split by domain (`core`, `repos`, `services`, `api`, `engine`, `worker`).
- Runtime providers should be assigned separately from backend domain work.
- TypeScript app work should be assigned separately from backend work.
- Shared libraries such as `python/libs/az-common/` should be coordinated by the lead.

Operational rules:

- The lead coordinates and integrates; independent implementation can be delegated.
- Avoid assigning the same files to multiple teammates.
- Run quality checks after integration.
