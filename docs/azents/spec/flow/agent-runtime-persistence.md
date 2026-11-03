---
title: "Runtime persistence"
created: 2026-05-25
tags: [backend, engine, infra]
---

# Runtime persistence

Provider-owned Workspace durability, environment settings, Projects and automatic-start boundaries.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Runtime Providers](../domain/runtime-provider.md)
- [Workspaces and membership](../domain/workspace.md)
- [Runtime control](agent-runtime-control.md)
- [Session Browser](session-browser.md)

## Overview

Managed Agent Workspace durability is owned by the Runtime Provider backend, not by the Azents
server process and not by S3 checkpoint/restore as an event path. An Agent may be Runtime-free and
have no logical Runtime row or Workspace. When managed compute exists, the current-generation
Runner reports the effective Agent Workspace absolute path as Runtime metadata. Server file APIs,
Projects, worktrees, and prompts consume that reported path without a fixed server-side fallback.
The Runner image includes Pixi and points its global environments, exposed
commands, manifest, and package cache under the existing persistent Runner
`HOME`.

## Session Browser native state

The product Browser uses a native persistent context/profile for each concrete
Session and selected engine under the current Runner-reported Workspace. Tasks
within that Session/engine reuse site state; distinct Sessions or engines do not
share a browser context. Patchright retains its existing profile location and
Camoufox uses a separate engine-specific location without profile migration.
Switching engines retires live browser identities but keeps both profiles and
does not recreate the Runtime or stop unrelated shells/jobs. Existing
Runtime storage persistence owns the bytes, not a server checkpoint or profile
export/restore service.

Task/page/frame handles and resource incarnations belong to the live Runner
manager. Runner replacement invalidates those identities without promising
restoration of old tabs. Manager shutdown closes contexts without deleting native
profile bytes. Run completion, panel dismissal and attachment revocation do not
delete profiles or close unrelated tasks. Captures are intentional Session files;
volatile viewer frames are not durable recordings.

The [Session Browser flow](session-browser.md) defines current authority,
SDK/tool behavior, lifecycle and capture delivery.

## Per-Agent Runtime environment variables

Agent settings → Runtime exposes one environment-variable editor for managed Agents.
Session pages and chat Runtime panels do not expose this editor. Owners and exact
Agent administrators can replace the desired variable list; ordinary members can
read only names for visible public Agents. Private Agents hide the setting from
non-managers. Every write checks Workspace identity and active Agent lifecycle
under the exact Agent row lock.

The Agent stores a nullable Fernet-encrypted JSON mapping in
`encrypted_runtime_environment`. GET/PUT on the Agent Runtime environment API
return names, value-presence metadata and `can_manage`, never plaintext. Desired
entries use explicit `stored` references or `replace` secret values. Stored
references retain or rename an existing value without retrieving it; absent names
are deleted, and an empty desired list clears the encrypted document. Blank
existing UI inputs select retention rather than sending empty replacements.

Names are POSIX names of at most 64 bytes. The mapping allows at most 50 entries,
4096 UTF-8 bytes per value and 100 KiB total names/values. NUL values, duplicate
desired names, duplicate retained references and missing references are rejected.
Secret representations and request-validation errors are redacted.

Runtime Toolkit reads the current setting for the owning `_runtime_agent_id`
immediately before each command after credential capability admission. It preserves
existing peer Toolkit collection and merges the Agent setting last, making Agent
values authoritative on duplicate names while retaining unrelated Toolkit values.
Removing an Agent entry removes only that contribution; a same-name Toolkit value
can remain. Read/decryption failures fail command preparation rather than silently
using stale or empty settings. Prompts include names only.

The Browser confidential-input path retains that environment delegation. For
new Agent shell commands the Runner applies its process-owned
`AZENTS_BROWSER_INPUT_PUBLIC_KEY` after ordinary environment composition; that
reserved public metadata slot wins over a caller-provided entry of the same name.
No private key or plaintext credential is added to Runner-global environment,
Provider configuration or persisted Runtime metadata. Interactive Terminal keeps
its existing environment behavior.

The Agent imports the release Browser Skill encryption script from the current
Run's immutable VFS projection and executes it with Runtime-side dependencies.
The imported copy and dependency cache follow ordinary Runtime file/tool
persistence; the script is not installed as a Runner-package command. The
[Session Browser flow](session-browser.md) defines ciphertext delivery and
process-key loss behavior.

Saved changes affect new shell processes without Runtime restart. Existing
processes, Interactive Terminal, Runner environment, Provider configuration and
Runtime configuration digests are unchanged. Agent settings survive Runtime
stop/restart/reset, Profile changes and managed Runtime removal; Agent lifecycle
and capability fence subsequent use. Explicit environment deletion or Agent
deletion owns removal of this setting. General-purpose environment-variable
Toolkits are retired by the data cutover below; service-specific credential
Providers remain available.

## Workspace environment variables and Agent opt-in

Workspace settings → Environment variables provides a shared catalog. Workspace
Owners and Managers can replace the desired catalog, including deletion; members
receive only name/ID/value-presence metadata. Agent settings → Runtime separately
lists shared keys with checkboxes. Workspace Owners and exact Agent administrators
can replace an Agent's selected-ID set. Manager role alone cannot edit Agent
selection. Existing public/private Agent visibility rules remain in force.

