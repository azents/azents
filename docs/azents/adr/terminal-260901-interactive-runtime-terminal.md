---
title: "Interactive Runtime Terminal"
created: 2026-09-01
tags: [terminal, runtime, session, websocket, security, architecture]
document_role: primary
document_type: adr
snapshot_id: terminal-260901
---

# Interactive Runtime Terminal

- Snapshot: `terminal-260901`
- Document reference: `terminal-260901/ADR`
- Requirements: [Interactive Runtime Terminal Requirements](../requirements/terminal-260901-interactive-runtime-terminal.md) (`terminal-260901/REQ`)

## Decision Map

- [x] `terminal-260901/ADR-D1` — Use a dedicated resource-bound Terminal WebSocket contract.
- [x] `terminal-260901/ADR-D2` — Use one dedicated bidirectional Runner stream per active Terminal.
- [x] `terminal-260901/ADR-D3` — Use one fenced attachment, lossless live delivery, and a bounded replay tail.
- [x] `terminal-260901/ADR-D4` — Use first-class Profile and Agent settings with live control-plane composition.
- [x] `terminal-260901/ADR-D5` — Use a bounded interactive-work lifecycle with complete session cleanup.
- [x] `terminal-260901/ADR-D6` — Use an additive stacked rollout followed by complete `shell_enabled` removal.

## Context

Azents currently supports bounded Runtime operations and managed pipe-based processes through an outbound authenticated Runner gRPC connection. Those operations have Session ownership, generation fencing, cancellation, bounded unread output, process-group termination, and Runtime/Session quotas, but they do not allocate a PTY, expose terminal resize, or maintain one ordered interactive byte stream.

Public Chat WebSocket connections use a short-lived ticket and a JSON event protocol. The Runtime operation path uses generation-scoped coordination streams intended for bounded operations. Production coordination is Redis-backed and standalone/test coordination has an in-memory implementation. The current operation reply streams are TTL-based rather than length-bounded, and Runner operation, heartbeat, and transfer traffic share a small outbound queue.

Runtime infrastructure Profiles are Provider-owned versioned documents. Workspace Runtime Profiles bind one infrastructure Profile and carry a versioned restrictive policy. An Agent selects one exact Workspace Runtime Profile. `shell_enabled` is currently an Agent boolean that gates several Agent Runtime Toolkit capabilities, while the confirmed Requirements remove that setting and establish an independent browser Terminal policy across Provider infrastructure Profile, Workspace Runtime Profile, and Agent settings.

The Main Web already has Chat and Runtime Workspace surfaces, desktop resize behavior, mobile drawer behavior, short-lived WebSocket ticket issuance, and Docker Runtime E2E coverage. It does not have a Terminal protocol, Terminal state model, PTY renderer, Terminal policy projection, or Terminal E2E.

## Fixed and Derived Outcomes

The confirmed Requirements and current project constraints determine the following outcomes and they are not reopened as ADR choices:

- A live Terminal belongs to one Chat Session and one user attachment, while its Runtime and Agent Workspace belong to the Agent.
- The initial release permits one active Terminal per Chat Session, but Terminal identity remains independently addressable for later multiple-Terminal support.
- A stopped Runtime requires explicit user Start.
- The Terminal begins in the authoritative Session working folder derived from current Runner-reported Agent Workspace evidence.
- Browser disconnect or page reload has a bounded same-user, same-Session reattachment window.
- Runtime stop, restart, desired-generation change, Runner reconnect, reattachment expiry, explicit termination, policy revocation, and access revocation terminate the PTY.
- Runtime lifecycle actions have priority over Terminal attachment, backpressure, grace, and cleanup and cannot be blocked by them.
- Runtime-free Agents expose no Terminal authority or UI.
- Terminal bytes and screen contents are not durable product data. Durable records are content-free metadata only.
- Terminal policy is independent from Agent Runtime Toolkit authority and is restrictive across Provider infrastructure Profile, Workspace Runtime Profile, and Agent settings.
- Existing and new policy sources allow Terminal by default; any upper or lower deny makes effective permission false.
- Existing Chat Session and Agent access control authorizes use; there is no separate per-user Terminal ACL.
- `shell_enabled` is removed without mapping its historical value into Terminal policy and without a legacy compatibility mode.
- Redis-backed and in-memory coordination implementations must have equivalent Terminal semantics. Redis loss may terminate ephemeral Terminals but must not affect durable Runtime or Workspace correctness.
- The shared protocol must not prevent a future non-Linux Runner backend even if current Linux Runtime Providers use a POSIX PTY first.

