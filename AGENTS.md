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

## Editing Strategy

### Replace Incorrect Units Instead of Patching Them

When an existing unit's responsibilities, control flow, or state model no longer match
the intended behavior, replace that function, class, module, or similarly narrow
surface instead of preserving the wrong structure with flags, branches, adapters, or
incremental special cases.

- Prefer a complete replacement when the expected behavior and acceptance checks are
  clear enough to verify.
- Preserve surrounding public contracts, call sites, migrations, and compatibility
  boundaries unless the task explicitly changes them.
- Do not minimize a diff by modifying a misunderstood implementation whose shape is
  itself the defect.

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
$ uv run pytest
```

Run the configured type checker for the subproject:

```console
$ uv run ty check --error-on-warning
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

- **Requirements** (`docs/azents/requirements/`) — confirmed user or system outcomes and acceptance criteria for one development snapshot. Implemented Requirements are immutable.
- **SPEC.md** (`docs/azents/spec/`) — current system behavior. Update when code changes.
- **ADR** (`docs/azents/adr/`) — append-only decision history. Implemented/adopted ADRs are immutable.
- **Design** (`docs/azents/design/`) — development-time design documents. Do not rewrite implemented design documents as living specs; current behavior belongs in spec docs.

The [branding-260823 historical document migration](docs/azents/adr/branding-260823-historical-document-migration.md)
authorizes one completed brand-only rewrite of historical snapshots and canonical
document identifiers. This exception does not make implemented snapshots generally
mutable; the normal immutability rules apply after that migration.

Development snapshots use one shared `{word}-{YYMMDD}-{slug}.md` basename across Requirements, ADR, and Design. Use `{word}-{YYMMDD}` as the snapshot ID and typed references such as `<snapshot>/REQ-N`, `<snapshot>/ADR-DN`, and `<snapshot>/DESIGN`. Legacy numbered ADRs and pre-migration Design filenames are historical inputs only; current core documents must use dated snapshot filenames. Preserve legacy references only in explicit provenance or ambiguity records.

Always read `docs/azents/spec/` first for current behavior. Read Requirements, ADRs, and design documents only when product intent, rationale, or historical context is needed.

When modifying azents-scoped areas:

- Update related spec files directly in the same PR when needed.
- For new technical feature design, confirm a Requirements document before creating its same-basename ADR or Design.
- When a large feature is split into stacked phases, run spec review once in a separate phase right before QA.
- For material architecture or product-contract decisions, record the accepted
  decision, rejected options, and risks in the development snapshot ADR.

Detailed documentation rules: `docs/azents/AGENTS.md`.

## Subagent Use

Subagent use is discouraged. The primary agent performs the work directly by
default. Only consider subagents for the following exceptions. Even when an
exception applies, reconsider whether the primary agent can solve the task directly.

- **Independent opinions:** A separate persona, such as an independent reviewer,
  provides read-only, one-way opinions rather than collaborating on the work.
  The primary agent evaluates the opinions and makes any changes directly.
- **Fully self-contained tasks:** The task can be completed from design through
  final output without parent conversation or feedback-driven follow-up changes,
  and is clearly faster than direct primary execution, including coordination and
  handoff costs. Tasks that leave the parent waiting for the result do not qualify.

The primary agent owns integration and runs integrated quality checks directly.