The catalog stores immutable `workspace_environment_variables` identities with
Workspace/name uniqueness and encrypted values. Default-empty
`agent_workspace_environment_selections` rows record explicit opt-in; there is no
automatic inheritance or select-all default. New catalog entries do not acquire
selections. Value replacement retains identity; rename deletes the old identity
and creates a new one, cascading old selections. Deletion followed by same-name
creation never restores selections. Stale deleted/renamed references and foreign
Workspace IDs are rejected rather than looked up by name.

Catalog writes lock Workspace; selection writes lock Workspace then Agent and
revalidate all IDs and management authority in the same completed DB transaction.
Whole-list replacement uses ordinary last-accepted-writer settings semantics, not
versions or history. Each source independently keeps the existing variable
count/name/UTF-8/value limits, leaving Agent-only limits unchanged.

Runtime owner resolution reads selected same-Workspace rows and Agent-local values
in one SQL statement snapshot. Final composition is Toolkit → selected Workspace
→ Agent-local. Shared changes apply at the next command preparation without
restart; already-prepared/running process environments are not revoked. An Agent
override hides the shared value; removing it reveals the selected shared value.
Unselecting removes only the shared contribution, not Agent-local or Toolkit
configuration. The Agent selection UI annotates local override names and explains
future shared-value updates. Reads, writes and errors never return secret values.

Workspace v1 exposes GET/PUT `/workspaces/{handle}/environment` and GET/PUT
`/workspaces/{handle}/agents/{agent_id}/environment-selection`. Generated clients
and existing secret-safe validation routes own the wire boundary. The initial
catalog migration adds empty tables only; the subsequent Toolkit cutover below
preserves explicitly configured legacy access.
Session pages, Interactive Terminal, Runner global environment and Provider
configuration remain unchanged.

## Environment Toolkit data cutover

Online Alembic revision `409e9e3cb85a` requires drained API/Workers and the existing
application `AZ_CREDENTIAL_ENCRYPTION_KEY`. It decrypts each `envvar` Toolkit's
`values` document and filters it through `config.entries`; undeclared secrets are
not resurrected. Agent ownership, rather than attachment rows, determines local
destination. Workspace secrets create/reuse Workspace variable identities and
only previously attached Agents receive selections. Unattached shared entries
remain available in the catalog without selecting any Agent. No unrelated Agent
is opted in. Existing unrelated settings, selections, and Toolkits are retained.

Identical same-name values deduplicate; conflicting values within one destination
abort rather than overwrite. Agent-local values still override migrated shared
values. A move that would invert an existing selected Workspace override also
aborts. Nonempty disabled Toolkits abort because neither destination can retain
disabled Agent-local settings without activating them. Operators must resolve
these blockers explicitly before retrying; errors never disclose values.
Invalid encryption, malformed payloads, cross-Workspace relationships and
destination-limit violations likewise roll back the entire revision.

Success deletes only `toolkit_type = 'envvar'` configurations; attachment rows
cascade and namespace reservations remain consumed tombstones. A custom slug
does not change migration eligibility, and unrelated Toolkit types using the
slug `envvar` are not deleted. Alembic re-invocation at head is a no-op. Offline
SQL generation is unsupported for this data-dependent revision. Downgrade refuses
to invent deleted Toolkit identities/metadata and requires a pre-cutover backup.

## Runtime Profile binding and current configuration state

An Agent stores capability `none`, `managed`, or `removing` independently from one exact Workspace
Runtime Profile selection or no selection. Existing Agents were backfilled to `managed`; new Agents
default to `none` and do not create a logical Runtime. Explicit add from `none` requires an
available Profile and creates or rearms the logical row in stopped desired state.

An existing logical Runtime is observed without a row lock. Actual creation uses the
unique Agent identity and conditional INSERT to return one winner; ordinary getters
remain read-only and never create a Runtime. Descriptive snapshots do not authorize
later lifecycle, configuration or resource mutations.

Both logical Runtime ensure paths acquire the parent Agent's `FOR KEY SHARE`
before attempting the unique Runtime insert. This preserves the Agent foreign-key
and deletion-admission boundary while preventing a creator from occupying Runtime
uniqueness before waiting on another transaction's Agent admission lock. Existing
Runtime reads remain lock-free; this ordering does not add retries or relax Session
creation authority.

Interactive Terminal policy is independent durable configuration on infrastructure
Profile, Workspace Profile, and Agent rows. Each default-true flag contributes to a
server-computed effective policy and bounded denial scope, but none contributes to the
Runtime configuration digest, desired/applied slot, lifecycle generation, or Runtime
Toolkit authority. Terminal-only policy mutation therefore does not recreate or
reconcile physical compute. The obsolete per-Agent Shell policy column and API
contract do not exist; managed capability plus version is the sole Runtime Toolkit
gate.

Terminal tickets, attachments, sequence cursors, replay windows, PTY state, and
input/output bytes are volatile coordination state. They are not written to
PostgreSQL, object storage, Session events, Runtime configuration history, analytics,
raw logs, traces, or metric labels. Only content-free current/recent lifecycle
summaries and aggregate byte counts may be projected while the bounded volatile record
exists. Coordination loss ends the Terminal path without changing durable Runtime,
Session, Project, or Agent Workspace state.

Runtime Web persists one `runtime_web_services` row for each Agent and numeric local
port, current authentication configuration, browser-identity hashes, broker/ticket
hashes, and one current `runtime_web_session_routes` Owner lease per Runtime. The
service row owns its opaque ID, Workspace and Agent identity, 12-character hostname
key, label, selected duration, nullable exposure deadline, and monotonic revision.
Effective On state exists only while the deadline is in the future; no request,
approval, cycle, origin, or service-history row exists.

