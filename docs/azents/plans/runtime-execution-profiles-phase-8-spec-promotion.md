---
title: "Runtime Execution Profiles Phase 8 Spec Promotion Execution Plan"
created: 2026-07-26
tags: [runtime, execution-policy, specification, documentation, validation]
---

# Phase Execution Plan

- Phase: `8 — living spec promotion`
- Branch/base: `feature/runtime-execution-profiles-10-spec-promotion` → `feature/runtime-execution-profiles-09-validation`
- PR boundary: Update current living Runtime Provider, Agent, Workspace, Runtime Control, Runtime persistence, and E2E strategy specifications to describe the implemented Runtime Execution Profile behavior. Record the Phase 7 evidence boundary without claiming unavailable Docker/Kubernetes execution as passing.
- Inputs: `runtime-260726/REQ`, `runtime-260726/ADR`, `runtime-260726/DESIGN`, implementation and Phase 1–7 plans, and the Phase 7 validation report.

## Deliverables

- Current-spec updates for:
  - `docs/azents/spec/domain/runtime-provider.md`
  - `docs/azents/spec/domain/agent.md`
  - `docs/azents/spec/domain/workspace.md`
  - `docs/azents/spec/flow/agent-runtime-control.md`
  - `docs/azents/spec/flow/agent-runtime-persistence.md`
  - `docs/azents/spec/flow/test-strategy-e2e-primary.md`
- Accurate `code_paths`, `last_verified_at`, and changelog/spec-version updates for each changed living spec.
- A concise spec-impact record from comparison of the complete stack diff with the existing living specs.

## Required behavior to promote

- Platform → Workspace → Agent policy is restrictive-only. Named Profiles, typed Provider-neutral modules, expected-version writes, governing-layer explanations, safe metadata-only audit, and bounded availability reasons are current product behavior.
- Saving Agent intent is distinct from Apply. Restrictive Platform/Workspace changes auto-converge; Agent Profile/override changes require explicit Apply. Automatic convergence preserves Agent Workspace data and only reset may delete it.
- Provider capability is authoritative and fail-closed. Current server capability remains `privileged_engine=false`; image build, container run, Compose, persistent engine storage, and qualified Kubernetes containment must remain unavailable/unadvertised until the Provider contract and qualified evidence support them.
- Kubernetes Runtime implementation owns fixed Provider topology and separate engine storage. Runner/gateway/nested workloads do not receive Provider credentials, Kubernetes ServiceAccount credentials, host sockets, or generic privileged controls. Persistent nested-engine storage remains unavailable unless specifically qualified.
- Status/UI projections are server-authoritative and expose configured, pending, applied, unavailable, and divergent states with bounded required action. They omit credentials, tokens, socket paths, raw manifests, and Provider topology.
- E2E uses Admin/Public API state setup without direct product DB writes. Docker-backed and qualified Kubernetes coverage use strict prerequisite handling; absent prerequisites are unavailable evidence, not a passing enablement claim.

## Non-goals and sequencing guard

- Do not change runtime behavior, Provider capability, APIs, generated clients, migrations, or infrastructure.
- Do not rewrite accepted ADR decisions or use Requirements/Design documents as living specs.
- Do not set `implemented` on the Requirements or Design in this PR. Those immutable snapshot status updates require complete-stack CI evidence after PR 11 exists, as directed by the delivery sequence.
- Do not hide the absence of qualified Kubernetes evidence or make a live test permissively skip an advertised-but-unenforced capability.

## Ownership and review

| Workstream | Owner | Owned paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Spec impact and promotion | `/root` | Candidate living specs listed above; this phase plan | Current behavior documentation and scoped changelog updates | `/spec-review`, docs validation, diff scope check |
| Independent review | `/root/runtime-execution-reviewer` | Read-only complete Phase 8 diff | Requirements/Design/spec alignment and security-boundary review | Blocker/P1/P2 batch only |

## Integration order

1. Compare `origin/main..HEAD` implementation paths to every living spec `code_paths` entry and inspect current spec text.
2. Update the Runtime Provider spec with typed capability/compatibility, fail-closed selection, Kubernetes authority/storage/isolation boundary, and safe management projection behavior.
3. Update Agent and Workspace specs with Profile selection, restrictive override/allowance, explicit Apply, automatic convergence, explanation/audit, and server-authoritative UI behavior.
4. Update Runtime Control and persistence specs with immutable target snapshots, generation/evidence fencing, fixed topology, separate engine storage, reset-only deletion, and unavailable capability boundaries.
5. Update E2E strategy with API-managed policy fixtures, safe evidence redaction, Docker/runtime-provider lane requirements, and qualified Kubernetes skip/fail rules.
6. Run `/spec-review` against the staged diff; validate docs/index/frontmatter; request independent review; repair only high-risk required findings.

## Final validation and scope-drift check

- Run `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check` or the project pre-commit equivalent, docs snapshot validation, `git diff --check`, and pre-commit on commit.
- Inspect all changed spec prose against code and Phase 7 evidence. Every statement about enabled enforcement must be backed by qualified evidence; otherwise express the capability as unavailable/unadvertised.
- Reject feature behavior changes, generated client changes, Requirements/ADR mutation, Design `implemented` updates, direct CI monitoring, unscoped unrelated spec refreshes, generic Kubernetes administration advice, and raw credential/topology disclosure.
