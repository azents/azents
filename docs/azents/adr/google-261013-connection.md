---
title: "Google Connection Architecture Decisions"
created: 2026-10-13
document_role: primary
document_type: adr
snapshot_id: google-261013
tags: [google, toolkit, oauth, architecture, security]
---

# Google Connection Architecture Decisions

- Snapshot: `google-261013`
- Reference: `google-261013/ADR`
- Requirements: [google-261013/REQ](../requirements/google-261013-connection.md).
- Mode: Autonomous after the requester's instruction to implement without further
  questions on 2026-10-13. Dedicated technical decision owner:
  `/root/google-design-owner`.
- The initial proposals remain context. Accepted outcomes are appended below;
  unaccepted proposals do not authorize implementation.

## Fixed Direction

These outcomes are already constrained, not new approval questions:

- Connect Calendar, Drive, and Gmail through Google's official remote MCP servers.
- Retain existing Toolkit ownership, shared-account execution authority, namespace
  allocation, and Runtime-free remote execution.
- Use existing MCP communication and background discovery facilities; do not turn
  the generic single-server MCP configuration into arbitrary multi-server support.
  Provider-specific composition exists for GitHub and GCP.
- Requested permissions, proved grants, selected tasks, discovered tools, and
  current execution authority are separate inputs. Discovery is not grant evidence.
- Unpublished authorization cannot execute. Explicit final review is necessary
  before publication; partial consent can produce a reduced usable result.
- Later authorization changes use ordinary reconnect. There is no task-specific
  consent workflow, automatic replay, relay, or Runtime credential injection.

Sources: REQ-1, REQ-3 through REQ-8, fixed constraints, and retained
[Toolkit](../spec/domain/toolkit.md) and [MCP OAuth](../spec/flow/mcp-oauth.md)
contracts. These derived boundaries do not approve the pending mechanisms below.

## Decision Map

| Topic | Kind and owner | State | Consequence |
| --- | --- | --- | --- |
| D1: operator registration binding and rotation | Material technical decision; delegated owner | Accepted; see appended ADR-D1 | Secret retention, existing-grant eligibility, and replacement failure behavior |
| D2: account/grant relationship | Bounded implementation choice; delegated owner | Accepted; see appended ADR-D2 | One actual account across selected service capability projections |
| D3: saved reconnect replacement | Material recovery decision; delegated owner | Accepted; see appended ADR-D3 | Staged candidate, current grant retained until reviewed atomic replacement |
| D4: provider-policy screening | Material security/operational decision; delegated owner | Accepted; see appended ADR-D4 | Local bounded screening and explicit residual-risk acknowledgement |

Encrypted local credentials, exact callback ownership, one-use attempt consumption,
atomic publication, current-state checks, and stale-response rejection are fixed
obligations. Equivalent table/helper layout and fixture composition are agent-owned.
They do not create another credential authority or change the decisions above.

## D1. Operator Registration Binding and Rotation

**State:** Pending. Recommendation only; no accepted `google-261013/ADR-D1`.

**Question:** Should existing Google grants resolve the current operator
registration for the same client, or retain connection-bound client credentials?

### Current Behavior and Gap

Generic MCP stores registration with its single Toolkit OAuth row. Platform GitHub
resolves current encrypted System Settings with application-identity checks.
[System Settings](../spec/domain/system-settings.md) already supplies typed
configuration, write-only secrets, environment ownership, redacted projections,
and effective-generation fencing. None of these facts selects Google's binding.

Google tokens belong to a particular OAuth client. Updating a secret for the same
client is different from replacing that client. A new client must not be paired
silently with an old client's refresh token.

### Viable Options

1. **Current operator registration reference.** Store the client binding with the
   grant; resolve the current same-client secret when renewing. One secret rotation
   affects existing connections. Client replacement makes mismatched grants
   ineligible until reconnect. Do not retain a retired secret as fallback.
2. **Connection-bound credentials.** Keep the client credentials used at consent
   encrypted alongside that grant. Operator changes apply to new connections.
   Existing connections continue using old credentials until explicit retirement
   or reconnect; old-secret retention and retirement become operating obligations.

**Recommendation:** Option 1. It keeps one operator secret authority and avoids
indefinite copies of retired secrets. In-flight callbacks/refreshes must check the
effective configuration again before committing; stale results cannot win.