The route row contains only the exact Runtime and Runner generations, Owner replica
and boot identities, trusted Owner address, session lease identity and generation,
join-nonce hash, protocol fingerprint, lease timestamps, and bounded drain marker
needed to fence the persistent Runner Web session. Exact acquisition, renewal, and
release compare the complete epoch. The row is deleted when the Owner session ends;
no route history is retained.

Each stream route operation owns and closes its database transaction. SQL time and the
existing exact epoch/generation predicates govern acquisition, renewal, resolution,
nonce consumption, and draining. Exact-epoch release has no added expiry or draining
predicate. One-time nonce consumption remains committed if the subsequent local
offer-deadline check rejects registration; local cleanup cannot remove a replacement epoch.

Route resolution is an ordinary read-only observation: it checks retained Runtime
and Runner generations, protocol, lease expiry and drain state without locking the
route or Runtime. Actual acquisition, renewal, join consumption and drain/release
mutations retain their exact epoch fences. A lagged description does not authorize
a replacement ownership epoch or a consumed nonce.

Runtime Web stream counts, pending opens, buffer and bandwidth grants, fair-scheduler
state, logical-stream registries, tombstones, and live session state are ephemeral.
The Owner keeps authoritative process-local live state. The optional Redis capacity
backend stores only bounded aggregate operational state with a TTL and backend
epoch. Redis loss reconstructs equivalent capacity from the live registry and credit
accounting; recovery replaces stale keys instead of adopting them as active work.

Security configuration changes revoke existing browser identities and discard
pending broker bindings and tickets. Plaintext browser secrets are returned once and
never stored. Application HTTP, SSE, and WebSocket bytes, full paths and queries,
headers, cookies, upstream errors, WebSocket payloads, flow-control frames, and
application outcomes are never written to PostgreSQL, Redis, object storage, events,
Chat history, or Runtime configuration history. A transport or coordination loss
therefore ends only active work; it does not replay application requests or change
the stable service or its exposure deadline.

The legacy `runtime_web_endpoints`, `runtime_web_requests`, `runtime_web_cycles`,
`runtime_web_tunnel_routes`, `runtime_web_admission_leases`, and
`runtime_web_gateway_admission_leases` tables do not exist. Their Session ownership,
approval lifecycle, request-scoped route, and endpoint/user/Agent admission
semantics have no reader, compatibility view, alias, or fallback after the
forward-only clean-cutover migration. Gateway identities contain no browser-vendor
or browser-profile state. Ordinary Agent Runtime removal explicitly deletes every
service for that Agent before Runtime finalization; deleting and recreating a service
or Runtime produces a new ID and hostname key.

The logical Runtime persists durable Provider routing IDs and a monotonic
`configuration_sequence` high-water mark. A one-to-one `runtime_configuration_states` row exists
only while current configuration authority remains and contains one desired slot plus an optional
applied slot. Superseded desired or applied documents are not retained as product history, and
there is no configuration archive or Profile tombstone.

The Runtime Profile resolver reads the exact Agent selection, Workspace Profile, infrastructure
Profile, Provider, and current capability as lock-free versioned snapshots. An explicit
selection clear takes the Agent selection-version fence and atomically writes the managed
Runtime's next `unconfigured/runtime_profile_required` desired slot, clearing desired
Provider/Runner acknowledgement evidence while preserving any applied slot. A ready desired
document records their scalar IDs, versions, digests, Agent selection version, source trace,
resolved full configuration, target desired generation, canonical digest, and complete retained
Profile v1 or Profile v2 document. These source identifiers are snapshot evidence rather than
foreign keys to mutable Profile resources. The resolver does not consult a Provider preference,
Platform default, environment default, fallback, or live Provider connection state.

Historical schema-v2 `process_containment: null` serialization is normalized away before
canonicalization; a non-null value produces a blocked desired slot rather than becoming a direct
configuration. Other unavailable source or capability results are also durable blocked slots with
bounded reasons. No Profile selection produces `unconfigured/runtime_profile_required` without
selected-Profile authority or resolved configuration. Both blocked and unconfigured desired state
preserve any older applied slot while its running incarnation remains current.

Provider connectivity is operational evidence rather than configuration identity. Disconnect and
reconnect events do not change desired status, sequence, or digest. Current connection authority
gates lifecycle dispatch and operations that create or replace compute, but it does not fence an
already-ready current-generation Runner serving a retained applied configuration.

Resolution commits through a Runtime compare-and-set that verifies the expected sequence high-water,
desired generation, and every snapshot identity/version relationship. A materially new source,
desired generation, blocked result, or unconfigured target increments the high-water mark and
overwrites the desired slot at that positive sequence. Repeating an identical current target does
not allocate a sequence. A concurrent source change cannot attach stale state; the resolver retries
a stale write from a fresh snapshot once, and a durable Agent-selection reconcile task converges
any remaining conflict to the current authoritative selection.

The applied slot is separate physical evidence. It is overwritten only after the exact current
ready desired sequence, digest, and target generation are acknowledged by the bound Provider under
its current connection generation and by the authenticated current-generation Runner. Desired
changes therefore become visible immediately while the running incarnation may remain applied to
an older sequence or wait for explicit recreation. Returning to an earlier canonical document
still allocates a higher sequence, so old Provider or Runner evidence cannot become current again.

