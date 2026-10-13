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
- Mode: Collaborative; the requester owns unresolved material decisions.
- This is the initial decision map, not an accepted decision log. No pending
  recommendation below authorizes implementation.

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
| D1: operator registration binding and rotation | Material technical decision; requester | Current, pending | Secret retention, existing-grant eligibility, and replacement failure behavior |
| D2: account/grant relationship | Product boundary first; requester | Pending | Whether one connection can show different service accounts; subsequent grant cardinality |
| D3: saved reconnect replacement | Product recovery boundary followed by technical decision; requester | Pending | What continues executing during reconnect and how reduced/account-changed results replace saved authority |
| D4: provider-policy screening | Material security/operational decision; requester | Pending | Additional data processor, failure behavior, deployment prerequisite, and risk disclosure |

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
