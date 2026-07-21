---
title: "Phase 3 — Agent Home Snapshot Hibernation Discussion"
created: 2026-04-18
tags: [backend, engine, infra, architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: phase3-260418
historical_reconstruction: true
migration_source: "docs/azents/adr/0021-phase3-snapshot-hibernation.md"
---

<!-- Design document, implemented: phase3-snapshot-hibernation.md -->

# phase3-260418/ADR: Phase 3 — Agent Home Snapshot Hibernation

> 📌 **Related design document** (implemented): [phase3-snapshot-hibernation.md](../design/phase3-snapshot-hibernation.md)
>
> This document records design-stage discussion. See the linked document for the final design and implementation.

## Overview

Phase 1 (#2609) completed DB-based activity tracking and lifecycle hooks. Phase 2 (#2627) completed the deadline-driven lifecycle loop and lease token. Phase 3 replaces the current "idle for 30 minutes → delete" behavior with **"idle → hibernate → resume."**

When an agent becomes idle during long-running work such as code analysis, builds, or tests, this phase preserves the **ephemeral layer** state—installed packages, shell history, filesystem changes, and similar state—as a snapshot, then restores it within a few seconds when the user returns.

Prerequisites: #2608 (research), #2609 (Phase 1), #2627 (Phase 2), #2661 (Phase 3 discussion), Discussion #2664.

## Background and Problem

### Current State After Phase 2

```text
No user message for 30 minutes
  → AgentHomeSandboxManager._evaluate_lifecycle() determines deadline
  → BEFORE_STOP hook → client.delete_agent(agent_id)
  → container / Pod fully deleted
  → only files remain in EFS (/data/user, /data/agent)
```

### Cost of Deletion

| Lost State | Restore Difficulty |
|---|---|
| Container itself | 5-15 seconds depending on image pull cache |
| Packages being installed, such as pip/npm/apt | Permanent loss; user must rerun manually |
| Shell history, cwd, environment settings | Permanent loss |
| Changes under `/usr/local/...`, `/etc/...` | Permanent loss |
| JIT / page cache | Recompile |

**Result**: returning after 30 minutes idle is equivalent to starting from scratch. Phase 3 fills this UX gap with snapshot hibernation.

---

## Discussion Points and Decisions

### D1. Snapshot type: Filesystem / CRIU / microVM

**Background**: Snapshot technologies fall into three levels by what they preserve.

- **A. Filesystem-only** (`docker commit`, CSI VolumeSnapshot) — rootfs only.
- **B. Process checkpoint (CRIU)** — process state + filesystem, Kubernetes 1.25+ alpha.
- **C. VM snapshot (Firecracker)** — entire VM state.

**Options**: A / B / C

**Decision: A — filesystem-only.** CRIU is outside Phase 3 and becomes a separate research track.

**Rationale**:

- NoIntern uses container isolation with bwrap inside the container; C requires replacing the entire isolation model.
- AL2023 EKS defaults to cgroupv2, while CRIU needs cgroupv1 plus specific runc settings. This would require a custom AMI and has high restore failure/debugging risk.
- Filesystem-only delivers about 80% of the value: installed packages, `/usr/local`, `/etc` changes, and shell history.
- When process state is needed, tmux/screen wrappers or agent init scripts can cover it.

### D2. Snapshot backend: `ctr commit` / CSI / hybrid

**Background**: Once filesystem-only is chosen, the next decision is where and how to store it.

**Options**:

- **A**. Docker commit + Container Registry (ECR)
- **B**. Kubernetes CSI VolumeSnapshot (EBS-based)
- **C**. Hybrid — fixed base image + `/data/agent` volume snapshot
- **D**. Privileged DaemonSet + `ctr commit` (containerd-native)
- **E**. In-container tar + path exclusions, non-privileged

**Decision: D + A hybrid** — Kubernetes production uses privileged DaemonSet + `ctr -n k8s.io containers commit`; local Docker uses `docker commit`. Both produce OCI images in ECR.

**Rationale**:

- Docker and Kubernetes environments share the **same semantics**, image-layer pull, so `AgentHomeClient` implementations remain symmetric.
- ECR already exists, so no new infrastructure is needed, only IAM extension.
- CSI creates AWS lock-in, differs from local Docker, and EFS is mounted in a way that cannot separate volumes per agent.
- In-container tar is non-privileged but duplicates base image contents, causing 2-3x size and roughly 3x ECR cost.
- Privileged DaemonSet security risk can be reduced from medium to low with three core defenses: NetworkPolicy, HMAC, and narrow API; see D8.

### D3. Whether to include CRIU

**Background**: Vercel Open Agents uses Firecracker microVM + native snapshots to fully restore process state. For NoIntern to provide equivalent UX, CRIU is the only option.

**Options**:

- **A**. Include in Phase 3 — CRIU + filesystem hybrid.
- **B**. Phase 3 is filesystem-only, CRIU moves to Phase 4+.
- **C**. CRIU only.

**Decision: B — outside Phase 3.** CRIU becomes a separate research track.

**Rationale**:

- Kubernetes checkpoint is 1.25+ alpha and requires AMI changes plus feature gate management for production.
- Restore failure rate is a concern. Processes depending on features such as inotify, D-Bus, or deleted file descriptors can fail to dump.
- Prioritize ROI. Filesystem-only covers 80% of cases; introduce CRIU gradually after stability is proven.
- Build the interface `AgentHomeClient.snapshot/restore` with filesystem first, so CRIU can be attached later without signature changes.

### D4. Snapshot storage cost

**Background**: Snapshot size and retained count per agent determine ECR cost. We need a budget limit before deriving retention policy.

**Options**:

- **A**. Latest 1 per agent.
- **B**. Latest 3, enabling rollback.
- **C**. Unlimited.

**Decision: A — latest 1 per agent** plus **2GB limit per snapshot**.

**Rationale**:

- Average snapshot diff size is expected around 200-500MB, with base layers shared.
- 1000 agents × 300MB × 1 = 300GB ECR Standard, about $30/month.
- Option B triples cost for low value; if restore fails, fallback to fresh is acceptable.
- 2GB cap prevents snapshot ballooning. If exceeded, hard fail and fallback to delete.

### D5. UX while restoring

**Background**: How should we show the 5-15 seconds of restore time?

**Options**:

- **A**. Transparent, no message; user just perceives a slow response.
- **B**. Explicit "restoring" message.
- **C**. Hybrid with a 5-second threshold.

**Decision: C — hybrid.** If restore finishes within 5 seconds, stay transparent. If it exceeds 5 seconds, send `SandboxRestoringEvent`.

**Rationale**:

- Average restore: ECR pull with cached base 2-5s + container start 1-2s ≈ 3-7s.
- Most cases finish within threshold, preserving quiet UX.
- Only slow cases show "restoring" noise, providing reassurance.
- Reuse existing `SandboxInitializingEvent` / `SandboxReadyEvent`; add only `SandboxRestoringEvent`.

### D6. Failure policy: silent fallback vs persistent contract

**Background**: What happens when snapshot creation fails during hibernate or restore fails when a user message arrives?

**Options**:

- **A**. Silent fallback — all failures fall back quietly to existing path, with metrics only for operators.
- **B**. Persistent contract — classify failures as transient/permanent, retry, and notify user.

**Decision: A — ephemeral contract, with soft notification on restore failure.** Treat snapshot as best-effort cache.

**Rationale**:

- User data under `/data/*` is stored separately in EFS, so losing a snapshot is not critical data loss.
- Classifying transient/permanent failures is ambiguous in many cases, such as healthcheck timeout or containerd error, and retry complexity increases.
- Agents should understand that snapshot is ephemeral; see D13. Users still receive soft transparency, such as "previous environment restore failed; starting fresh."
- Metric thresholds: snapshot failure rate >5%/h, restore failure rate >1%/h → Slack alert.

### D7. Retention

**Background**: How long should snapshots be kept for long-unused agents?

**Options**:

- **A**. 30 days
- **B**. 90 days
- **C**. Unlimited
- **D**. Short, 7 days

**Decision: A — 30 days, ECR lifecycle policy, and cascade delete.**

**Rationale**:

- Matches common SaaS retention practice.
- Aligns with predictable monthly cost: 30-day TTL + 1 per agent + average 300MB.
- Automate with ECR `countType=sinceImagePushed, countUnit=days, countNumber=30`.
- On Agent/workspace deletion, perform cascading delete through FK ON DELETE CASCADE plus explicit hook.

### D8. Security: sensitive data handling

**Background**: Snapshot is a full container filesystem image and may contain credentials, tokens, or cookies. The privileged DaemonSet also has security risk.

**Options**:

- **A**. Maximum defense: 8+ layers including credential scanning, audit, IAM, KMS, NetPol, HMAC, cosign, RBAC, sandbox escape protection.
- **B**. Three core defenses: NetworkPolicy / HMAC / narrow API, plus standard additions.
- **C**. Only default ECR encryption.

**Decision: B — three core defenses**, plus ECR KMS encryption and cosign signing.

**Rationale**:

- Initial risk assessment incorrectly included "sandbox escape → DaemonSet path." In reality, a successful sandbox escape already means node root, so the DaemonSet is irrelevant in that scenario.
- Actual threats:
  1. nointern-server RCE → DS misuse, though the DS grants limited authority.
  2. DS code/dependency CVE — mitigated by dependency scanning and narrow API surface.
  3. Supply chain risk in DS image — mitigated by cosign + ArgoCD verify.
  4. Token leak / NetworkPolicy mistake — mitigated by explicit NetworkPolicy allow-list.
- **Three core defenses**:
  1. **NetworkPolicy** — DS API is reachable only from `namespace=nointern, serviceAccount=nointern-server`.
  2. **HMAC request signing** — HMAC-SHA256 over body + timestamp with 60-second replay window.
  3. **Narrow API** — only `POST /snapshot` and `POST /delete-snapshot`. No arbitrary `ctr` command exposure. Image refs are generated server-side and regex-validated.
- Credential isolation: Agent containers should not contain credentials by policy, so snapshots are unlikely to contain credentials.

### D9. Multi-tenant isolation

**Background**: Can an agent in workspace B restore a snapshot from workspace A?

**Options**:

- **A**. DB single source — Manager always goes through `repo.find_latest_snapshot(agent_id)`.
- **B**. Separate ECR repository per workspace.
- **C**. Image-tag-level isolation only.

**Decision: A — DB single source + server-side tag generation.**

**Rationale**:

- External API never accepts `snap_ref` directly, blocking arbitrary snapshot injection.
- `agent_snapshots.agent_id` FK ON DELETE CASCADE automatically cleans metadata when the agent is deleted.
- Image tags are generated server-side as `<ecr>/agent-snapshots:<agent_id_hash>-<ts>` and regex-validated.
- Per-workspace ECR repositories add operational complexity for little benefit. Tag-level + DB isolation is enough.
- Only testenv-specific endpoints may accept arbitrary `snap_ref`, and they are guarded by feature flag.

### D10. Persistent layer: keep EFS vs move to S3-backed

**Background**: After agreeing on the 2-layer model—persistent `/data/*`, ephemeral container rootfs—the major decision is how to implement the persistent layer itself.

**Options**:

- **A**. Keep current model: single EFS backend.
- **B**. S3-backed `/data` with event-based sync, tar dump on hibernate and unpack on restore.
- **C**. S3-backed + write-through for strong durability.
- **D**. Hybrid: hot data on EFS, cold data on S3.
- **E**. Mountpoint for S3 (FUSE) to minimize code changes.

**Decision: Phase 3 = A — keep EFS; Phase 4 = move B, S3-backed, forward.**

**Rationale**:

- Independent from the original Phase 3 goal, container snapshot. Expanding scope would multiply schedule by 2-3x, from about 6 weeks to 3-4 months.
- Safer sequence: prove Phase 3 and stabilize operations, then take the bigger Phase 4 change.
- Option B's value, such as monthly cost from $150 to $12, local I/O, and clean ownership, remains available in Phase 4.
- If Phase 4 fails, Phase 3 remains independently useful.
- Phase 4 subtopics to revisit: sync policy, lock protocol (`data_owner` lease), File-API rewrite, and EFS → S3 migration path.

### D11. Snapshot timing

**Background**: We decided what/where/how/failure policy, but must decide **when** to snapshot. Idle hibernate alone loses up to 30 minutes of state if a Pod crashes while active.

**Options**:

- **A**. Only on hibernate.
- **B**. Hibernate + periodic safety snapshot every N hours.
- **C**. Explicit snapshot tool for user/agent.
- **D**. Event-triggered debounce on install/state-change.
- **E**. Hybrid A + C.

**Decision: A + D debounce with max-wait.** Periodic safety snapshots (B) and manual tool (C) move to Phase 4+.

**Concrete behavior**:

- **Idle hibernate**, existing Phase 2: 30 minutes idle → BEFORE_STOP → snapshot → `delete_agent`.
- **Debounced active snapshot**, new Phase 3:
  - First state-change event sets `snapshot_deadline_at = NOW + 10min`.
  - Events within the next 10 minutes are coalesced; deadline does not move.
  - At 10 minutes → snapshot while keeping container running → `snapshot_deadline_at = NULL`.
- **State-change events (4)**:
  - `POST /exec` — shell execute, regardless of path.
  - `PUT /files` — file write.
  - `PATCH /files` — file edit, `old_string → new_string`.
  - `DELETE /files` — file delete.

**Rationale**:

- Option A alone does not snapshot during continuous active work, such as every 5 minutes, until hibernate occurs. Long session state could be lost.
- Periodic option B is excessive relative to low crash probability during continuous sessions.
- Debounce with max-wait 10 minutes covers both "activity paused briefly" and "long-running active work needs a safety checkpoint."
- Trigger on all write paths without path distinction. The maintenance cost of complex conditional logic is greater than the benefit, and writes under EFS paths do not enter commit diff anyway.
- Communication channel: no separate broker/HTTP needed. Manager itself is the sandbox-daemon caller, so add `notify_state_change` hooks at call sites such as `AgentHomeSandbox.exec` and `.write_file`.

### D12. Termination handling: Spot / Eviction / Drain

**Background**: Snapshot is also needed when Pods terminate involuntarily due to spot interruption, eviction, or drain. Existing design only handled hibernate and debounce.

**Options**:

- **A**. Pod preStop hook calls Manager `/terminating` endpoint.
- **B**. Spot interruption watcher DaemonSet polling metadata.
- **C**. Hybrid A + B.
- **D**. Manager watches Pod terminating through K8s API.

**Decision: A — Pod preStop only in Phase 3. B is unnecessary because Karpenter already handles SQS-based interruptions.**

**Concrete behavior**:

- Add `preStop` hook and `terminationGracePeriodSeconds: 90` to Agent Home Pod spec.
- preStop calls a script inside sandbox-daemon, which sends HMAC-signed POST to Manager `/admin/v1/agent-home/terminating` endpoint.
- Manager runs the same path as hibernate: BEFORE_STOP → snapshot → delete_agent.

**Rationale**:

- Karpenter v1.9 + SQS interruptionQueue is already configured in the EKS cluster (`addons.tf:106`).
- When SQS receives interruption, Karpenter cordons node + evicts Pods → SIGTERM → preStop hook automatically runs.
- A Spot watcher DaemonSet would duplicate Karpenter.
- `karpenter.sh/do-not-disrupt` only blocks voluntary disruption; spot interruption is involuntary and still applies, so preStop is required.
- Time budget: 2-minute notice with preStop 1-2s + snapshot 5-15s ≈ 20s. `terminationGracePeriodSeconds: 90` is enough margin.
- Accepted unhandled cases: OOMKilled (SIGKILL skips preStop), node kernel panic. Reconsider periodic safety snapshot in Phase 4.

### D13. Agent awareness of snapshot limits

**Background**: Silent fallback protects the **operator** perspective. From the **agent** perspective, it may not know why its work disappeared. The agent should know in advance and adjust behavior.

**Options**:

- **A**. Static guidance only in system prompt.
- **B**. System prompt + dynamic feedback, injecting a system note on failure in the next turn.
- **C**. Everything: A + B + pre-flight warning at 1.5GB.

**Decision: B — system prompt + dynamic feedback.** Pre-flight warning (C) moves to Phase 4+.

**Rationale**:

- System prompt alone is only preventive. On failure, the agent still would not know why the sandbox started fresh.
- Dynamic feedback provides transparency, such as injecting a system note at the start of the next user turn: "previous hibernate snapshot failed, reason: 2.3GB > 2GB limit; cleanup recommended."
- Pre-flight warning needs ctr dry-run support plus du -sb cost evaluation; decide after POC in Phase 4+.

### D14. Demoting `/home/sandbox`

**Background**: In the 2-layer model, `/home/sandbox` was previously an EFS subPath but can be classified as ephemeral. Shell history, bashrc, and home sub-tools are cleaner if managed by snapshot.

**Options**:

- **A**. Include in Phase 3 — modify K8s manifest + path.py.
- **B**. Split into separate migration issue.

**Decision: B — separate migration issue.** Keep existing EFS subPath for `/home/sandbox` in Phase 3.

**Rationale**:

- Existing data migration strategy, whether bulk/lazy/dual-write, plus path.py, File-API, and system prompt updates make the scope broad.
- Phase 3's core value, container snapshot, is achievable without demoting `/home/sandbox`.
- A separate migration issue should review data transfer plan and operational risks independently.

### D15. Snapshot handling on base image upgrade

**Background**: A snapshot is a self-contained OCI image produced by `ctr commit`, with agent diff accumulated over the base image from creation time. When `nointern_agent_runtime_image` is deployed with a new version:

- Existing snapshot restore still works because old base layers remain in ECR and can be pulled.
- But fresh Pods use the new base, while snapshot restore Pods use the old base, causing **drift between agents**.
- Security patches or breaking APIs in the new base do not reach agents on the old base.

**Options**:

- **A**. Explicit invalidation: if snapshot `base_image_ref` differs from current config image ref, discard snapshot and fresh fallback.
- **B**. Silent drift + natural recovery: keep old base until next hibernate commits a new base.
- **C**. Opt-in invalidation flag: flush only when operator deploys with `--invalidate-snapshots`.

**Decision: A — explicit invalidation.** Backward compatibility support is split into follow-up issue #2684.

**Rationale**:

- Silent drift (B) can stretch security patch latency up to debounce × 30-day ECR TTL, which is serious.
- Opt-in (C) weakly protects against operator error; missing the deploy flag keeps the fleet vulnerable.
- A has UX cost, one cold start per org on rolling deploy, but improves security and consistency.
- `/data/*` remains, so there is no user data loss; only cold-start inconvenience remains.
- SemVer / compat_key mitigation can be considered in #2684 after observing production drift frequency metrics.

---

## Decision Summary Table

| # | Point | Decision |
|---|---|---|
| D1 | Snapshot type | Filesystem-only; exclude CRIU/microVM |
| D2 | Backend | Privileged DaemonSet + `ctr commit` / local `docker commit` → ECR OCI image |
| D3 | CRIU | Outside Phase 3; separate research track |
| D4 | Storage cost | Latest 1 per agent, 2GB cap, ECR about $30/month for 1000 agents |
| D5 | Restore UX | Hybrid 5-second threshold, `SandboxRestoringEvent` |
| D6 | Failure policy | Ephemeral contract — silent fallback + soft notification |
| D7 | Retention | ECR lifecycle 30 days + cascade delete |
| D8 | Security | Three core defenses: NetworkPolicy / HMAC / narrow API, plus KMS + cosign |
| D9 | Multi-tenant | DB single source + server-side tag generation |
| D10 | Persistent layer | Phase 3 keeps EFS; Phase 4 moves S3-backed work forward |
| D11 | Timing | Idle hibernate + debounce with 10-minute max-wait on four write events |
| D12 | Termination | Pod preStop + `terminationGracePeriodSeconds: 90`; no spot watcher needed |
| D13 | Agent awareness | System prompt + dynamic feedback; pre-flight is Phase 4+ |
| D14 | `/home/sandbox` demotion | Separate migration issue, outside Phase 3 |
| D15 | Snapshot handling on base image upgrade | Explicit invalidation: base_image_ref mismatch → fresh fallback; compatibility support in follow-up #2684 |

## Migration provenance

- Historical source filename: `0021-phase3-snapshot-hibernation.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