Provider and Runner report operations compose configuration evidence/promotion with
their existing state, path, connection, and failure writes in one database-only
transaction per report. A normal stale state compare-and-set can still commit evidence
written earlier in that operation; an exception or cancellation rolls back the entire
operation. Successful restart rearm uses its own later transaction rather than
collapsing into report persistence. Runner registration accepts current or retained-applied
evidence, and heartbeat reads expose only the existing eligible Provider-first pending
configuration before transport output.

There is no persisted process-containment lifecycle enum, boolean, status table, or qualification
record. Product status is derived from bounded desired/applied current state, exact
sequence/digest/generation evidence, current Provider/Runner authority, and current Runner-reported
Workspace evidence.

Capability/Profile changes never reassign the Agent to another Provider or Profile. Provider or
Profile loss preserves stored selection, Provider binding, applied state, running compute, and
existing storage while blocking new create/start/restart/reset/recreate work. A current-generation
ready Runner may continue ordinary data-plane operations from that retained applied state even when
the future desired slot becomes blocked or unconfigured. Historical hierarchy conversion occurs
only inside the one-way Alembic migration; runtime services do not read legacy policy tables,
snapshots, overrides, or status fallbacks.

An Owner-only exact-version Workspace Runtime Profile hard delete physically removes the Profile in
the same PostgreSQL transaction that clears a matching Workspace default and Agent selections,
advances their versions, supersedes Profile-targeted recreation, and writes affected managed
Runtimes' desired slot as higher-sequence `unconfigured/runtime_profile_required`. No fallback is
selected. Existing applied state, Provider binding, running compute, Runner-reported Workspace
path, and Agent Workspace storage remain until explicit replacement or terminal Runtime removal.

A System-Admin exact-version infrastructure Profile hard delete is permitted only when no current
Workspace Runtime Profile references the target. The transaction physically removes only the
Provider-owned Profile and terminalizes target-scoped pending or running recreation; it does not
rewrite Runtime desired or applied slots, Provider bindings, workloads, Runner-reported Workspace
paths, or Agent Workspace storage. A running Runtime may therefore retain the deleted Profile ID
inside its applied document as bounded historical evidence. That evidence is not a foreign key,
does not block deletion, and cannot authorize future create, start, restart, reset, or recreation.

## Ordinary automatic-start authority

`agent_runtimes` owns two nullable scalar fields,
`automatic_start_predecessor_sequence` and
`automatic_start_predecessor_generation`, constrained to be both null or both
valid. They are bounded current transition evidence, not configuration history
or foreign keys. Runtime row deletion removes them with their owner; they add no
new cleanup resource or public API field.

An ordinary internal start locks active Agent capability/selection, then Runtime,
then current configuration. It advances the exact stopped predecessor once and
records that pair, or joins its exact immediate current successor without another
mutation. Joining requires matching digest, current ready desired slot, running
START, unchanged capability, and sequence/generation each exactly predecessor + 1.
The original invocation adopts only that committed successor. It cannot follow
an unrelated START, a completed restart, or a chain of transitions.

Explicit lifecycle operations, removal/rearm/recreation, and material configuration
writes invalidate the pair atomically. Connection reports and ordinary
acknowledgements do not invalidate it. Old writers that advance counters without
clearing the new fields still break exact adjacency and fail joining closed.
Existing rows have no receipt until a new ordinary automatic start writes one.
The additive migration precedes server upgrade; server rollback may leave the
nullable columns in place.

## Event Persistence

| Provider | Event persistence | Scope |
|---|---|---|
| Kubernetes Provider v3 | EBS-backed PVC per Runtime | Production Kubernetes path |
| Docker Provider v1 | Per-Runtime host directory bind mount on a stable single Docker host | Local/dev single-host path |

S3/RustFS checkpoint objects are not the event persistence contract for Agent Runtime v1.
Legacy checkpoint rows may remain for older data/model compatibility, but new Runtime lifecycle
correctness must not depend on checkpoint commit/restore.

## Runtime System Metrics

The Runner optionally advertises `runtime.system-metrics.v1` and reports normalized CPU, memory,
and root-filesystem disk observations for its observable `host`, `vm`, or `container` scope.
Collection occurs immediately after registration and every 60 seconds for the accepted Runner
connection. CPU needs two cumulative-counter observations, so the immediate sample may expose
memory and disk while CPU is explicitly unavailable. Unsupported operating environments and
bounded source failures remain per-metric `unsupported` or `unavailable` observations; they never
become zero values or Provider-derived substitutes.

Runtime Control accepts a sample only for the current authenticated Runner connection generation
that advertised the capability. The report carries a positive generation-local sequence but no
Runner timestamp, hostname, path, mount, device, process data, or diagnostic string. Control
validates the closed scope and availability values, numeric invariants, and a 4 KiB serialized
message limit, assigns the UTC acceptance time, and atomically rejects duplicate or lower
sequences. Invalid, stale, capability-mismatched, or store-failed reports drop only that sample;
they do not close the Runner stream, change lifecycle/configuration state, or interrupt operations.

The Runtime Coordination Store retains one volatile series per Runtime and physical Runner
connection generation. Redis and in-memory implementations enforce the same higher-sequence
append, maximum 60 samples, one-hour expiry, and one-hour read filtering contract. A reconnect,
restart, reset, or replacement selects only the new generation and starts with an empty current
series. PostgreSQL, Providers, Agent Workspace storage, lifecycle reconciliation, and backup paths
do not own or reconstruct metrics; Coordination Store loss produces an empty overview while
ordinary Runtime behavior continues.

