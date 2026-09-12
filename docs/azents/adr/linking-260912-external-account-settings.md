---
title: "External Account Linking and Conversation Settings Decisions"
created: 2026-09-12
tags: [external-channel, security, architecture]
document_role: primary
document_type: adr
snapshot_id: linking-260912
---

# External Account Linking and Conversation Settings Decisions

- Snapshot: `linking-260912`
- Authority: [linking-260912/REQ](../requirements/linking-260912-external-account-settings.md)
- Mode: Autonomous; a dedicated technical interviewee owns material technical decisions under the requester's delegation.

## System Framing

Existing provider principals authorize guest admission and native response/location settings independently from Azents users. Canonical Team Session execution remains separate. The current model-profile write path locks the root Session, checks Workspace membership and ownership where applicable, validates Agent options, and persists idempotent shared intent. Slack settings use private modals; Discord settings use authenticated ephemeral interactions. Existing auth elevation and database-backed login sessions can prove the current Azents user.

## Material Decision Map

- T1: Two-sided identity proof using verified provider interactions or end-user provider OAuth.
- T2: Durable Workspace link/challenge lifecycle, identity cardinality, and concurrency boundaries.
- T3: Same-target model-write authority, stale-screen detection, and revocation fencing.
- T4: Private provider UI, shared notification, and audit ownership/failure boundaries.

Requirements fix guest preservation, optional linking, native private-only personalization, same-web rights, unique Workspace links, explicit shared application, conflict recovery, and minimal common notices. Identifiers, file layout, helper decomposition, and equivalent fixture composition remain local implementation details. No product question is delegated as a technical choice.

## Decisions

### D1. Prove both accounts through an immutable browser-code rendezvous

- Authority: linking-260912/REQ-2, REQ-3, REQ-4, REQ-11.
- Accepted: 2026-09-12 by the delegated technical interviewee.

Use the existing authenticated provider interactions rather than adding end-user OAuth credentials. A native private action creates an expiring origin challenge bound to the initiating human principal, Workspace, connection, and configuration generation. Its URL is a locator, not identity proof. An elevated web user creates an immutable candidate bound to their User and current auth Session. Generate a cryptographically random 128-bit code, return it once to that browser, and persist only its hash. Concurrent browser candidates remain independent; there is no mutable latest-candidate pointer.

The user pastes that browser code into the original provider's private modal. The signed submission must prove the original principal and exact origin scope, locate the matching candidate, and verify expiry and live connection generation. The candidate-owning web User and same elevated auth Session must then explicitly confirm the displayed account pair and Workspace. Final current-account, membership, connection, uniqueness, and consumed-state validation commits atomically with the link.

Changing browser account or auth Session requires a fresh candidate. A consumed, cancelled, expired, or mismatched flow cannot be rebound or reactivated. Code and credential values never enter URLs, logs, durable provider projections, or public messages. Expiry and failed attempts are bounded. The provider proof surface need not display the candidate's private Azents identity.

**Rejected alternative:** End-user provider OAuth with state/PKCE and verified provider identity is viable, but adds customer-App credentials, scopes, configuration, and operational failure paths that the existing signed-interaction protocol does not require.

**Risks:** Copying a code adds a user step; instructions must identify the original account and prohibit entering a code supplied by another person. Provider/private-screen expiry is recoverable by restarting rather than silently weakening proof. A forwarded locator alone cannot select or confirm another browser's candidate.

### D2. Own links at the Workspace boundary, independently of guest principals

- Authority: linking-260912/REQ-1, REQ-2, REQ-3, REQ-9; ADR-D1.
- Accepted: 2026-09-12 by the delegated technical interviewee.

Use separate Workspace link, origin challenge, and immutable browser candidate records. A link key consists of Workspace, provider, identity scope, and external user ID. Discord uses a global provider identity scope; Slack uses the Slack team ID. Preserve existing guild-scoped Discord principals and all principal-scoped grants unchanged. Partial unique indexes enforce one active owner per external identity and one active external identity per User/provider/scope in a Workspace.

Disconnection marks the link terminal. Retain the row for audit and create a new row after fresh proof on relink. Workspace link lifetime is independent of the connection that first proved it; each new proof or edit requires its own current valid connection. A user's own management list remains readable after membership loss, projecting the link as inactive. Unlink requires the elevated authenticated owner and never modifies guest state.

Origins and their candidates expire after ten minutes. Permit at most five immutable candidates and five invalid-code submissions per origin; validate the signed original actor and connection scope before consuming that failure budget. Finalization atomically consumes the origin and chosen candidate, invalidating all siblings. A bounded scheduled database cleanup removes expired challenge/candidate records after 24 hours. Link/proof correctness never depends on Redis or cleanup timing.

Finalization and future edits lock or fence live account, auth Session where applicable, membership, connection, and link authority against their revocation paths. A current unlocked read alone is insufficient concurrency evidence. Retained audit references the exact historical link row, not whichever link is now active.

