---
title: "Runtime System Metrics Overview"
created: 2026-08-24
tags: [runtime, metrics, observability, provider, runner, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260824
---

# Runtime System Metrics Overview

- Snapshot: `runtime-260824`
- Document reference: `runtime-260824/ADR`
- Requirements: [Runtime System Metrics Overview Requirements](../requirements/runtime-260824-system-metrics-overview.md) (`runtime-260824/REQ`)

## Decision Map

- [x] `runtime-260824/ADR-D1` — Use the Runner as the only system-metrics reporter.
- [x] `runtime-260824/ADR-D2` — Add an optional Runner metrics capability and dedicated message without a protocol-version bump.
- [x] `runtime-260824/ADR-D3` — Use normalized usage values with optional totals and per-metric availability.
- [x] `runtime-260824/ADR-D4` — Use the current Runner connection generation as the metric epoch.
- [x] `runtime-260824/ADR-D5` — Store one bounded generation-scoped ring buffer in the Coordination Store.
- [x] `runtime-260824/ADR-D6` — Sample immediately and every 60 seconds, with a fixed three-minute stale threshold.
- [x] `runtime-260824/ADR-D7` — Expose one dedicated Agent-authorized read endpoint with visibility-scoped polling.

## Context

Azents currently exposes Agent Runtime lifecycle, configuration, Runner availability,
and Agent Workspace operations, but it has no user-facing system-resource overview.
Provider and Runner are independent authenticated Runtime Control clients with
separate connection generations. Their existing bidirectional gRPC protocols carry
registration, heartbeat, lifecycle or Runner state, operation, transfer, and error
messages, but no metrics payload.

The Runner can observe its local host, virtual machine, or container environment.
It cannot be assumed to observe or aggregate other Provider-owned containers in a
multi-container topology. The requester narrowed the confirmed Requirements to this
Runner-observable scope rather than introducing Provider metrics, Kubernetes Metrics
API access, a privileged collector, or sidecar aggregation.

The existing `RuntimeCoordinationStore` provides short-lived streams, operation
metadata, and generation-fenced current connections through Redis and in-memory
implementations. It has no bounded metric-series contract. Redis is optional, and
the in-memory implementation must therefore provide equivalent pruning and expiry
semantics for this informational history.

The current public Agent Runtime API already enforces Agent access and is consumed by
both the chat Runtime/Workspace panel and Agent Runtime settings. Those clients poll
Runtime state only during lifecycle transitions, so a continuously refreshed metrics
series needs an explicit read and refresh boundary rather than silently changing the
existing lifecycle polling contract.

## Fixed and Derived Outcomes

The confirmed Requirements and existing project constraints determine the following
outcomes and they are not reopened as ADR choices:

- Metrics are untrusted Runtime-originated observations and never grant lifecycle,
  Provider, Agent, Workspace, billing, scheduling, or destructive-operation
  authority.
- Only samples belonging to the current physical Runtime incarnation may be
  presented as current. An old authenticated connection cannot submit current
  samples after its generation is replaced or revoked.
- Collection uses one-minute intervals and the product returns no more than the most
  recent hour or 60 samples per metric.
- Missing intervals remain missing; the control plane does not synthesize or
  interpolate observations.
- Trend state is best-effort and volatile. Its loss cannot affect Runtime correctness,
  lifecycle state, Agent Workspace durability, or ordinary Runner operations.
- Redis remains optional and cannot be a correctness or availability dependency.
- Metrics visibility uses the existing Agent access boundary and exposes no
  hostname, filesystem path, process identity, or raw infrastructure identifier.
- Measurement scope is one of the bounded physical environment classes `host`,
  `vm`, or `container`; Agent Workspace usage is not the system disk metric.
- A Provider-managed Runtime reports only the environment visible to its Runner.
  Other Provider-owned containers and sidecars are outside this overview.
- A narrower node, Provider-host, or control-plane value is never substituted for
  the Runner's actual execution scope.
- Unsupported, unavailable, stale, stopped, and disconnected states remain explicit
  and independent per metric.

## Decisions

### runtime-260824/ADR-D1: Use the Runner as the only system-metrics reporter

**Affected requirements:** `runtime-260824/REQ-1`, `REQ-2`, `REQ-3`, `REQ-5`

Every supported Runtime topology uses its authenticated Runner connection as the
only system-metrics reporting plane. Runtime Providers do not collect, aggregate,
forward, or report Runtime system metrics. The snapshot introduces no Kubernetes
Metrics API dependency, Provider-side Docker stats path, privileged node collector,
or metrics sidecar.

The Runner reports the host, virtual machine, or container environment it can
actually observe. In a Provider-managed multi-container topology, usage from other
containers and sidecars is not aggregated into the overview. The report identifies
its actual bounded scope and marks a metric unsupported when it cannot determine a
meaningful value or denominator without claiming broader infrastructure authority.

This keeps one authenticated source, one collection implementation, and one
generation-fencing path for the initial product. A future requirement for complete
Pod or Provider-owned topology aggregation requires a new development snapshot
rather than extending this reporter silently.

**Rejected:** Selecting a reporter through each Provider capability contract would
preserve broader topology aggregation but require Provider-specific collection,
capability, authorization, failure, and test paths. Making every managed Provider
the reporter would duplicate local collection for single-container Runtimes and
still not guarantee a meaningful aggregate disk-capacity metric.

### runtime-260824/ADR-D2: Add an optional Runner capability and dedicated message

**Affected requirements:** `runtime-260824/REQ-1`, `REQ-2`, `REQ-5`

Runner registration advertises the additive `runtime.system-metrics.v1`
capability. A capable Runner publishes a dedicated system-metrics message on its
existing authenticated bidirectional Control stream. Metrics are not embedded in
heartbeat or Runner lifecycle state reports, so their one-minute cadence and
failure behavior remain independent from the connection heartbeat and durable
Runtime state projections.

The existing Runner protocol version remains unchanged. A current Runner without
the capability may continue to register and perform ordinary operations, while the
metrics overview reports the feature as unsupported. Runtime Control accepts a
metrics message only from a current Runner generation that advertised the
capability. Provider protocol versions and capabilities are unchanged.

This additive rollout permits Control and Runner deployment order to vary without
making system metrics a prerequisite for Runtime availability. It does not retain
an alternate legacy metrics format: there is one metrics capability and one
message contract.

**Rejected:** Requiring a new Runner protocol version would force synchronized
replacement of every active Runner even though metrics are informational.
Piggybacking metrics on the heartbeat would couple a ten-second connection
liveness mechanism to the independent one-minute sampling contract and make an
absent sample ambiguous.

### runtime-260824/ADR-D3: Use normalized usage values with optional totals

**Affected requirements:** `runtime-260824/REQ-1`, `REQ-2`, `REQ-3`, `REQ-5`

One Runner report contains one sample time, one execution scope, and independent
CPU, memory, and disk observations. Scope is the closed set `host`, `vm`, or
`container`. Each metric observation has one of `available`, `unavailable`, or
`unsupported`.

An available CPU observation carries average used millicores for the fixed
one-minute interval and may carry total millicores when the Runner can identify a
meaningful capacity or limit. Available memory and disk observations carry used
bytes and may carry total bytes. Values are non-negative, and a supplied total must
be positive. The report does not carry a percentage; the public read model computes
one only when the matching total exists.

`Unavailable` means the Runner supports the metric for its environment but could
not read the current sample. `Unsupported` means it cannot provide that metric
meaningfully in the current environment. Fresh, stale, stopped, and disconnected
are server-derived presentation states and are not asserted by the untrusted
Runner. A partially available report remains a valid sample and preserves each
metric independently.

**Rejected:** Percentage-only reports conceal the denominator and cannot present a
useful absolute value when capacity is unknown. Raw OS, procfs, cgroup, or
filesystem counters would move platform-specific interpretation into Runtime
Control and create multiple wire contracts instead of one normalized sample.

### runtime-260824/ADR-D4: Use the current Runner connection generation as the metric epoch

**Affected requirements:** `runtime-260824/REQ-2`, `REQ-3`, `REQ-5`

Runtime Control accepts a metrics report only when the authenticated Runner
connection is the current generation for the Runtime and its registration
advertised `runtime.system-metrics.v1`. Each report carries a monotonically
increasing sample sequence within that connection generation. A duplicate or lower
sequence is ignored and cannot replace a later accepted sample.

The Control server assigns the canonical measurement timestamp when it accepts the
report. Runner wall-clock time is not an ordering or freshness authority. Stored
series are partitioned by Runtime ID and Runner connection generation. A
reconnected or replaced Runner receives a new generation and begins a new series;
samples from the prior generation may remain until volatile expiry but are never
selected as current for the new generation.

This intentionally gives up trend continuity across Runner reconnection. Recent
history is best-effort, while excluding an old physical or connection incarnation
from current data is mandatory. A disconnected Runtime may present the bounded
series for its last known Runner generation together with a disconnected current
state.

**Rejected:** A separate durable Runtime-incarnation identifier would preserve
history across benign reconnects but require another lifecycle identity and
cross-check. Trusting Runner timestamps would require clock-skew bounds and would
let an untrusted reporter influence ordering and freshness.

### runtime-260824/ADR-D5: Store a bounded ring buffer in the Coordination Store

**Affected requirements:** `runtime-260824/REQ-2`, `REQ-5`

The existing `RuntimeCoordinationStore` gains a system-metrics series contract
keyed by Runtime ID and Runner generation. One series contains at most 60 accepted
samples. Appending a sample removes excess entries, refreshes volatile expiry, and
preserves the highest accepted sequence. Reading a series excludes samples whose
server-assigned measurement time is older than one hour.

The Redis and in-memory stores implement the same bounded append, sequence, pruning,
and expiry behavior. In-memory expiry is explicit and does not inherit the current
operation-metadata behavior that ignores TTL. The last retained sample is the
latest sample; there is no separate latest-value store or second source of truth.

The series expires one hour after its last accepted sample. Coordination Store
loss, Control restart in in-memory mode, or ordinary expiry may clear the complete
trend. PostgreSQL, migrations, backup, restore, and long-term cleanup are not part
of the feature.

**Rejected:** A Runtime Control process-local cache would not be shared across
replicas and would make API results depend on request routing. PostgreSQL would
create durable time-series lifecycle and migration obligations that contradict the
best-effort one-hour overview.

### runtime-260824/ADR-D6: Use a fixed sampling and freshness policy

**Affected requirements:** `runtime-260824/REQ-1`, `REQ-2`, `REQ-5`

A capable Runner attempts one sample immediately after its registration is
accepted and then once every 60 seconds. A failed local metric read is represented
in that scheduled report as `unavailable`; the Runner does not create an
independent retry loop or catch-up burst between regular intervals.

An available metric is fresh while its latest accepted sample is no more than
three minutes old. After three minutes without a newer accepted observation, its
current presentation is `stale` and the old value is not presented as current.
The retained sample remains in the recent trend until normal one-hour pruning.
Capability absence or an explicitly unsupported observation presents
`unsupported`.

Runtime lifecycle overlays have precedence over metric freshness. A stopped Runtime
presents `stopped`, and a Runtime whose last known Runner connection is unavailable
presents `disconnected`; either state may retain the bounded trend. A newly
accepted Runner generation starts with `unavailable` until its first sample arrives.
Missing scheduled reports create gaps and are never synthesized.

The 60-second interval and three-minute threshold are fixed product constants in
this snapshot. They are not environment variables, Profile fields, Provider
capabilities, or administrator settings.

**Rejected:** Deriving sampling or staleness from the heartbeat interval would
couple connection liveness to an informational product series. Configurable or
adaptive intervals would add operational settings, compatibility behavior, and
test combinations without a confirmed need.

### runtime-260824/ADR-D7: Use one dedicated read endpoint with visibility-scoped polling

**Affected requirements:** `runtime-260824/REQ-1`, `REQ-2`, `REQ-4`, `REQ-5`, `REQ-6`

The Public API exposes one Agent-scoped system-metrics read endpoint beside the
existing Agent Runtime routes. It uses the same Workspace membership and Agent
access rules as the Runtime read. Its response contains the server-derived current
state and the current or last-known Runner generation's retained series, bounded to
one hour and 60 samples. It exposes the bounded scope and normalized metric values
but no connection ID, generation, Provider identity, host identity, path, or raw
infrastructure identifier.

The chat Runtime/Workspace panel and Agent Runtime settings consume this same
contract and render the same reusable metrics overview component. The query polls
every 60 seconds only while the relevant panel is visible or the settings surface
is mounted. Opening the panel reads the already collected server-side series; the
browser does not create or retain an independent trend.

The feature adds no WebSocket event, Server-Sent Events stream, Admin API, Admin UI,
manual refresh interval, or second metrics contract. A metrics-read failure remains
isolated from the existing Agent Runtime lifecycle response.

**Rejected:** Embedding the complete metrics series in `AgentRuntimeResponse` would
attach an ephemeral 60-sample payload and Coordination Store failure boundary to
every lifecycle read, including callers that do not display metrics. A push stream
would add connection and subscription lifecycle for a one-minute informational
series.

## Consequences

- Provider implementations and deployment RBAC remain unchanged by metric
  collection.
- Kubernetes sidecar and complete-Pod usage are outside the overview.
- Direct and Provider-managed Runtimes share one collection and transport path.
- Existing Runners remain operational and present metrics as unsupported until
  they advertise the additive capability.
- Reports use one normalized unit contract and retain partial availability without
  invented percentages.
- Runner generation and server-assigned time provide the complete metric fencing
  boundary; reconnection starts a new best-effort series.
- One Coordination Store ring buffer is both the latest-value and recent-trend
  source, with equivalent Redis and in-memory behavior.
- Collection and freshness use fixed constants with no retry or configuration
  mode.
- One dedicated read contract serves both product entry points without changing the
  existing lifecycle response or adding a push channel.