The Agent-authorized Public API exposes one privacy-safe system-metrics response beside the
lifecycle response. It selects only the permitted current or last-known disconnected generation
and projects CPU, memory, and disk current state from the latest observation without falling back
to an older available value. Available observations are `fresh` through three minutes inclusive
and `stale` afterward. Capability absence, missing/current unavailable data, stopped lifecycle, and
Runner disconnect remain explicit `unsupported`, `unavailable`, `stopped`, or `disconnected`
states. Stopped and disconnected overlays preserve retained trend samples until expiry.

azents-web consumes only the generated Public client through one tRPC query. The shared overview
appears in the chat Runtime/Workspace panel and Agent Runtime settings, polls at a fixed 60-second
interval only while its owning surface is visible or mounted, and is invalidated after lifecycle
mutations. The browser renders server-retained samples with unavailable observations and missed
intervals as true gaps; it does not accumulate, interpolate, or authorize history locally. Metrics
with a current percentage pair a 0–100 usage bar with a labeled locally scaled area trend. The
trend has no persistent or active point markers, tooltip, or touch/hover visual state. Metrics are
informational and cannot affect authorization, lifecycle, configuration, scheduling, billing, or
destructive operations.

## Workspace Path Contract

Runner resolves an explicit startup path before `HOME`, normalizes it, requires an absolute
non-empty value, and reports it during registration and state updates. Control stores valid
current-generation evidence on the Runtime row and exposes it through server-computed
workspace/bootstrap responses.

Providers choose their deployment mount paths and configure Runner `HOME` and working directory to
the mount. They do not report, approve, or clear Agent Workspace metadata. Missing or invalid Runner
evidence makes workspace operations unavailable, and a new desired generation clears the previous
path until its Runner reports current evidence.

## Destructive Operation Boundary

Only explicit `reset` and terminal delete may delete Agent Workspace data.

- `start` may create compute and attach durable storage; it must not wipe existing workspace bytes.
- `stop` may stop compute; it must preserve durable storage.
- `restart` may recreate compute; it must preserve durable storage.
- `recover` and reconciliation may repair stale backend/control state; they must preserve durable
  storage.
- ordinary Runtime Profile recreation may replace compute; it must preserve durable storage.
- `observe` is read-only.

Pixi global environments, exposed commands, manifest, and package cache follow the
same boundary because they live inside the existing Workspace storage. Ordinary
recreation preserves installed tools; reset and terminal deletion remove them
together with the Workspace.

For desired-running Runtimes, periodic reconciliation uses idempotent `start` to compare the
Provider-managed workload against the current Runner image and configuration. Equivalent workloads
are reused. Drifted Docker containers or Kubernetes Pods are replaced while the host workspace
directory or PVC remains intact.

Any ambiguous backend outcome is treated as unavailable or retryable until Provider evidence proves
the desired state. Ambiguity is not permission to delete the workspace.

Permanent managed Runtime removal persists one Agent-scoped operation with irreversible capability
fence, cleanup cursor/counts, interruption evidence, retry/lease state, exact target terminal-delete
generation, acknowledgement kind/time, and bounded failures. PostgreSQL is sufficient for
correctness; Redis may only accelerate wake-up.

Each removal or Agent-decommission claim increments its existing `attempt_count`.
Coordinators carry that returned attempt with the lease-owner identity into actual
phase/progress, retry and finalization predicates. An old attempt cannot complete a
reclaimed job even when the Scheduler or Worker retains the same lease-owner label.
Deletion-wait/acknowledgement observations do not lock the job or Runtime. Actual
target recording, acknowledgement publication and irreversible finalization fence the
admitted resource and current generation. When physical deletion is required, removal
completion also compares the recorded acknowledgement kind/time. No new lease token,
resource identity or retry mode is introduced.

Removal clears Session Project/worktree metadata, Runtime-only Toolkit projections, Agent Project
defaults/presets/catalog, and automatic Project policy items while preserving the automatic policy
settings row. It terminally invalidates every retained `pending` or `bound` Session folder binding.
After exact physical acknowledgement, finalization clears Profile selection,
deletes the bounded configuration-state row, keeps the Runtime-owned sequence high-water mark,
and sets capability to `none`.

Re-add reuses a retained logical Runtime ID only after completed removal and exact acknowledgement.
It advances desired generation, allocates the next configuration sequence, writes a newly resolved
ready desired slot with no applied slot, and starts stopped with no Workspace path or applied
incarnation evidence. The Provider therefore creates a fresh empty Workspace on later start; old
Session bindings and deleted Project/worktree rows are never restored.

## Kubernetes Provider v3

Kubernetes Provider v3 is an external process that talks to the Kubernetes API and Runtime Control
gRPC. It uses Kubernetes Lease leader election so only the active leader issues lifecycle commands
for a provider id. Lease creation is conditional on absence, while renewal and expired-holder
takeover use the exact observed `resourceVersion`; a `409 Conflict` means the process did not
acquire leadership and must remain or become standby.

Current Runtime Control admits protocol `agent-runtime-provider-kubernetes-v2` for retained legacy
direct contracts and protocol `agent-runtime-provider-kubernetes-v3` for current strict contracts.
Protocol v2 cannot send operational diagnostics and uses the legacy `network_policy`
reconciliation contract. Protocol v3 requires diagnostics and uses aggregate
`network_enforcement` evidence. Protocol v1 is rejected before capability contract proposal,
durable connection registration, or command authority. A connection cannot mix report contracts
or use protocol v2 as a fallback for a v3 strict contract.

