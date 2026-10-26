---
title: "Browser Continuity Across Control Reconnection Requirements"
created: 2026-10-27
tags: [browser, runtime, reliability, security]
document_role: primary
document_type: requirements
snapshot_id: browserlife-261027
---

# Browser Continuity Across Control Reconnection Requirements

- Snapshot: `browserlife-261027`
- Reference: `browserlife-261027/REQ`

## Problem

Control transport loss currently retires native browser resources even when the
Runner process survives. Transient connection failures can also be described as
resource replacement or account revocation.

## Primary System Outcome

A surviving Runner preserves its native browser across Control reconnection while
retiring the former connection's authority and uncertain work.

## Goals

- Preserve live tabs and page state without relaxing current access checks.
- Distinguish transport loss from actual access or target loss.

## Non-Goals

- Restoring live tabs after Runner process exit or native browser crash.
- Solving site challenges or guaranteeing third-party authentication validity.
- Changing shell, PTY, or managed-process reconnection policy.
- Adding browser daemons, profile migration, durable recovery stores or replay.

## Requirements

### REQ-1. Same-process continuity

With the same Runner process and browser intent, Control reconnection preserves
native contexts, tabs, page memory, site state, and surviving task/page identities.
It does not automatically reload or navigate the site.

### REQ-2. Former authority retirement

Former generation input, viewer sources/ACKs and observation references cannot
produce new effects after connection loss is detected. Fresh admission requires
successful cleanup and current registration/configuration evidence.

### REQ-3. Uncertain effects are not replayed

Interrupted input or submission is never automatically retried. Native dialogs
are not automatically answered by reconnection cleanup.

### REQ-4. Accurate recovery classification

Transport or connection epoch loss ends the attachment but is not account
revocation or proof of native target destruction. A surviving tab admits a fresh
attachment. Real access loss, expiry and target closure remain fail-closed.

### REQ-5. Destructive boundaries remain explicit

Runner exit, actual Runtime replacement and explicit browser engine transitions
retain their cleanup behavior. Profiles remain under existing persistence rules.
Browser capability disable retains its existing access-control semantics.

### REQ-6. Security and truthful diagnostics

Generation/access/Session isolation and confidential input remain enforced.
Connection errors do not claim physical Runtime recreation without evidence.
Browser content, input, cookies and credentials are not added to logs.

## Acceptance Criteria

- A minimal real Control-reconnect journey retains a native page memory canary and
  target identity, then accepts fresh authorized input.
- Deterministic lower-layer tests reject old generations, refs and attachments;
  cover pending work/configuration races and actual destructive boundaries.
- API, Owner and UI preserve access denial while allowing transient reattachment.

## Fixed Constraints

Use existing Runner transport, intent reconciliation and native profile ownership.
No new wire version, durable recovery table or automatic mutation retry.

## Confirmation

The requester confirmed the complete six-requirement proposal on 2026-10-27 and
authorized implementation, autonomous technical decisions and a PR with passing CI.
Merge and production deployment are outside this delivery request.