**Remaining product context:** Where the operator prepares the registration and
whether another registration can be supplied are not silently determined by this
technical recommendation. The draft does not add a manager-owned application mode.

**Affected requirements:** REQ-2, REQ-4, REQ-7, REQ-8.

## D2. Account and Grant Relationship

**State:** Pending product clarification, then evidence-constrained technical
decision. No accepted `google-261013/ADR-D2`.

REQ-1 promises one Google setup surface but explicitly does not promise shared
account identity or one consent operation. The draft therefore must not equate
UI grouping with a single account/grant row.

The product alternatives are one connected Google account for the whole Toolkit,
or separately reviewed service accounts within the unified connection. The latter
requires a per-service identity projection; it is not a storage-only change.
The recommendation is one account per connection for a comprehensible shared
execution identity, but that recommendation is not confirmed intent.

Given the chosen account relation, validate whether one Google authorization grant
can be used at all selected official endpoints. Public discovery establishes a
common authorization server, not token interoperability. Distinct endpoint grants
may be necessary if live evidence requires them; they cannot create an unapproved
account model. Do not implement both alternatives as selectable modes.

**Affected requirements:** REQ-1, REQ-4, REQ-6, REQ-8.

## D3. Saved Reconnect Replacement

**State:** Pending recovery boundary and material technical choice. No accepted
`google-261013/ADR-D3`.

Initial creation already requires explicit review and atomic publication. Current
generic MCP reconnect can update stored state before consent completes; copying
that behavior would not automatically satisfy Google's truthful verification
and recovery requirements.

Two viable outcomes differ materially:

1. **Staged replacement.** Keep the current saved grant while an unpublished
   replacement is authorized and reviewed. Replace only on explicit confirmation,
   comparing the exact saved state. Cancel abandons the candidate, not the saved
   grant. Provider-proved revocation can still make the old grant unusable.
2. **Suspended reconnect.** Make the saved grant ineligible when reconnect starts.
   Review/confirm restores a verified grant; cancel does not silently restore old
   eligibility. This avoids continued execution during reauthorization but creates
   a user-visible interruption.

**Recommendation:** Option 1, with exact publication/refresh comparison and a
truthful account/reduced-capability review. A changed subject never inherits old
permissions or refresh credentials. This recommendation needs recovery authority;
REQ-7 alone does not select what continues executing during reconnect.

Whether an already authorized outbound operation can be cancelled is bounded by
the provider: local cancel/disconnect cannot promise to reverse remote effects.
No option authorizes blind write replay or remote token revocation as cleanup.

**Affected requirements:** REQ-4, REQ-6, REQ-7, REQ-8.

## D4. Google MCP Security Policy

**State:** Pending security/operational choice and compliance evidence. No accepted
`google-261013/ADR-D4`.

Google's [MCP security guide](https://developers.google.com/workspace/guides/configure-mcp-security?hl=en)
requires scanning prompts and responses for malicious content or prompt injection.
It permits Model Armor or a documented own solution with user risk acceptance.
Treating content as untrusted is necessary but does not establish scanning.

The viable directions to evaluate are operator-configured Google Model Armor, or
a documented application-owned screening solution with credible coverage and
disclosure. Model Armor has processing-location, payload-log, and operating-cost
consequences. An own solution needs an actual scanner and verification; a warning
alone is not sufficient. Neither is selected. There is no approved paid service,
new relay, configurable scanner framework, or silent fail-open.

**Recommendation at this stage:** Keep the live-readiness claim conditional.
Evaluate coverage, input/output boundaries, data residency, logging, outages, and
accepted-risk disclosure before selecting a mechanism. Existing tool hooks are
possible enforcement points, not proof of an adequate security solution.

**Affected requirements:** REQ-2, REQ-8, fixed provider-policy constraints.

## Acceptance Recording

After the requester chooses a topic, append its accepted outcome, alternatives,
consequences, authority, and date as `google-261013/ADR-DN`. Pending proposals above
are retained as context. Do not turn an instruction to continue drafting into
blanket delegation, Requirements changes, or Design approval.

## Accepted google-261013/ADR-D1 — Current Operator Registration

- Accepted on: 2026-10-13.
- Decision owner: `/root/google-design-owner`, under the requester's instruction
  to implement without further questions.