A healthy non-leader process reports Kubernetes readiness while it can inspect the leader Lease, so
a single-replica rolling Deployment can replace the old leader without waiting for the standby to
become active first. On leadership acquisition, the process clears readiness until Runtime Control
authentication and registration succeed. Standby processes do not open the authoritative Control
stream or mutate Runtime resources.

The active Provider keeps the Kubernetes Pod watch as a long-lived request without a client total or
socket-read deadline. Normal server-side watch completion is reopened independently and does not
rotate the authoritative Runtime Control connection.

For each Runtime, the provider creates or reuses an EBS-backed PVC and mounts it at its configured
Runner home path in the Pod. PVC identity is tied to Runtime identity/generation labels
and fenced by Control generation. Stale observations cannot overwrite newer desired generations.

Reset is the only non-terminal command that may delete and recreate the PVC contents. Terminal
delete removes the PVC without recreating it. Stop/restart/recover and ordinary recreation must not
delete the PVC.

The Runtime Profile topology is typed Provider infrastructure, not arbitrary Pod input. A Profile
without DinD contains only the unprivileged Runner. A DinD-enabled Profile adds one
privileged DIND sidecar and mounts its Runtime-private Unix socket read-only into the Runner. There
is no Docker API Gateway or partial operation allowlist. The complete Docker capability supports
CLI, Compose, SDK, Testcontainers, Ryuk, and port-binding workflows supported by the daemon.
The Runner and DIND sidecar mount the Agent Workspace PVC at the same configured absolute
path and mount one Pod-local shared temporary volume at `/tmp`, bounded by the Profile's Runtime
ephemeral-storage allocation. Docker bind mounts sourced from the Agent Workspace or `/tmp`,
including Compose paths relative to the Agent Workspace, therefore resolve to the same files from
the Docker daemon's mount namespace. Other Runner root-filesystem paths are not shared bind-mount
sources.

The Runner and nested workloads do not receive the Provider ServiceAccount, Provider credentials,
host Docker socket, or another Runtime's DIND socket. Agent Workspace PVC storage remains distinct
from temporary Docker data, which uses a bounded engine-only `emptyDir`. The Profile may set the
DIND sidecar's Kubernetes CPU/memory requests and limits and fixed ephemeral-storage allocation.
PID, nested-container count, and per-Profile network fields are not advertised because direct
privileged Docker authority bypasses such in-daemon policy claims.

The Kubernetes Provider advertises Pod Profile schema versions 1, 2, and 3. Versions 1 and 2 remain
direct-only. Version 3 adds hierarchical `direct`, `proxy_required`, and `no_network` authority.
The selected Pod Profile remains the per-Runtime source of truth for resources, storage, network
authority, scheduling, identity, and optional DinD topology.

Direct mode keeps the complete Runtime NetworkPolicy inside the effective CIDR boundary.
Proxy-required mode removes Runtime DNS and direct customer egress, creates one Runtime-dedicated
proxy Service/Pod/policy ConfigMap/logical-Runtime CA, exposes only the public CA certificate to the
Runner, and constrains proxy egress by the inherited Provider CIDR boundary and effective domain
policy. No-network mode preserves Platform-owned Runtime Control, transfer, and
configured direct object-storage communication. The exact storage Service route is
deployment-owned rather than customer egress authority; missing or mismatched endpoint
readiness fails closed. Strict modes use
observed mandatory Service ClusterIPs as exact host mappings rather than DNS. The Pod Profile
separately controls Agent Workspace PVC capacity. Expansions may apply to the existing PVC; shrink
remains deferred until an explicit reset or terminal deletion recreates storage.

Pod lifecycle observation is independent of enforcement verification history. Explicit command
reports may carry exactly one structured aggregate `network_enforcement` result, while watch,
failover, and lifecycle-only reports may omit it. Runtime Control never persists drift evidence,
repair claims, retry times, resource inventory, or completion history. A successful
live-stream-correlated `OBSERVE` completion with current `drifted` evidence may make one
generation- and configuration-fenced, non-destructive `UPDATE_CONFIGURATION` dispatch. Missing or
drifted enforcement cannot acknowledge the desired configuration; exactly one current `in_sync`
aggregate can. Pending lifecycle dispatch and terminal deletion prevent repair. Stale evidence
cannot dispatch; a reconnect, stream/control restart, lost completion, or dispatch failure is
discarded and can retry only after a later periodic `OBSERVE`.

The logical Runtime CA and Agent Workspace PVC survive stop, restart, recovery, and ordinary
recreation. Proxy policy/artifact replacement retains the stable Service and CA identity. Reset and
terminal delete remain the only PVC-destructive boundaries; terminal delete also removes every
Provider-owned strict-network resource. A terminal-delete acknowledgement is emitted only after
the Provider observes the Runtime Pod, Workspace PVC, logical CA, and all owned strict-network and
proxy resources absent. While Kubernetes deletion is still in progress, the Provider reports a
non-acknowledged stopping observation and Control retries the same terminal delete.

## Docker Provider v1

Docker Provider v1 assumes one stable Docker host. For each Runtime it creates a host directory and
bind-mounts it into the Runner container at its configured Runner home path. The host directory is
the event persistence source.

New Runner containers use their stable `azents-runtime-<runtime_id>` container name
as the native hostname. Replacing the container for the same Runtime retains that
hostname, allowing Chromium to handle its existing same-host process lock after
an abrupt exit without deleting native profile data or bypassing profile locking.
This does not change Runtime authentication or generation fencing. Reused older
containers are not renamed, and existing stranded profile locks created under a
different hostname are not automatically migrated or removed.