## Decisions

### terminal-260901/ADR-D1: Use a dedicated resource-bound Terminal WebSocket contract

**Affected requirements:** `terminal-260901/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-6`, `REQ-7`, `REQ-9`, `REQ-10`

Browser Terminal traffic uses a dedicated Public API WebSocket contract rather than extending the Chat WebSocket. An authenticated HTTP request issues a short-lived Terminal ticket bound to the requesting user and authentication Session, Workspace, Agent, Chat Session, and permitted Terminal open or attach intent. Possession of the ticket does not replace authorization: the WebSocket endpoint revalidates current Chat Session and Agent access, managed Runtime capability, effective Terminal policy, current Runtime and Runner generation authority, and Session working-folder authority before accepting Terminal traffic.

The protocol separates PTY bytes from control messages. Terminal input and output use bounded binary frames. Open acknowledgement, attach state, resize, output acknowledgement, heartbeat, termination, exit, revocation, and protocol errors use a closed typed control contract. Frame size, byte rate, connection lifetime, heartbeat, and slow-consumer limits belong to the Terminal endpoint and do not change Chat delivery limits.

Long-lived connections revalidate current authorization within the bounded revocation interval required by `terminal-260901/REQ-7`. Policy denial, user access loss, stale Runtime generation, or stale Runner authority closes the WebSocket and terminates the affected PTY through the Terminal lifecycle authority. A brief browser disconnect or page reload follows the separately decided Terminal attachment and replay lifecycle rather than the Chat subscription resync protocol.

The existing Chat WebSocket remains JSON-only and retains its current history/live subscription acknowledgement, health check, buffering, and reconnect behavior. Runtime-free Chat Sessions do not initialize or carry Terminal protocol state.

**Rejected:** Multiplexing Terminal binary traffic into the Chat WebSocket would combine unrelated flow-control, timeout, reconnect, resync, authorization, and failure boundaries. Large or slow Terminal output could delay Chat delivery, Runtime-free Chat would inherit unused Terminal complexity, and Terminal revocation or protocol failure could unnecessarily disrupt the canonical Chat live subscription.

### terminal-260901/ADR-D2: Use one dedicated bidirectional Runner stream per active Terminal

**Affected requirements:** `terminal-260901/REQ-1`, `REQ-4`, `REQ-5`, `REQ-7`, `REQ-9`

Terminal open and termination admission remain bounded metadata intents on the existing authenticated Runner Control stream. After an open intent is admitted, the Runner opens one dedicated outbound bidirectional Terminal gRPC stream for that active Terminal through the existing Runtime Control endpoint and Runner credential/TLS trust boundary. The stream registers the exact Runtime, current Runner connection generation, and independently addressable Terminal identity before carrying bytes.

Each active Terminal owns its own gRPC stream and therefore receives independent HTTP/2 stream flow control, cancellation, reconnect, and failure isolation. Terminal input, output, resize, acknowledgement, heartbeat, exit, and transport status cannot occupy the Runner Control stream queue or delay heartbeat, operation admission, operation cancellation, transfer intent, system metrics, or configuration evidence.

A Terminal data stream may reconnect within a bounded transport grace while the same Runner Control connection generation remains current and the Terminal lifecycle authority still permits attachment. The Runner retains the PTY during that bounded data-stream recovery. A stale Terminal stream cannot resume after a newer stream generation has attached. Closing or replacing the Runner Control stream changes Runner authority and terminates every PTY owned by the previous generation as required by `terminal-260901/REQ-4`.

The Runner may share one independently pooled gRPC channel across Terminal RPCs, but each active Terminal remains a separate RPC stream. Runtime-wide and per-user Terminal admission limits bound the number of active streams. This model supports later multiple named Terminals without changing the transport ownership boundary.

**Rejected:** Sending PTY bytes through the current Runner Control stream would retain head-of-line coupling with authoritative control traffic even if application-level priority queues were added. One multiplexed Terminal stream per Runner generation would isolate Terminal from Control but would make every Terminal share one stream-level failure and flow-control window, requiring a fairness scheduler to prevent one slow Terminal from blocking the others.

### terminal-260901/ADR-D3: Use one fenced attachment, lossless live delivery, and a bounded replay tail

