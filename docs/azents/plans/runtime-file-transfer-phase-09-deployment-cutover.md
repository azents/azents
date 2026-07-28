---
title: "Runtime File Transfer phase 9: Deployment and coordinated cutover"
created: 2026-07-26
tags: [runtime, files, transfer, deployment, helm, security, provider]
---

# Runtime File Transfer phase 9: Deployment and coordinated cutover

## Phase Execution Plan

- Phase: `9 — Deployment and coordinated cutover`
- Branch/base: `feature/runtime-file-transfer-09-deployment-cutover` → `feature/runtime-file-transfer-08-external-channel-outbound`
- PR boundary: Activate the already-implemented Runtime File Transfer contracts only through one coordinated Runtime Control, Runner, provider, API Server, Worker, and Helm deployment configuration. The cutover fails closed when its strict protocol, trust, state-owner, storage-lifecycle, or protected-staging prerequisites are absent.
- Inputs: Confirmed `transfer-260725/REQ`; accepted `transfer-260725/ADR`; approved `transfer-260725/DESIGN`; current runtime/provider and file-storage specs; multi-phase implementation plan; completed Phases 3–8; current Docker/Kubernetes provider, Runtime Runner, Runtime Control, backend composition, and Helm seams.
- Deliverables: Runtime Provider lifecycle transfer configuration; strict Runner registration/capability admission; protected same-filesystem download staging; Runtime Control transfer S3/state/limits/coordinator composition; API Server and Worker coordinator trust configuration; Docker/Kubernetes environment allowlists and reconciliation; Helm values/schema/templates/render tests; lifecycle-defense/operator evidence contract; deterministic cutover and rollback documentation/tests.
- Non-goals: New transfer protocol semantics; gRPC message-limit changes; Runner S3 authority; presigned URLs; mixed-version or inline-binary fallback; independent transfer deployment by default; Exchange/Artifact/External Channel product changes; provider file policy changes; new public APIs; Phase 10 E2E promotion; living-spec promotion; a protected staging fallback that is visible or writable to workload code.

### Fixed cutover contract

The deployment has one supported Runtime transfer generation. Runtime Control, Runner,
API Server, Worker, and adopted consumers move together. Runtime work resumes only after
all of the following are true:

1. Runtime Control exposes the typed Runner Transfer and trusted Coordinator services
   using the configured TLS/trust boundary.
2. Runner registers the exact supported protocol version and `file.transfer.v1`
   capability before ordinary Runtime work is accepted.
3. Runtime Control has a valid transfer state backend, bounded transfer settings,
   trusted object-storage configuration, and transfer-prefix cleanup configuration.
4. API Server and Worker authenticate to the coordinator using the trusted-service
   credential root and never construct Transfer State locally.
5. The selected Runtime Provider gives Runner the transfer endpoint and existing trust
   material but never gives it S3 credentials, bucket names, object keys, provider
   credentials, or storage topology.
6. `overwrite=true` download uses protected same-filesystem staging; otherwise the
   existing fail-closed refusal remains active.

Old, missing, or capability-incomplete Runner registrations are rejected before normal
operations resume. A Control reconnect does not convert an old Runner into a compatibility
mode. Rollback is likewise coordinated: it drains/stops affected Runtime work, removes the
new generation as one unit, and relies on existing logical-expiry/cleanup contracts for any
inaccessible transfer objects.

### Interface contract: Runtime Control transfer composition

Runtime Control alone constructs and owns:

- `RuntimeTransferStateStore` using `memory` or `redis`;
- transfer object storage under the internal transfer prefix;
- bounded TTL, terminal TTL, chunk, multipart part, buffer, stream, copy, and cleanup
  settings; and
- authenticated Coordinator service admission for Server and Worker callers.

Settings validate transfer TTL and terminal metadata TTL as positive and at most 3,600
seconds. Chunk/part/concurrency values must yield a calculable bounded process-memory
maximum. The transfer endpoint defaults to the Runtime Control endpoint while retaining a
distinct Runner transfer channel.

Memory transfer state is valid only when every Runner Transfer and Coordinator request
routes to one Runtime Control owner. Helm rejects `memory` with more than one replica or
an enabled HPA above one replica. Redis transfer state permits multi-replica Control, but
existing Redis-backed Runtime Coordination remains required in every state mode.

Runtime Control receives object-storage authority only through existing trusted server
configuration. Transfer-prefix lifecycle and incomplete multipart abort settings are
configured where Azents owns the bucket. For externally managed storage, deployment is
blocked until the operator supplies documented evidence for equivalent prefix expiration
and incomplete-multipart defense. Those defenses supplement, never replace, synchronous
logical expiry and explicit cleanup.

### Interface contract: trusted service and Runner configuration

API Server and Worker receive only the Coordinator endpoint, TLS trust, and short-lived
trusted-service credential configuration. They continue to use Runtime Coordination through
Redis and do not receive an in-process transfer state or transfer object identity.

Docker and Kubernetes Runtime Provider lifecycle declarations gain explicit bounded transfer
endpoint/trust configuration and propagate it through desired-state serialization,
comparison, creation, recreation, and reconciliation. Runner receives:

- the transfer endpoint;
- the existing Runtime Control endpoint and TLS/bearer trust material; and
- bounded Runner transfer concurrency/staging configuration.

Runner does not receive object-storage settings, bucket names, object keys, S3 credentials,
presigned access, provider credentials, or Coordinator credentials. Provider manifests,
container environments, pod specs, logs, health responses, and tests must prove this
negative boundary.

### Interface contract: protected same-filesystem staging