The Provider protocol remains Docker Provider v1 while the selected infrastructure Profile may be
schema v1 or v2. Both versions use direct Runner execution. The durable host Workspace directory
remains mounted at the same Agent path, and the Provider-owned temporary directory is scoped to the
Runtime incarnation.

Stop/restart/recover and ordinary recreation may remove/recreate containers, but must keep the host
directory. Reset may delete or replace the host directory according to the reset command. Terminal
delete removes the container, Workspace directory, and Provider-owned ephemeral directories.

## Agent Workspace Projects

Session Workspace Project registry rows are AgentSession-scoped DB state. They are not derived from
filesystem snapshots. Runtime persistence preserves the bytes; the session registry preserves which
child paths are registered or awaiting registration approval for the selected conversation.

Project paths are normalized as children of the current Runner-reported Agent Workspace root. The root
itself is not a Project. Runtime persistence does not own Project membership. azents-web exposes
Project management inside the concrete session Workspace surface. The Workspace browser opens in
Project mode by default, keeps `All files` as an explicit Agent Workspace root inspection mode, and
uses backend Project browser manifest capabilities so Project root removal is registry-scoped rather
than filesystem-destructive.

Existing BOUND folder authority, Project/worktree inventory and filesystem-status
projection use ordinary reads without an inherited execution-owner transaction gate.
Only an actual PENDING bind changes binding state. Actual worktree action/resource
publication and terminal handoff explicitly fence the captured Session owner through
their database commit. Allocation, registration and destructive claims preserve
transaction-scoped Runtime/path overlap exclusion, including ancestor/descendant
targets; ordinary inventory does not inherit it. These changes do not alter Runner
target revalidation or the reset/terminal-delete storage boundary.

## Validation

Required checks:

- Docker provider tests show stop/restart preserves the host directory and reset is destructive.
- Kubernetes provider tests render PVC-backed Runtime resources and leader-election settings.
- Workspace service tests reject missing current Runner workspace paths with explicit errors.
- Runner state sink tests persist normalized Runner path authority and reject missing or invalid paths.
- Provider tests verify configured mount, Runner `HOME`, and working-directory alignment without Provider workspace reports.
- Deterministic azents E2E covers Agent Workspace bootstrap and reset action availability.
- Runtime Profile E2E uses Admin/Public API setup and a real Docker Provider to verify unconfigured,
  default, and explicit selection; exact desired/applied evidence; explicit recreation; Provider
  loss without substitution; retained selection; and recovery.
- Profile tests prove v1/v2 direct preservation, v3/Policy-v2 hierarchy, canonical current-state
  identity, historical null-field normalization, and active containment rejection.
- Docker and Kubernetes Provider tests prove Workspace persistence and ephemeral-state clearing on
  recreation.
- Runner tests prove HOME-based Pixi state survives ordinary recreation and is
  removed by the existing Workspace reset boundary.
- Kubernetes Provider unit, manifest, protocol, and lifecycle tests prove exact strict-mode
  resource ownership, comparison, replacement, cleanup, logical-CA retention, and PVC preservation
  without creating live Kubernetes resources.
- Schema and migration searches prove no containment application or availability state is
  persisted.
- Migration tests prove exact legacy effective-selection conversion and final absence of obsolete
  policy/override/snapshot schema.
- Runtime metrics tests cover Runner collection and scheduling, generation/capability/sequence
  admission, Redis/in-memory ring parity, Agent authorization and state projection, generated
  clients, localized web presentation, and the real Docker Runtime browser journey without direct
  database writes.

## Workspace runtime state and filesystem authority

`AgentWorkspaceFileService` receives the completed
`AgentWorkspaceAccessRepository` as an injected collaborator. The repository
loads the Agent and exact requester membership in a native PostgreSQL read-only
scope and returns detached authority after that scope closes. File orchestration
does not construct access owners from database managers or narrower repositories;
Runtime operation targets, Runner-reported paths, and file outcomes remain
independently authoritative.

Agent Workspace API exposes Agent Runtime capability and lifecycle state. Read APIs do not ensure or
start a Runtime. Server reads PostgreSQL capability, optional logical Runtime, Provider/Runner state,
configuration state, and durable removal progress as source of truth. When a logical Runtime exists,
the Agent Runtime response and Agent Workspace bootstrap response expose the same server-computed
lifecycle presentation: desired target, convergence, direct Provider connection/resource facts,
direct Runner state, overall availability, one bounded reason code, and desired generation.

Workspace retains its separate Runtime and access unions only for file-browser layout. Lifecycle
actions come from the same `AgentRuntimeService` authority used by Runtime Settings. The UI renders
one user-impact lifecycle status, separate execution-environment, Runtime-connection, and
host-control facts, and only actions that the server currently authorizes. It does not consume a
public single-summary projection or recompute availability and operation completion from
Provider/Runner raw state. Frontend-side judgment is limited to API failure and network error.

