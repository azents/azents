---
title: "Provider-Owned Runtime Process Containment"
created: 2026-08-08
tags: [runtime, provider, security, sandbox, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260808
---

# Provider-Owned Runtime Process Containment

- Snapshot: `runtime-260808`
- Document reference: `runtime-260808/ADR`
- Requirements: [Provider-Owned Runtime Process Containment Requirements](../requirements/runtime-260808-provider-process-containment.md) (`runtime-260808/REQ`)
- Decision mode: Requester-directed
- Decision owner: requester

## Context

The bundled Runtime Providers currently place trusted Runner code and Agent-originated
processes in the same broad operating-system authority. Child commands inherit the
Runner environment, native file and Git operations execute directly in the trusted
Runner process, and the current Profile contracts do not describe process containment.
The existing configuration protocol already generation-fences immutable resolved
configuration evidence reported by both Provider and Runner.

`runtime-260808/REQ` requires an explicit Provider-owned containment Profile that
protects trusted infrastructure while preserving Agent Workspace behavior, development
tooling, Runtime-scoped temporary storage, and ordinary outbound connectivity. It also
requires equivalent authority for Agent process and native operation surfaces, a
portable product contract, fail-closed qualification, and Runtime-independent model
execution.

## Decision Map

- [x] `runtime-260808/ADR-D1` — Model guidance source and evidence separation
- [x] `runtime-260808/ADR-D2` — Asynchronous Runtime lifecycle and explicit-operation readiness
- [x] `runtime-260808/ADR-D3` — Provider-qualified Runner-local containment topology
- [x] `runtime-260808/ADR-D4` — Unified contained authority for Agent-selected operations
- [x] `runtime-260808/ADR-D5` — Versioned portable Profile containment module
- [x] `runtime-260808/ADR-D6` — Pre-registration containment qualification
- [x] `runtime-260808/ADR-D7` — Allowlisted Agent environment and credential separation
- [x] `runtime-260808/ADR-D8` — Positive Agent filesystem and temporary-storage projection
- [x] `runtime-260808/ADR-D9` — Derived containment status projections
- [x] `runtime-260808/ADR-D10` — Pluggable containment backend interface
- [x] `runtime-260808/ADR-D11` — Docker trusted Runner bootstrap authority

Local identifiers, module placement, helper boundaries, equivalent fixture composition,
and exact behaviorally equivalent static prompt wording remain agent-owned implementation
details after the material contracts are fixed.

## Decisions

### runtime-260808/ADR-D1: Render bounded model guidance from the resolved desired Profile

**Affected requirements:** `runtime-260808/REQ-15`, `REQ-16`

Trusted Worker code renders behaviorally relevant Runtime guidance from validated typed
values in the immediately available resolved desired Runtime Profile. The renderer uses
code-owned bounded static templates and describes the contract that explicit Runtime
operations will follow when available. It does not claim that a physical Runtime is
currently connected, qualified, ready, or actively enforcing containment.

Provider and Runner configuration evidence remains physical application and readiness
validation input. Evidence identity, Runner diagnostics, Provider diagnostics, and
Profile-authored arbitrary prompt text are not rendered or translated into model prompt
wording. A blocked or unavailable resolved Profile produces only a generic bounded
Runtime-unavailable statement.

**Rejected alternatives:**

- Rendering Runner-provided prompt text was rejected because it would mix physical
  enforcement diagnostics with model instructions and create a new unbounded trust
  boundary.
- Deriving prompt wording from current Runner readiness or applied evidence was rejected
  because prompt stability would then depend on asynchronous physical lifecycle state.
- Omitting all Profile-derived guidance was rejected because the model still needs the
  stable behavioral contract of the Runtime operations it may request.

### runtime-260808/ADR-D2: Keep model execution asynchronous from Runtime readiness

**Affected requirements:** `runtime-260808/REQ-10`, `REQ-15`, `REQ-16`

Session input admission, wake-up, prompt construction, and otherwise model-eligible
dispatch do not wait for Runtime creation, startup, qualification, registration,
heartbeat, reconnection, or readiness. Runtime lifecycle and configuration-evidence
convergence proceed asynchronously relative to ordinary model inference.

An explicitly ordered Runtime-dependent TurnAction or a model-requested Runtime tool
call resolves a Runtime whose applied configuration matches the current resolved desired
Profile, waits for its Runner through a bounded, cancellable, observable wait attributed
to that operation, and then awaits the bounded Runner operation. `BUSY` remains a
qualified operational state and does not invalidate retained matching qualification.

**Rejected alternatives:**

- A Session-wide readiness gate was rejected because it would turn background Runtime
  startup into hidden model latency and prevent Runtime-independent turns.
- Prompt-time Runner polling was rejected because it would couple static context
  construction to volatile physical state.
- Failing explicit operations immediately whenever the Runner is not already ready was
  rejected because ordered setup actions and Runtime tools require bounded readiness
  acquisition rather than a single instantaneous state check.

### runtime-260808/ADR-D3: Use a Provider-qualified Runner-local containment boundary

**Affected requirements:** `runtime-260808/REQ-2`, `REQ-3`, `REQ-5`, `REQ-9`,
`REQ-10`, `REQ-11`, `REQ-14`

The trusted Runner remains the Runtime operation supervisor. It dispatches every
Agent-originated process and Agent-facing operation through a Runner-local containment
backend that creates a separate Agent authority with its own bounded filesystem,
process, environment, privilege, and socket view. Agent descendants remain inside that
authority for their complete lifetime.

Each Provider prepares the physical Runtime so the backend can operate and declares the
matching typed Profile capability. Provider and Runner qualification verifies the
actual operating-system, container-runtime, kernel, and mandatory-access-control
environment before the Runtime becomes qualified for the contained Profile. Missing or
failed backend support fails closed.

The product contract and Profile capability describe observable containment behavior,
not the concrete Linux backend or command-line arguments. Kubernetes and Docker may
prepare and qualify the backend differently while exposing the same local containment
contract. A future non-Linux Provider may use another Runner-local implementation.

**Rejected alternatives:**

- A separate trusted Runner container and Agent executor container topology was
  rejected for the initial feature because it would require a new multi-container
  lifecycle and operation-dispatch protocol across both bundled Providers.
- A Runtime-level VM, gVisor, or Kata boundary was rejected as the required initial
  mechanism because it would prevent practical Docker Provider parity and make the
  portable capability depend on one infrastructure class.
- Treating the existing Runner container boundary as sufficient was rejected because
  Agent processes currently share the Runner's process, environment, and filesystem
  authority inside that container.

### runtime-260808/ADR-D4: Route every Agent-selected operation through one contained authority

**Affected requirements:** `runtime-260808/REQ-2`, `REQ-4`, `REQ-6`, `REQ-7`,
`REQ-14`

Every operation whose command, path, repository target, or file selection originates
from Agent-visible input executes its operating-system access inside the contained Agent
authority defined by `runtime-260808/ADR-D3`. This includes foreground and managed
processes, file reads and mutations, search, edit, patch, Git operations, import,
presentation, transfer, and their descendants.

The trusted Runner may validate the typed operation envelope, enforce quotas and
deadlines, create the contained execution context, cancel the operation, and transport
bounded input, output, or opaque file bytes. It does not use its broader filesystem
authority to open an Agent-selected path or perform an Agent-selected Git operation.
Transfer and presentation services may act outside containment only after the contained
operation has resolved and read the selected file into the bounded transfer flow.

A product-owned typed system operation may use separately validated trusted authority
only when Azents fixes the exact operation, trusted identity, and path scope. Its input
cannot select arbitrary commands or expand filesystem authority, and its implementation
must not be reusable as an Agent-facing path-access bypass.

**Rejected alternatives:**

- Keeping native file and Git operations in the trusted Runner with a mirrored path
  policy was rejected because it would create a second authorization model vulnerable
  to policy drift, symlink mistakes, and operation-specific bypasses.
- Confining mutations while allowing trusted native reads and search was rejected
  because read access can expose Runner code, credentials, process state, and sockets.
- Maintaining operation-specific trusted exceptions for performance was rejected
  because new tools would require repeated security classification and could silently
  weaken the complete-operation coverage contract.

### runtime-260808/ADR-D5: Add a portable containment module in new Profile schema versions

**Affected requirements:** `runtime-260808/REQ-1`, `REQ-8`, `REQ-9`, `REQ-11`,
`REQ-13`, `REQ-15`

The existing `kubernetes.pod-profile` and `docker.container-profile` contract families
retain schema version 1 unchanged. Each family adds schema version 2, which may carry
the same shared, versioned process-containment module. A contained Infrastructure
Profile is a version 2 Profile with that module explicitly present and required.
Existing version 1 Profiles remain non-contained and preserve their current behavior.

The shared module expresses the portable observable containment contract rather than
Provider-specific backend arguments. Provider capability contracts advertise support
for the new Profile schema version and the portable process-containment capability.
Compatibility evaluation derives that capability requirement from the typed module
before Profile publication or Runtime resolution.

Typed Profile validation rejects process containment combined with Agent-accessible
nested Docker. Provider backend names, Linux namespace arguments, mandatory-access-
control rules, credential locations, and qualification diagnostics are not Profile
configuration. Adoption or removal of the containment module changes physical Runtime
authority and therefore requires Runtime recreation.

The Worker derives bounded model guidance from the typed effective Profile, including
the containment module and other behaviorally relevant Profile modules such as nested
Docker and network policy, according to `runtime-260808/ADR-D1`.

**Rejected alternatives:**

- Adding optional containment fields to the existing version 1 schemas was rejected
  because it would change the meaning and compatibility requirements of an established
  contract version.
- Creating separate contained Kubernetes and Docker Profile kinds was rejected because
  it would duplicate resource, storage, network, and scheduling contracts and fragment
  future Provider support.
- Inferring containment from Provider identity, capability metadata alone, or Profile
  naming was rejected because resolved configuration, digesting, recreation impact, and
  prompt behavior require one explicit typed source of truth.

### runtime-260808/ADR-D6: Qualify containment before Runner registration

**Affected requirements:** `runtime-260808/REQ-2`, `REQ-9`, `REQ-10`, `REQ-13`

For a contained Profile, the Runner initializes the configured containment backend
and performs its local enforcement checks before opening its normal Runtime Control
connection and registering as the current Runner. The checks execute test work through
the same contained authority used by Agent operations and verify the required
filesystem, process, environment, privilege, credential, and socket boundaries.

Only a Runner that passes qualification may connect, register with its existing
`RuntimeConfigurationEvidence`, and accept Agent operations. Runtime Control continues
using the existing revision, digest, desired-generation, and Runner-generation fences;
qualification does not create a separate persisted authority or replace configuration
evidence.

A Runner that cannot initialize or qualify the configured containment implementation
does not register, does not accept operations, and does not fall back to direct or
weaker execution. The Provider observes it as a bounded startup failure. Physical
Runtime recreation starts a new Runner and therefore repeats qualification before the
new registration.

**Rejected alternatives:**

- Registering first and qualifying afterward was rejected because an unqualified
  Runner would temporarily hold operation authority and appear as a current Runner.
- Treating Provider capability advertisement or Profile validation as qualification
  was rejected because they do not test the actual Runner environment.
- Registering an unqualified Runner in a failed mode was rejected because failed
  containment must not acquire normal Runner connection or operation authority.
- Falling back to unsandboxed execution was rejected because contained Profiles are
  fail-closed.

### runtime-260808/ADR-D7: Build an allowlisted Agent environment without Runner inheritance

**Affected requirements:** `runtime-260808/REQ-2`, `REQ-5`, `REQ-7`, `REQ-14`

Contained Agent processes do not inherit the trusted Runner's process environment.
The Runner constructs a new environment from a code-owned safe base allowlist and then
adds only values explicitly authorized for Agent use by the current operation and
enabled Toolkits.

Runner authentication tokens and credential IDs, Runtime Control and transfer
configuration, Provider configuration, TLS material, configuration evidence, and other
Runner-reserved names never enter the contained environment. Agent-supplied or
Toolkit-supplied values cannot override those reserved names. Toolkit credentials are
carried as operation-scoped Agent inputs rather than added to the trusted Runner's
global environment.

The initial feature preserves the existing semantics of credentials intentionally
granted to Agent commands. GitHub Toolkit tokens, EnvVar Toolkit values, and equivalent
explicit Agent credentials may therefore be present in the contained process
environment. The Git credential helper executes inside the contained authority and
uses only those Agent-authorized values. A fully compromised Agent process can access
credentials intentionally granted to it, but cannot expand that access into Runner,
Runtime Control, Provider, workload, host-runtime, or unrelated-Runtime authority.

**Rejected alternatives:**

- Copying the Runner environment and deleting known secret names was rejected because
  new infrastructure variables could become exposed by omission.
- Moving every Agent-authorized credential behind a trusted broker was rejected for the
  initial feature because it would change arbitrary `git`, `gh`, SDK, package-client,
  and EnvVar Toolkit behavior and require a separate credential-execution product
  contract.
- Removing all credentials from contained Profiles was rejected because it would make
  ordinary authenticated development workflows unavailable.

### runtime-260808/ADR-D8: Project only the Agent filesystem contract into containment

**Affected requirements:** `runtime-260808/REQ-2`, `REQ-4`, `REQ-5`, `REQ-6`,
`REQ-9`, `REQ-14`

The contained authority receives a positive filesystem projection rather than the
trusted Runner filesystem with a denylist. The current Runner-reported absolute Agent
Workspace path is preserved and mounted read-write with its existing Session, Project,
Skill, instruction, shared-file, and cross-Session behavior.

The bundled system and development toolchain required for ordinary Agent work is
available read-only. Exact operating-system paths remain a Design detail, but the
projection includes the executables, libraries, certificates, and system data needed
to run the supported tools without exposing the trusted Runner installation, private
state, credentials, infrastructure sockets, host filesystem, or unrelated Runtime
storage.

Each physical Runtime has one dedicated Agent temporary storage projection mounted at
the standard `/tmp` path, including compatibility for existing `/tmp/agent` workflows.
It is read-write and shared by contained Agent operations for that physical Runtime
lifetime, but is not durable Workspace state and is discarded on Runtime recreation,
reset, or terminal deletion. The trusted Runner uses separate private temporary storage
that is absent from the Agent projection.

The contained process view exposes only the Agent process tree and bounded device view,
not trusted Runner processes or host process state. Every Agent-facing process, file,
Git, import, presentation, and transfer operation uses the same filesystem projection.
Kubernetes and Docker Providers may use different volume and directory implementations
while preserving these paths and semantics.

**Rejected alternatives:**

- Exposing the Runner filesystem and hiding known sensitive paths was rejected because
  new Runner state, sockets, or installation paths could become visible by omission.
- Sharing the Runner's temporary directory was rejected because trusted transient
  state and credentials could cross the containment boundary.
- Creating a separately maintained Agent tool image was rejected for the initial
  feature because it would duplicate the bundled development environment and add a
  second image lifecycle across both Providers.
- Creating Session-scoped temporary storage was rejected because the required contract
  is shared for the physical Runtime lifetime.

### runtime-260808/ADR-D9: Derive containment status from existing Runtime authority

**Affected requirements:** `runtime-260808/REQ-10`, `REQ-13`, `REQ-15`, `REQ-16`

Azents does not persist a separate `contained` boolean or containment lifecycle status.
Containment projections are derived from the existing authoritative state:

- the resolved desired Profile states whether containment is required;
- desired and applied configuration revisions determine whether that exact Profile has
  been physically adopted; and
- the current qualified Runner authority and state determine whether explicit Runtime
  operations are presently available.

A desired contained Profile alone never means that the existing physical Runtime is
contained. During pending recreation, configuration adoption, startup, qualification
failure, stop, or Runner unavailability, each product surface derives the appropriate
bounded projection without creating another source of truth.

Administrative surfaces may expose Profile compatibility, desired-versus-applied
adoption, recreation impact, current Runner availability, and bounded backend
diagnostics. Workspace and Agent surfaces expose only the effective capability,
recreation requirement, Runtime availability, nested-Docker availability, and safe
bounded reasons. Exact UI placement and wording remain Design details.

The model prompt remains intentionally different: according to
`runtime-260808/ADR-D1`, it describes the resolved desired Profile contract and does
not consume applied revision, qualification, or current Runner state.

**Rejected alternatives:**

- Persisting a separate containment boolean or status was rejected because it could
  drift from Profile selection, configuration adoption, and Runner authority.
- Treating desired Profile selection as active containment was rejected because the
  old physical Runtime may still be running before recreation.
- Treating Runner state alone as containment status was rejected because readiness does
  not identify which Profile revision the Runner applied.
- Exposing one undifferentiated contained/not-contained value was rejected because it
  cannot represent pending adoption, recreation, startup, or temporary unavailability
  without making a false enforcement claim.

### runtime-260808/ADR-D10: Isolate concrete sandbox implementations behind one Runner interface

**Affected requirements:** `runtime-260808/REQ-9`, `REQ-10`, `REQ-11`, `REQ-14`

Runner process, file, Git, import, presentation, and transfer operations depend on one
backend-neutral containment interface rather than invoking `bwrap` or constructing
implementation-specific sandbox arguments directly. Operations submit a generic
contained-execution specification containing the command or contained helper, working
directory, Agent environment, filesystem projection, bounded input and output,
deadline, cancellation, and managed-process requirements.

One concrete backend is selected by trusted Runtime deployment configuration when the
physical Runner starts. That backend performs the pre-registration qualification
defined by `runtime-260808/ADR-D6` and then serves every contained operation for the
Runner incarnation. The portable Profile module requires containment behavior but does
not name or configure a backend implementation.

`bwrap` may be the initial Linux backend adapter. Another Linux or future non-Linux
backend can implement the same qualification and execution contract without changing
Agent tools, Runner operation envelopes, Runtime Control protocols, Profile schemas,
or model guidance. All implementations must pass one common functional and security
conformance suite.

The Runner does not select a backend per operation and does not automatically fall back
to direct execution, another backend, or weaker containment when the configured backend
is absent, unsupported, or fails qualification.

**Rejected alternatives:**

- Calling `bwrap` directly from Runner operation handlers was rejected because backend
  options, errors, process lifecycle, and cancellation would spread across every
  Agent-facing operation.
- Hiding direct `bwrap` calls behind a shell wrapper was rejected because the Runner
  contract and tests would remain coupled to one command-line implementation.
- Shipping separate Provider-specific Runner operation implementations was rejected
  because Kubernetes and Docker behavior and security guarantees could drift.
- Allowing per-operation backend selection or fallback was rejected because one
  physical Runtime must expose one coherent qualified Agent authority.

### runtime-260808/ADR-D11: Grant only the Docker trusted Runner the bootstrap authority required by bwrap

**Affected requirements:** `runtime-260808/REQ-2`, `REQ-3`, `REQ-5`, `REQ-9`,
`REQ-10`, `REQ-11`, `REQ-14`

For a contained Docker Profile using the initial bwrap backend, the trusted Runner
container starts as UID/GID 0 with all Linux capabilities dropped and only
`CAP_SETUID`, `CAP_SETGID`, `CAP_SETFCAP`, and `CAP_SYS_ADMIN` added. Docker's default
system-path masking is disabled for that container because bwrap must construct a new
`/proc` and mount view. The deployment applies the dedicated enforcing AppArmor profile,
uses the unconfined seccomp preparation required by the supported bwrap environment, does
not run privileged, and exposes no Docker or infrastructure socket.

This authority belongs only to the trusted Runner supervisor while it creates the
contained namespace. The Runner container itself cannot use Docker
`no-new-privileges`, because that prevents the required UID/GID mapping. Instead, bwrap
sets `NoNewPrivs=1` inside the contained authority, maps the Agent child to UID/GID 1000,
drops every effective, permitted, inheritable, ambient, and bounding capability, and
disables nested user namespaces before executing Agent-selected code. Qualification
verifies these child invariants through the same backend entry point used by operations.

The Docker-specific trusted bootstrap authority does not change the portable Profile
contract and is not inherited by Kubernetes or future Providers. Each Provider remains
responsible for selecting the least authority that can satisfy the common contained
child contract in its environment.

**Rejected alternatives:**

- Keeping the Docker Runner at UID/GID 1000 was rejected because a non-root process can
  create a user namespace on the target host but cannot establish the required
  UID/GID 1000-to-1000 mapping for the contained child.
- Setting Docker `no-new-privileges` on the trusted Runner container was rejected because
  it prevents bwrap from installing the required UID/GID mapping before the Agent child
  exists.
- Set-user-ID bwrap, file capabilities, `newuidmap`/`newgidmap`, an unconfined AppArmor
  profile, and adding only individual mapping capabilities to a non-root Runner were
  rejected because feasibility probes did not produce the required child identity and
  authority.
- A privileged Runner container was rejected because the required preparation succeeds
  with the explicit capability set and security fields above.
- Granting the bootstrap capabilities to the Agent child was rejected because it would
  directly violate the contained privilege contract and permit authority expansion.

## Consequences

- Model context remains stable across ordinary Runner ready/busy/reconnecting transitions.
- Physical containment claims remain grounded in Provider/Runner qualification rather
  than prompt wording.
- Runtime-independent conversation can continue while a physical Runtime is unavailable.
- Explicit Runtime actions surface their own readiness latency, timeout, cancellation,
  and failure instead of hiding it in Session startup.
- Both Providers must prepare and qualify a Runner-local containment backend, but the
  concrete Linux mechanism remains an implementation and diagnostic detail.
- Native Runner file and Git implementations must be replaced or routed through the
  contained authority rather than preserved as a parallel Agent-facing access path.
- Trusted typed system operations require explicit fixed scope and non-convertibility
  evidence in the complete Design.
- Provider registrations, Profile parsing, compatibility evaluation, canonical
  configuration digesting, recreation classification, and administrative Profile
  surfaces must support both unchanged version 1 and new version 2 contracts.
- Contained Runner startup must complete qualification before the normal Control run
  loop begins; startup failure remains Provider-observed rather than creating a second
  Control-side qualification state machine.
- Runner operation launch no longer uses `os.environ.copy()` as the Agent environment,
  and tests must prove that newly introduced Runner variables are denied by default.
- Existing user-authorized credential exposure remains explicit Agent authority rather
  than trusted Runtime infrastructure authority.
- Both Providers must provision separate Agent and Runner temporary storage and make
  only the positive Agent filesystem projection available to the containment backend.
- Path-preservation tests must prove that existing Agent Workspace and `/tmp/agent`
  workflows remain compatible while Runner-private paths are absent.
- APIs and user interfaces derive containment projections from existing Profile,
  configuration-revision, and Runner authority rather than synchronizing a new
  containment state field.
- The initial sandbox implementation is delivered as an adapter behind the shared
  interface, and direct `bwrap` construction is absent from Runner operation handlers.
- Backend additions require implementation and conformance evidence, not Agent-facing
  protocol or Profile changes.
- The contained Docker Runner is a trusted root bootstrap supervisor with four explicit
  capabilities, while every Agent child remains UID/GID 1000, capability-free,
  no-new-privileges constrained, and unable to create a nested user namespace.
