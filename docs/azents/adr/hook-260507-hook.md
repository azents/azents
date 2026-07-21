---
title: "Runtime Hook System Historical Decision Reconstruction"
created: 2026-05-07
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: hook-260507
historical_reconstruction: true
migration_source: "docs/azents/design/runtime-hook-system.md"
---

# Runtime Hook System Historical Decision Reconstruction

- Snapshot: `hook-260507`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/runtime-hook-system.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### hook-260507/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Ordering/Failure Policy

- Provider order per lifecycle uses provider snapshot available at dispatch point as source of truth.
- `on_session_*`, `on_run_*` follow resolved `RunRequest.toolkits` order because these lifecycles may be called before turn `update_context()` executes.
- `on_sandbox_*` can happen from idle timeout, hibernate, and restore paths outside run request, so it does not require `RunRequest.toolkits`. Sandbox lifecycle dispatcher resolves current provider snapshot using sandbox `agent_runtime_id` / `session_id`. Provider resolve failure does not block hibernate/restore; it is traced and skipped.
- `on_turn_*` and `on_*tool_call` follow active provider set/order determined by that turn's `update_context()` result. Providers excluded because of `ToolkitStatus.DISABLED` or `update_context()` failure do not receive that turn/tool lifecycle hook.
- Runner does not manage provider-local hook order. Since one lifecycle key has at most one callback per provider, internal composition is provider responsibility.
- before tool hook short-circuits on first deny.
- after tool hook executes as pipeline in active provider order.
- observation-only lifecycle calls providers in order, but default is fail-open: a provider exception does not stop other providers or original operation.
- `asyncio.CancelledError` and runtime cancellation signals are propagated, not fail-opened.
- Started run and started turn must each dispatch exactly one end hook inside single-process execution scope. Implementation should use scope guard or try/finally.
- End with unknown reason is recorded as `unknown` and warning is logged.

### Explicit source section: CI execution policy

- Core fake-provider E2E is candidate for required CI.
- If sandbox hibernate/restore is sensitive to infra cost or readiness, split into testenv-gated job.
- Optional/live provider tests should skip when credentials are absent and must not become required behavior gate.

### Explicit source section: Optional/live test skip/fail criteria

- Missing credential or external service prerequisite is skip.
- Failure in core fake-provider lifecycle behavior is fail.
- Raw args/output/prompt/credential remaining in trace is fail.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
