---
title: "GitHub Authorization-Before-Create Decision"
created: 2026-10-09
document_role: primary
document_type: adr
snapshot_id: github-261009
tags: [github, toolkit, oauth, security]
---

# GitHub Authorization-Before-Create Decision

Authority: [github-261009/REQ](../requirements/github-261009-authorization-journey.md), confirmed by the requester on 2026-10-09.

## ADR-D1. Publish a new user-account Toolkit only with its confirmed authorization

Accepted by the requester on 2026-10-09 in the explicit UI/API implementation brief. Applies to REQ-1..3.

Retain the submitted configuration/registration only in a bounded encrypted authorization attempt, not in a published ToolkitConfig. Provider exchange verifies and stages the account. Explicit account/sharing confirmation atomically creates the Toolkit, its namespace when Agent-owned, and its current account connection. User-account creation through ordinary shared/Agent Toolkit APIs is rejected with actionable guidance. PAT and installation modes retain their creation contracts.

Rejected: saving an unauthenticated disabled/draft Toolkit first and only delaying UI completion. That would retain the unusable saved item the requester asked to remove and permit API bypass. Browser-persisted credentials, provider network I/O inside the create transaction, and automatic account/sharing confirmation are also excluded.

The new attempt retains existing exact manager/Auth Session/Workspace/Agent/App/callback binding, ten-minute expiry, one-use exchange and bounded fail-open candidate token cleanup. Local cancellation/failure removes pending creation, not a preexisting Toolkit. No cleanup actor, retry state, token refresh or credential fallback is added. Abandoned encrypted attempts are not Toolkit discovery/execution authority; expiry bars completion. Known token cleanup has the existing bounded best-effort limitations.

## ADR-D2. Restore confirmation automatically in the authorization browser context

Derived from the requester's explicit automatic-return instruction, REQ-1 and unchanged explicit-sharing authority. The callback replaces its URL with the exact originating Toolkit surface and restores only the server-reviewed attempt identity from scoped session storage. It does not require the user to find the opener tab or grant credentials through a popup message. Codes, nonce/state, secrets and tokens are excluded from return URLs and persisted browser state. Existing same-origin/exact-window notification can assist the opener but is not the only completion path.

Unchanged saved connections remain the source of edit authorization; blank write-only fields and Platform source discriminators are not reauthorization requests. Source labels use the same localized name across both execution authorities and details (REQ-3/4).
