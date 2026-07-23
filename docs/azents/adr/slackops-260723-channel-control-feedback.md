---
title: "Slack Channel Control Feedback"
created: 2026-07-23
tags: [slack, external-channel, frontend, authorization, architecture]
document_role: primary
document_type: adr
snapshot_id: slackops-260723
---

# Slack Channel Control Feedback

- Snapshot: `slackops-260723`
- Requirements: [`slackops-260723/REQ`](../requirements/slackops-260723-channel-control-feedback.md)

## Context

The first readable Slack message implementation relies on Slack fallback `text`,
abbreviates provider IDs, infers progress drift from unrelated revision counters,
and retains approval control messages after a decision. Grant revocation also keeps
a soft-revoked policy row even though the requested product behavior is removal.

## Decisions

### slackops-260723/ADR-D1. Normalize supported Slack blocks into bounded canonical text

**Affects:** `slackops-260723/REQ-1`

When usable fallback text is absent, derive normalized message text from a bounded
allowlist of Slack text, rich-text, reference, link, emoji, and date elements.
HTTP admission stores only bounded block type and normalized-text projections.
Revision identity uses the resulting normalized body.

**Rejected:** Persisting arbitrary Block Kit JSON would expand the untrusted
provider surface and expose interactive payload details that Azents does not use.
Discarding blocks leaves legitimate Slack messages unreadable.

### slackops-260723/ADR-D2. Reuse the durable delivery ledger for approval deletion

**Affects:** `slackops-260723/REQ-4`

Each final access decision creates an idempotent access-request-origin
`progress_delete` delivery intent when the original control message has a confirmed
provider identity. The intent commits with the decision. The existing provider
delete adapter attempts it after commit and records delivered, failed, or unknown.

**Rejected:** Calling Slack inside the decision transaction could roll back durable
authorization after a provider failure. A separate retry queue would violate the
current at-most-once provider mutation contract.

### slackops-260723/ADR-D3. Derive Activity Tracker presentation from delivery state

**Affects:** `slackops-260723/REQ-3`

Expose a bounded projection-state label derived from the latest durable progress
delivery and the retained provider message identity. Render the canonical ordered
task snapshot directly. Do not compare state and desired-progress revision numbers
as if they were the same sequence.

**Rejected:** Aligning unrelated counters would change their existing persistence
meaning and still would not identify failed or ambiguous provider mutations.

### slackops-260723/ADR-D4. Hard-delete revoked participant grants

**Affects:** `slackops-260723/REQ-5`

Grant revocation locks and deletes the selected grant row. Provider messages,
invocation batches, and projected Session events remain unchanged.

**Rejected:** Retaining a soft-revoked grant does not match the requested removal
contract and complicates repeated grant creation without providing a user-visible
audit surface.

### slackops-260723/ADR-D5. Keep full identifiers in administrative detail surfaces

**Affects:** `slackops-260723/REQ-2`, `slackops-260723/REQ-6`

Regular timeline summaries continue to prioritize names. Detail and approval
surfaces show complete IDs, wrap long values, and provide copy controls.

**Rejected:** Abbreviation loses traceability. Showing full identifiers in every
summary would reintroduce the scanning problem addressed by the earlier snapshot.