**Rejected viable alternative:** A normalized global identity registry with separate Workspace associations adds a global ownership layer without a required current outcome. Keep canonical identity normalization local to Workspace link keys.

**Rejected incompatible alternative:** Adding mutable Azents ownership to existing principals or merging Discord guild principals would change existing guest authorization and cannot satisfy REQ-1.

**Risks:** Terminal link audit adds retained metadata. Lifecycle cleanup must respect existing User/Workspace deletion boundaries without restoring links or cascading away unrelated external roots.

### D3. Share canonical model authority and fence native drafts with a generation

- Authority: linking-260912/REQ-1, REQ-6, REQ-7, REQ-8; ADR-D2.
- Accepted: 2026-09-12 by the delegated technical interviewee.

Extract the existing web model-profile replacement into repository-owned transaction composition and reuse its exact root Session, active Agent, Workspace membership, User-Session ownership, and selectable-option validation. Native settings add live linked-user, exact provider principal/connection/resource/binding, and external grant/block checks. Keep existing web request and idempotent replay semantics unchanged.

Add an applied-profile generation to AgentSession and increment it atomically in the common `set_applied_inference_profile` setter for every existing caller: explicit web replacement, composer/input admission, edited input, and subagent initialization. A native draft carries the generation observed on opening. Check that generation and replace the profile in the same Session-locked transaction. Matching web idempotent replay does not invoke the setter or increment generation. Any accepted replacement, including equal values, conservatively invalidates older native drafts. Draft selection is private state until explicit Apply.

Use nonblocking acquisition for every potentially conflicting lock in the new native operation. Retry the entire database-only transaction on lock contention/deadlock within a bounded budget; exhaustion is an explicit retryable failure with no save or success notice. Existing lifecycle paths do not share one global lock order. Do not hold a scope lock while blocking on Session, Agent, User, membership, link, or authorization-fence locks. A transaction advisory fence uses its try variant; row fences use NOWAIT.

The native authorization check and all relevant block-insert/grant-revoke writers share a narrow principal/Agent authorization fence, including the absent-block case. User disable, membership deletion, link revocation, and connection/binding lifecycle writes must conflict with the actual rows locked by native commit. No provider or other external I/O occurs inside transactions or retry loops.

**Rejected viable alternative:** Comparing only the previous profile tuple avoids a generation column but misses change-away-and-back (ABA) conflicts.

**Rejected incompatible alternative:** A native-only model overlay would violate the required shared Session setting and web parity.

**Verification obligations:** Exercise ABA, all setter callers, concurrent block insertion and grant revocation, unlink/member-loss/user-disable races, reverse-order archive contention, and exhausted retries using real database synchronization. Migration initializes the new generation without altering existing profile values.

### D4. Keep private drafts and external mutation audit separate from public delivery

- Authority: linking-260912/REQ-4, REQ-5, REQ-7, REQ-8, REQ-9, REQ-10, REQ-11; ADR-D1 through ADR-D3.
- Accepted: 2026-09-12 by the delegated technical interviewee.

Use a dedicated external model mutation record rather than extending REST ChatWriteRequest with provider audit. Atomically record the exact principal, historical link and User, Binding and Session, old/new profile, generation, timestamp, collision-free provider/connection/interaction idempotency key, and preclaimed unknown notice outcome with the model change. Validate actor and target authority before returning a replayed result.

The first committed mutation returns one process-local public notice plan. Send it once after commit through the existing Slack or Discord SDK adapter and record delivered, failed, or unknown outcome. Replays never repeat ambiguous delivery. Construct the notice from committed values and the safely rendered external identity, selected label/effort/options, and effective timing. Do not include Azents identity, private roles, or the available-options catalog. Provider failure does not roll back the save; reopening shows current applied state.

Keep the common settings entry unchanged and resolve personalization only in the native private surface. Unlinked users see a small persistent optional invitation. Blocked or unauthorized participants receive only their own linking/management controls without calling conversation resolution or disclosing its details. Guest controls and the added model editor apply independently. Typed draft state belongs to the exact actor and interaction, with bounded size and expiry; provider-limit handling remains private and must not truncate available authorized choices silently. No unsupported-provider or failed-private-delivery fallback exists.

Web routes serve only identity confirmation and personal link management, not provider-personalized conversation settings. Mutation records follow existing Session purge retention; unlink cannot cascade-delete them. Historical link identity remains immutable.

**Rejected viable alternative:** A durable notification outbox adds workers, retry and duplicate-recovery behavior without a required eventual-delivery outcome. The specified saved-versus-notified distinction is satisfied by one bounded post-commit attempt.

**Risks:** A process failure between save and notice may leave an unknown delivery outcome. The actor can reopen settings to inspect actual state; the system does not pretend that an unobserved message was delivered.