- Authority: REQ-2, REQ-4, REQ-7, REQ-8 and optional-integration/compatibility/data
  preservation constraints; retained System Settings and detached MCP refresh.

Use one optional operator-owned Google OAuth registration in existing typed System
Settings. Keep client identity with each Google grant, but no connection-bound
copy of its client secret. Only existing System Admin authority manages settings;
public managers receive redacted preparation state. No manager-BYOA mode or new
secret authority is added.

Same-client secret rotation preserves client bindings and verified scopes. Future
credential operations resolve current configuration. An effective-generation
change during provider I/O defeats stale successes and failures; it cannot mark
current credentials rejected. No ambiguous external effect is automatically
replayed.

Client replacement makes mismatched grants ineligible for projection/execution and
requires ordinary reconnect. Never refresh an old token with the replacement
client. Preserve encrypted grant state; configuration replacement is not deletion
or Google revocation. Missing/incomplete configuration blocks Google credential
use with an operator-preparation reason, not fabricated user denial.

Callback claim, post-I/O finalization, publication and refresh compare current
registration and exact grant state. Provider I/O remains outside transactions.
Database state and effective configuration, not Redis/events, own correctness.

Rejected alternative: connection-bound old credentials create indefinite secret
copies and a retirement obligation without a requested need. Current reference
keeps one secret authority and practical same-client rotation.

Verification obligations: redaction, absent config, same-client rotation, changed
client ineligibility, rotation during exchange/refresh, stale failure rejection,
callback/publication races, data preservation, and unrelated-provider regression.

## Accepted google-261013/ADR-D2 — One Subject and Toolkit-Owned Grant

- Accepted on: 2026-10-13.
- Decision owner: `/root/google-design-owner`, under delegated implementation
  authority within the original account-authorization scenario.
- Authority: primary scenario, REQ-1, REQ-3 through REQ-6, REQ-8 and current
  ownership/non-goal constraints.

One Google Toolkit has one current verified Google subject and one Toolkit-owned
grant, routed to the three fixed official endpoints. Review displays that actual
account once and partitions usable/unavailable/unknown work by service/task.
Partial consent does not create separate service accounts or another consent flow.
Separate service accounts were an explored alternative, not a required capability.

Identity includes stable subject, trusted issuer, and exact client binding, using
supported verification with issuer/audience/expiry/nonce checks. Display email,
browser input and login hints are not evidence. A changed subject/client never
inherits scopes or renewal credentials. No grant pooling or token borrowing occurs
across Toolkits, even with identical subject/client.

Do not invent endpoint-specific audience/resource parameters. Public metadata
establishes a common authorization server but not authenticated token reuse.
Interoperability, tool-to-scope mapping, Preview and renewal remain conditional
until live evidence. If live evidence contradicts the single-grant contract,
report that blocker; do not silently introduce per-service accounts/grants,
multiple consent modes, direct API substitutes, or a relay.

Shared/Team execution continues using the connected account, not participant
identity. Review retains the shared-account warning.

Verification obligations: one identity across service projections; partial service
grants; subject/client isolation; independent Toolkit credentials; bad issuer/
audience/nonce; exact service routing and current execution authority.

## Accepted google-261013/ADR-D3 — Staged Reconnect Replacement

- Accepted on: 2026-10-13.
- Decision owner: `/root/google-design-owner`, under delegated implementation
  authority.
- Authority: REQ-4, REQ-6, REQ-7, REQ-8; ADR-D1/D2 and retained ownership,
  credential-preservation and detached-refresh contracts.

Ordinary reconnect stages an unpublished candidate against the exact saved
Toolkit and current connection identity. The saved grant stays eligible only
under current scopes, client binding and execution authority. Reconnect does not
restore revoked permission or suspend a still-valid saved grant.

Explicit review displays the new account and actual capabilities, including
reductions. Confirm atomically replaces the single current grant and relevant
selected configuration. Cancel, expiry, denial and verification failure discard
only the candidate. Local abandonment never promises reversal of Google consent,
revocation, or completed provider effects. Different subjects/clients never inherit
scopes or renewal credentials.

Capture exact ownership, current connection identity, permission/auth state,
authentication-affecting configuration and operator-generation fence. Compare
these in the final publication transaction. Different connection, disconnect,
changed ownership, grants/auth state or authentication configuration causes stale
conflict. Unrelated metadata is preserved. Routine access-token renewal retains
connection identity and does not alone stale an independently verified candidate.
Publication creates a new current connection identity, defeating old refresh CAS.
Sibling candidates cannot both replace the captured identity.

