---
title: "Run Resume Phase 4 — Infrastructure + Monitoring"
tags: [infra]
created: 2026-03-26
updated: 2026-03-26
implemented: 2026-03-26
---

# Run Resume Phase 4: Infrastructure + Monitoring

## Changes

### 1. `terminationGracePeriodSeconds: 60`

**File**: `infra/argocd/nointern-server/base/worker-deployment.yaml`

Change from K8s default 30 seconds to 60 seconds. This gives 30 seconds engine timeout after SIGTERM plus 30 seconds cleanup margin.

Spot instance reclamation provides 2-minute warning, so 60 seconds is enough.

### 2. Worker PodDisruptionBudget

**File**: `infra/argocd/nointern-server/base/worker-pdb.yaml` (new)

Set `maxUnavailable: 25%`. During deploy, terminate sequentially to minimize concurrent multiple interruptions.

Existing apiserver, admin, and mcp-egress-proxy had PDB, but worker did not.

### 3. Logs

Logs already added in Phase 1-3:
- `"Resuming interrupted run with pending function calls"` (engine.py)
- `"Shutdown detected during engine run, applying timeout"` (worker/engine.py)
- `"Engine task timed out after shutdown, canceling"` (worker/engine.py)
- `"Re-enqueued session for resume after shutdown"` (worker/engine.py)

### 4. Metrics (follow-up)

Since nointern currently has no Prometheus metrics infrastructure (ServiceMonitor, PrometheusRule not configured), add metrics after monitoring infrastructure is set up. Metrics defined in design document (`engine_run_resumed_total`, `engine_run_llm_canceled_total`, `engine_run_tool_canceled_total`) will be added after infrastructure is ready.