**Affected requirements:** `terminal-260901/REQ-1`, `REQ-4`, `REQ-5`, `REQ-7`, `REQ-9`, `REQ-10`

Each live Terminal has one generation-fenced browser attachment lease. Only the current attachment generation may send input, resize, acknowledge output, request termination, or extend attachment liveness. An authenticated same-user, same-Session attachment atomically supersedes an older attachment so page reload does not wait for a stale socket timeout. Superseded sockets lose mutation authority immediately but do not terminate the PTY.

Live attached output uses monotonically ordered sequence and acknowledgement semantics. Bounded queues preserve lossless delivery while the attachment is healthy. When the browser does not acknowledge output quickly enough, the server applies bounded backpressure rather than silently dropping unconsumed live bytes. A continuing slow consumer loses its attachment and enters the normal browser reattachment grace period; grace expiry terminates the PTY.

Terminal coordination retains a bounded volatile output tail independently from live delivery acknowledgement. On reattachment, the browser resets its terminal emulator and replays the retained tail before accepting new interactive input. If earlier output has been trimmed, the protocol sends an explicit replay-truncated state and never claims that the reconstructed screen or scrollback is complete. Terminal input, output, and emulator state remain non-durable.

Redis-backed coordination uses atomic generation fencing, bounded queue/ring operations, blocking reads, and expiry. The in-memory implementation provides equivalent observable semantics with process-local synchronization. Redis loss may terminate live Terminals but cannot affect durable Runtime or Agent Workspace correctness.

**Rejected:** Letting the PTY continue while dropping unconsumed live output can hide prompts, errors, and command results from the user. Maintaining a server-side ANSI/VT screen emulator would duplicate xterm.js behavior, create two potentially divergent interpretations of terminal control sequences, and add a stateful compatibility boundary solely to reconstruct old screen contents.

### terminal-260901/ADR-D4: Use first-class Profile and Agent settings with live control-plane composition

**Affected requirements:** `terminal-260901/REQ-1`, `REQ-2`, `REQ-6`, `REQ-7`, `REQ-8`

Provider infrastructure Profiles, Workspace Runtime Profiles, and Agents each store a first-class `terminal_enabled` setting alongside their existing row-owned settings rather than embedding Terminal policy in Provider-specific infrastructure `spec` or Workspace physical Runtime `policy` documents. Existing and new rows default to enabled.

Effective Terminal permission is the logical AND of the current selected Provider infrastructure Profile, current Workspace Runtime Profile, and Agent setting. The current Agent must also have managed Runtime capability and an available selected Profile chain. Missing, cleared, disabled, deleted, cross-boundary, or otherwise unavailable current Profile authority fails closed. Historical applied Runtime configuration never restores Terminal permission after current authority is lost.

Profile and Agent APIs expose their owned raw setting where the caller may manage it. Session and Terminal projections expose a server-authored effective availability and bounded denial scope or reason. Browsers never reconstruct hierarchy from raw Provider, Profile, Runtime, or Agent state.

Terminal policy is a live control-plane access boundary. A committed deny immediately blocks open and reattachment and initiates bounded revocation of affected active Terminals. Terminal-only changes do not enter Provider-applied physical Runtime configuration, do not require Provider or Runner Profile contract support, and do not recreate or restart a Runtime. Profile optimistic versions still fence concurrent management, while physical configuration digests remain scoped to physical Runtime intent.

**Rejected:** Adding Terminal permission to every typed infrastructure `spec` and Workspace physical `policy` version would couple browser access control to Provider compatibility, desired/applied configuration, and Runtime reconciliation. A separate Terminal Policy resource would add another ownership, lifecycle, deletion, permission, and source-of-truth hierarchy despite the requester explicitly placing the setting on the existing three resources.

### terminal-260901/ADR-D5: Use a bounded interactive-work lifecycle with complete session cleanup

**Affected requirements:** `terminal-260901/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-7`, `REQ-9`, `REQ-10`, `REQ-11`

The initial Linux PTY backend launches an interactive Bash login shell in the authoritative Session working folder with `TERM=xterm-256color` and a UTF-8 environment. The shared execution contract requests a logical interactive shell and remains operating-system-neutral; a future backend may select a different native shell while preserving the same lifecycle and byte protocol.

A browser or Terminal data-stream disconnect starts a two-minute reattachment grace while Runtime and Runner generation authority remain current. An attached client that fails to acknowledge output for 30 seconds loses its attachment and enters the same grace. A Terminal with neither input nor output activity for 30 minutes terminates. Every Terminal has an eight-hour maximum lifetime regardless of activity.