Managed Runtime surfaces also render the server-derived system-metrics overview. One
Agent-authorized response supplies CPU, memory, disk, Runner-observable scope, freshness/lifecycle
states, and a bounded one-hour series without Runtime, Runner, Provider, generation, hostname,
path, mount, device, or process identifiers. The concrete-session Runtime/Workspace panel polls
every 60 seconds only while the panel is visible; Agent Runtime settings polls while mounted.
Lifecycle mutations invalidate both lifecycle and metrics queries. Both surfaces share the same
localized responsive component, preserve unavailable samples and missed intervals as trend gaps,
show explicit loading/error/unsupported/unavailable/stale/stopped/disconnected states, and never
derive zero values or browser-owned history. When a current percentage exists, the component pairs
it with a 0–100 usage bar and a labeled locally scaled area trend. The trend has no persistent or
active point markers, tooltip, or touch/hover visual state.

The concrete-session Workspace panel requests the Project browser manifest only while the
server-provided Agent Workspace state is `READY`. Manifest loading or failure does not replace
lifecycle state and actions while the Agent Workspace is unavailable or transitioning. Workspace
and Runtime-backed directory pickers poll while lifecycle convergence is non-stable, permanent
removal is active, or configuration is waiting for recreation. They render the shared lifecycle
presentation and expose Start or Restart only when the corresponding server action is available.

| Runtime authority | Lifecycle availability | Workspace response and behavior |
|---|---|---|
| capability `none` | no lifecycle presentation | `UNAVAILABLE`; show the Runtime-free state and Add Runtime only when authorized |
| capability `removing` | `removing` | `UNAVAILABLE`; Runtime access is revoked while irreversible removal remains pending, with progress and no add/cancel action |
| stopped target and resource | `stopped` | `UNAVAILABLE`; expose Start only when the server action is available |
| starting, stopping, resetting, or recovering convergence | `transitioning` | `UNAVAILABLE` or `CONNECTING`; show convergence and do not expose `READY` early |
| no ready Runner and Provider command authority disconnected | `provider_disconnected` | `UNAVAILABLE`; explain that host controls are unavailable and show only server-authorized recovery actions |
| no ready Runner and desired configuration unavailable | `configuration_blocked` | `UNAVAILABLE`; explain the configuration impact and block actions that require a usable desired configuration |
| Provider resource running without a ready Runner | `runner_unavailable` | `UNAVAILABLE`; show the direct Runner fact, bounded reason, and only server-authorized actions |
| current-generation Runtime or Provider failure | `failed` | `UNAVAILABLE`; show the bounded lifecycle reason and only server-authorized actions |
| ready current-generation Runner serving an applied configuration | `ready` | `READY` when the current Runner-reported Agent Workspace path and exact applied operation target are valid, including while Provider host control is disconnected or a future desired selection is blocked or waiting for recreation |

Runtime-dependent file, browser, Project, directory-validation, and worktree operations resolve one
shared exact operation target. The resolver may request start/wait when the explicit operation
allows it; that host transition requires a usable desired configuration and Provider authority.
For an already-ready Runner, the target instead freezes the applied configuration sequence,
digest, and target generation plus the Runner generation and current Runner-reported Agent
Workspace path. Provider disconnection, Provider resource observation mismatch, or an unapplied
future desired configuration does not fence that current target. Missing or invalid Runner
evidence produces `RUNNER_WORKSPACE_PATH_MISSING` or `RUNNER_WORKSPACE_PATH_INVALID`. Runner loss,
terminal deletion, capability-version change, serving-authority supersession, timeout, or authority
drift fails closed, and the server does not invent a fallback path. The read-only Workspace summary
itself remains non-starting.

The Runtime response includes desired and applied current configuration-state status and evidence
without a process-containment projection. The UI keeps selected and applied Runtime Profile,
execution Profile, and effective network values visible for verification, while omitting sequence,
target-generation, digest, raw reason code, missing-capability identifiers, and acknowledgement
details from the normal product surface. It renders the status supplied by the server and does not
reconstruct physical security claims from raw Provider/Runner states.

Agent Workspace path preview first uses Runner `file.stat` to classify the path. Text-preview candidates use bounded `file.read_text` with UTF-8 strict decoding and character-count truncation metadata; their byte size does not reject an otherwise bounded character preview. Binary preview candidates remain byte-size bounded, return no text body, and do not use Control file chunks. Complete Workspace downloads authorize the requester before Runtime access, resolve and normalize the Runner-reported root, stat a regular file, and open a response-scoped verified Runtime transfer consumer. The consumer exposes only its opaque verified object through a bounded S3 iterator; the stream verifies exact size and SHA-256, keeps its lease renewed while the body is consumed, and acknowledges and settles only after exact EOF plus successful final ASGI body-send return. Source failure, lease/deadline loss, disconnect, or cancellation before that boundary abandons and cancels the attempt. Neither surface reconstructs a complete file body from Runner Control Base64 events. Directory paths return `DIRECTORY` listing data for tree navigation; azents-web opens directories in the file tree instead of rendering a separate directory preview page.

Lifecycle API is desired-state declaration. `start`/`stop`/`restart`/`recover`/reconcile and ordinary
recreation do not delete Agent Workspace data. Only explicit `reset` and terminal delete may delete
Agent Workspace data. Workspace, directory-picker, and Runtime Settings Restart controls require
explicit confirmation that storage is preserved while compute is temporarily unavailable. Reset
uses a distinct destructive confirmation and is rendered only when the server returns the Reset
action.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/core/session_workspace_paths.py`](../../../../python/apps/azents/src/azents/core/session_workspace_paths.py)
- [`python/apps/azents/src/azents/repos/agent_workspace_access.py`](../../../../python/apps/azents/src/azents/repos/agent_workspace_access.py)
- [`python/apps/azents-runtime-provider-docker`](../../../../python/apps/azents-runtime-provider-docker)