Persist the exact attempt/final-settings publication outcome atomically. Identical
confirm replay returns the outcome under current management authority; different
settings conflict. Outcome lookup after response loss never repeats provider I/O.
Cancel after publication cannot claim proven abandonment. Historical publication
success does not assert current readiness after replacement/disconnect and cannot
restore the old connection. These identities are internal concurrency fences,
not product version history.

Rejected alternative: suspend-at-start introduces unnecessary interruption and
changes cancellation recovery. No automatic task replay or remote revocation is
added to either creation or reconnect.

Verification obligations: partial/account-changed review, preserved local state,
same-attempt replay/settings mismatch, response loss, confirm/cancel races,
disconnect/refresh/publication races, sibling candidates, auth-config conflict,
routine refresh during reconnect, unrelated metadata preservation, and historical
outcome lookup without resurrection.

## Accepted google-261013/ADR-D4 — Google-Scoped Content Screening

- Accepted on: 2026-10-13.
- Decision owner: `/root/google-design-owner`, under delegated implementation
  authority.
- Authority: REQ-8, truthful final review under REQ-4/REQ-6, fixed provider-policy
  constraints.

Use a bounded application-owned deterministic scanner at the Google MCP boundary.
Screen remote schema text before persistence/exposure and re-screen cached
schemas; screen complete outgoing argument keys/nested values after current
authorization but before outbound I/O; screen complete incoming text/structured
results and embedded resource text before extraction or artifact publication.
Unsupported binary content is not passed through as scanned.

Traverse with explicit depth/node/string/total-content budgets. Unicode
normalization, casefolding, invisible/control handling and supported encoded-text
inspection are bounded inspection views, never silent rewriting. Over-budget,
unsupported, flagged or scanner-error content fails closed; do not approve a
truncated prefix. Detect a reviewed known-pattern corpus of overrides, role
spoofing, credential/prompt exfiltration and other-tool commandeering. Ordinary
links, imperatives and the word system alone are not malicious classification.
Add benign/false-positive fixtures. Keep compiled instructions separate from
remote text.

Diagnostics contain safe categories/counters/operation identity only, no contents,
excerpts, private-content hashes or secret-bearing URLs. Flagged arguments cause
no Google call. A blocked response may follow a completed provider effect: report
that uncertainty without publishing any original content/artifact or retrying.
Screening is not OAuth-revocation evidence.

Final review documents known-pattern coverage, novel/semantic/obfuscated and
multilingual gaps, false negatives, false positives and bounded-content rejection.
Require fresh explicit `security_risk_acknowledged=true` for exact creation and
reconnect confirmation; an old grant or browser default cannot approve a new
candidate. Persist minimal current-connection acknowledgement. This is part of
required final review, not another OAuth/additional-consent feature.

Rejected direction: enabling Model Armor introduces an unselected paid processor
and operational configuration; a warning without screening does not satisfy the
contract. No relay, generic scanner plugin, background model call, or bypass is
added.

Implementation and deterministic verification may proceed. This is not complete
prevention, detection-efficacy proof or Google certification. Authenticated
behavior and provider-policy compliance remain conditional; report any broader
provider-coverage requirement instead of manufacturing compliance.

Verification obligations: malicious and benign corpus at every boundary; nested
keys/values and supported encodings; Unicode/invisible handling; budget limits and
scanner exceptions; cached-schema quarantine; zero outbound calls on flagged
arguments; no artifacts or replay after flagged responses; fresh acknowledgement;
safe diagnostics; unchanged unrelated providers.

## ADR-D1 Refinement — Direct Local Activation

- Accepted on: 2026-10-13.
- Decision owner: `/root/google-design-owner`.
- Authority: ADR-D1 and REQ-2's distinction between declared preparation and
  verified results.

Use existing direct typed Section activation for `google_oauth`: local schema
validation, optimistic mutation, encryption, environment ownership, redacted
status and effective-generation fencing. Registration presence is preparation,
not a live client/Preview/API validation. Client replacement retains ADR-D1's
ineligibility and data-preservation consequences. No second confirmation mode,
retired-secret fallback or false remote-health claim is introduced.