Runtime download publication with `overwrite=true` requires a provider-created staging
boundary that is on the destination filesystem but inaccessible to workload code. The
boundary must prevent workload code from reading, replacing, linking, renaming, deleting,
or precreating a staging entry. Runner validates the boundary before accepting the intent,
uses an attempt-owned protected entry, syncs content, atomically replaces the destination,
and removes its exact staging evidence on every exit.

Docker and Kubernetes implement provider-specific UID, mount-namespace, ownership, and
volume/mount controls while preserving the shared invariant. A same-UID writable pathname,
a directory reachable by the workload, a symlink escape, an unavailable staging boundary,
or a cross-filesystem destination fails closed. Existing destination content remains visible
until the verified atomic replacement commits. Named protected staging cleanup is bounded,
identity-fenced, and cannot delete workload files.

### Interface contract: Helm and operator contract

Helm exposes typed transfer settings under Runtime Control and provider values, validates
cross-field constraints in `values.schema.json`, and renders only existing-secret references
for trusted credentials. Default values contain no secret literals. Runtime Control
Deployment, service, HPA, provider templates, NetworkPolicy, API Server, and Worker use
one compatible endpoint/TLS configuration.

Helm render tests cover:

- memory state with one Control replica and no HPA above one;
- Redis transfer state with permitted replica/HPA settings;
- missing/invalid coordinator trust, transfer state, S3/lifecycle, or provider settings;
- Runner environment allowlists with no storage authority;
- Docker/Kubernetes lifecycle desired-state changes on transfer configuration;
- strict protocol/capability registration; and
- protected staging configuration/fail-closed behavior.

Document an operator acknowledgement template for externally managed object storage:
transfer prefix, expiration interval, incomplete multipart abort policy, responsible owner,
evidence timestamp, and rollback owner. Missing acknowledgement blocks cutover instead of
silently assuming bucket lifecycle behavior.

### Failure, rollout, and observability contract

- Registration rejects unsupported protocol versions and missing/false
  `file.transfer.v1` capability before ordinary Runtime work begins.
- Endpoint, TLS, Coordinator credential, state backend, bucket lifecycle, staging, or
  memory-single-owner validation failure prevents Runtime transfer admission and reports a
  bounded configuration failure without bytes or secrets.
- Provider reconciliation recreates a Runtime when its transfer endpoint/trust/staging
  desired state changes; it never patches an old Runner into compatibility mode.
- Cutover smoke evidence records only bounded deployment generation, protocol/capability,
  state backend, endpoint reachability, transfer phase/outcome, size/hash result, and
  lifecycle-policy acknowledgement. Logs exclude bytes, object handles, keys, buckets,
  credentials, bearer headers, and provider secrets.

| Workstream | Owner | Owned paths | Output | Validation |
| --- | --- | --- | --- | --- |
| Runtime Control/server composition | `/root/runtime-transfer-implementer` | Runtime Control settings/composition, backend Worker/API composition, coordinator trust tests | Transfer S3/state/settings/coordinator activation | Config and single-owner/Redis parity tests |
| Provider lifecycle and Runner staging | `/root/runtime-transfer-implementer` | Docker/Kubernetes providers, Runner config/staging, lifecycle/protocol tests | Endpoint/trust propagation, strict capability, protected staging | Provider reconciliation and hostile-workload staging tests |
| Helm and operator lifecycle contract | `/root/runtime-transfer-implementer` | chart values/schema/templates/tests, operator documentation | Rendered secure deployment and lifecycle acknowledgement | `helm lint`, render/schema tests, no-secret/no-Runner-S3 assertions |
| Independent review and final verification | `/root/runtime-transfer-reviewer`, then `/root` | Read-only cumulative Phase 9 diff | Security/cutover review and recheck | Trust, state-owner, staging, strict-cutover, and scope audit |

- Integration order: (1) add settings and configuration validation; (2) compose Control,
  API Server, and Worker Coordinator trust; (3) add provider lifecycle endpoint/trust and
  strict registration propagation; (4) add protected staging boundary; (5) render Helm
  settings/schema/templates and operator contract; (6) run focused validation; (7)
  implementation owner requests review, remediates accepted Critical/Warning findings, and
  requests the same reviewer recheck.
- Scope-drift check: Reject Runner S3 access, protocol compatibility, any gRPC limit
  increase, a second default transfer deployment, deployment activation without strict
  cutover, ordinary file-tool rewrites, provider product behavior changes, fallback staging,
  a relational transfer entity, secret literals, or Phase 10 validation/spec-promotion work.

## Required evidence before independent review

- Docker and Kubernetes desired-state reconciliation propagates the transfer endpoint and
  trust material, recreates obsolete Runtime generations, and gives Runner no object-store
  authority.
- Old/missing protocol registrations and missing `file.transfer.v1` capability are rejected
  before ordinary Runtime work; the exact coordinated generation succeeds without a legacy
  fallback.
- Memory state rejects multi-replica/HPA deployment while Redis state preserves existing
  Redis Runtime Coordination and permits supported multi-replica Control deployment.
- Runtime Control/API/Worker configuration uses authenticated Coordinator access and bounded
  transfer settings; TTLs above 3,600 seconds and unbounded memory combinations fail config
  validation.
- Workload code cannot access protected staging and `overwrite=true` preserves the previous
  destination until verified atomic replacement. Missing, exposed, or cross-filesystem
  staging fails closed.
- Helm values/schema/render tests and operator evidence prove lifecycle/incomplete-multipart
  defenses without placing S3 credentials, keys, buckets, URLs, or topology in Runner pods.
- Coordinated deploy, recreation, transfer smoke, rollback, cleanup, and operator
  acknowledgement instructions are documented with no production secret values.