The initial product limit remains one active Terminal per Chat Session. Admission additionally allows at most eight active Terminals per user and sixteen per Agent Runtime. These limits cover current multiple-Session use and bound the future multiple named Terminal extension. Exact frame, input queue, unacknowledged output, and replay-tail byte limits are conservative code-owned Design values within the accepted lossless/backpressure and bounded-memory policy; they do not create another product configuration hierarchy.

Explicit termination, shell exit, reattachment expiry, idle expiry, maximum lifetime, policy or access revocation, and Runner generation loss finalize the Terminal. On Linux, PTY cleanup targets the complete POSIX session rather than only the shell process group because interactive job control may place foreground and background jobs in separate process groups. The backend enumerates and signals all remaining session process groups, allows two seconds for TERM, escalates remaining processes to KILL for two seconds, and records content-free cleanup outcome metadata.

Runtime lifecycle authority is strictly higher priority than Terminal lifecycle. Runtime stop, restart, reset, recreation, repair, and permanent removal invalidate affected Terminals and continue without waiting for attachment acknowledgement, replay drainage, backpressure release, grace expiry, or successful PTY cleanup. Cleanup is bounded best-effort relative to the Runtime transition; generation fencing rejects every late Terminal frame or cleanup mutation after authority changes.

**Rejected:** Reusing the existing two-hour managed-process maximum would interrupt ordinary long interactive work while adding little protection beyond the accepted idle and quota controls. Removing idle expiry and retaining Terminals for 24 hours would let abandoned shells and background jobs consume shared Runtime resources for too long. Killing only the shell process group is incomplete for interactive job-control workloads and was disproven by a PTY cleanup probe.

### terminal-260901/ADR-D6: Use an additive stacked rollout followed by complete `shell_enabled` removal

**Affected requirements:** `terminal-260901/REQ-1`, `REQ-2`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`, `REQ-10`, `REQ-11`

Delivery uses a stacked sequence whose intermediate commits are buildable and fail closed, while the final architecture contains no legacy `shell_enabled` mode.

1. Add the PTY backend, typed Terminal gRPC protocol/service, and Runner `terminal.v1` capability without a user-visible Terminal surface.
2. Add the three first-class default-enabled Terminal policy fields, live effective-policy resolver, volatile coordination contract, Terminal service, and dedicated Public API WebSocket backend while temporarily retaining the existing `shell_enabled` contract.
3. Regenerate API clients and add the xterm.js Main Web experience. Terminal affordances and admission require the current Runner generation to advertise `terminal.v1`.
4. Remove `shell_enabled` from Agent persistence, Runtime capability resolution, Worker Toolkit binding, API schemas, generated clients, Web forms and summaries, seeds, tests, and Runtime transition/removal behavior. A new generated Alembic revision drops the current column after all active source stops reading it.
5. Complete E2E coverage, Living Spec synchronization, removal verification, temporary visual-review harness cleanup, and final design implementation evidence.

Mixed-version behavior is fail closed. A new Server with an old Runner projects Terminal unavailable with a bounded `runner_terminal_unsupported` reason and never sends a Terminal open intent. A new Runner connected to an old Server only advertises an unused capability and never opens a Terminal stream without an admitted control intent. Provider processes need no Terminal policy support because D4 keeps policy in Azents control-plane state. Public API and generated Web client changes move together within their stack phase.

Existing stored Provider Profiles, Workspace Profiles, and managed Agents receive `terminal_enabled=true` through new migrations. No historical `shell_enabled` value is copied. Historical executed migrations remain unchanged. Temporary coexistence across the stacked delivery is a rollout property only; the final code, database schema, OpenAPI contract, generated clients, Web, Specs, tests, and fixtures contain no deprecated field, fallback, or dual-resolution branch.

The complete planned PR stack is created before CI monitoring begins. Each PR targets the previous stack branch, includes its generated and verification surfaces, and remains independently reviewable. PR merging remains outside this decision and requires separate explicit requester approval.

**Rejected:** One atomic cross-system PR would couple protocol, database, backend, Web, and E2E failures into one review boundary. Keeping a deprecated `shell_enabled` fallback would create two Runtime authority models, contradict the confirmed removal requirement, and make later cleanup another migration and product-contract change.
