---
title: "Adopt testenv QA Fixture-First Architecture"
created: 2026-05-12
tags: [testenv, qa, architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: testenv-260512
historical_reconstruction: true
migration_source: "docs/azents/adr/0029-testenv-qa-fixtures.md"
---

# testenv-260512/ADR: Adopt testenv QA Fixture-First Architecture

## Context

nointern `testenv/nointern/` is designed around `run-tc`, setup DAG, run-scoped state, and fresh-context verifier. This improved TC execution reliability, but recent QA showed that QA environment preparation cost and uncertainty are now larger problems than product runtime defects.

Representative symptoms:

- The agent re-evaluates environment readiness for user/workspace/agent/devserver/sandbox on every QA run.
- The verifier default depends on `claude -p`, so organization policy or subscription state can block QA itself.
- Narrow feature probes are tied to broad chat baseline, LLM, shell pipeline, and nested `run-tc`, obscuring the real failure cause.
- devserver state has no worktree fingerprint, so a run can attach to a devserver from another worktree.
- Existing setup state is tied to `runs/<run-id>/state.json`, making it unsuitable as the source of truth for long-lived QA environments.

The core goal of this decision is not preserving existing TCs. It is to **accurately set up and verify reusable fixture environments so agents do not waste time and tokens setting up and interpreting the QA environment every time**.

## Decision

Introduce a first-class QA fixture subsystem in `testenv/nointern`.

- Fixtures are the source of truth for long-lived, reusable QA environments.
- Fixture state is stored as logical manifests in `testenv/nointern/.state/fixtures/<fixture-id>.json`.
- Fixture manifests do not store raw secrets. They store only resource ids, paths, URLs, fingerprints, status, and doctor results.
- Provide `fixture up`, `fixture doctor`, and `fixture reset` as first-class commands independent from TC execution.
- `qa run` validates a prepared fixture through fixture doctor, then runs only deterministic probes. It does not use the default LLM verifier or legacy bash fallback.
- The existing setup DAG remains as the substrate for run-local seed work, but responsibility for long-lived QA environment preparation moves to fixtures.
- Preserving existing TCs is not a goal. Necessary TCs should move to probes or E2E, and new QA only allows fixture-based declarations.

## Consequences

### Positive

- At QA start, the agent can quickly determine current environment state by reading fixture manifest and doctor results.
- Environment failures and feature probe failures are separated, shortening the debugging path.
- A deterministic QA path can be created without depending on `claude -p` verifier, broad chat baseline, or shell pipeline.
- devserver worktree mismatch can be blocked before probe execution.
- Existing setup handler/client code that creates resources through API/seed paths can be reused in fixture resource implementations.

### Negative

- State duplication can occur if responsibility boundaries are not kept clear among `runs/<run-id>/state.json`, `.state/devserver.state.json`, and `.state/fixtures/*.json`.
- If fixture reset semantics become too broad, DB reset, tmux restart, and external session cleanup can become mixed.
- If fingerprints are too sensitive, fixtures will be marked stale every time and reuse goals will be undermined.
- If too much compatibility layer is built to preserve existing TCs, the core goal becomes unclear.

## Alternatives

### Extend existing setup DAG as fixtures

Extending existing `run-setup` and `runs/<run-id>/state.json` would be a smaller change. However, run-scoped state and TC prerequisite semantics do not match the requirements of long-lived QA environment manifests. State mismatch after DB reset is also not solved naturally.

### Integrate with pytest E2E fixtures

Integrating with pytest fixtures in `python/apps/nointern-e2e` would use a familiar testing ecosystem. However, nointern testenv handles agent-as-runner, Slack/browser/devserver/live integration QA, which has a different purpose from containerized API E2E. Clear separation is better than integration.

### Gradual improvement focused on preserving existing TCs

We could preserve existing TCs as much as possible while fixing verifier defaults, shell fallback, and linter. But the core problem is not the TC execution model; it is the repeated cost of setting up and interpreting the environment. Prioritizing TC preservation would delay fixture correctness and reusability design.

## Migration provenance

- Historical source filename: `0029-testenv-qa-fixtures.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
