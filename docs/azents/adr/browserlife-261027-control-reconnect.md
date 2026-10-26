---
title: "Browser Continuity Across Control Reconnection Decisions"
created: 2026-10-27
tags: [browser, runtime, security]
document_role: primary
document_type: adr
snapshot_id: browserlife-261027
---

# Browser Continuity Across Control Reconnection Decisions

Authority: [browserlife-261027/REQ](../requirements/browserlife-261027-control-reconnect.md).
Mode: autonomous technical decisions; dedicated decision owner `/root/design-owner`.

## ADR-D1. Process-owned native browser, connection-owned authority

Accepted 2026-10-27 by the delegated technical decision owner.

Keep the browser controller, native managers and surviving resource registry for
one Runner process. Use a stable nullable current connection epoch. Detecting
transport loss fences authority before asynchronous cleanup. Drain former
requests, viewers and pending effects and discard observation refs before a new
connection can act. Preserve current intent reconciliation and shielded engine
transitions; actual process shutdown and engine switches still retire resources.

This implements REQ-1, REQ-2, REQ-3 and REQ-5. Connection-owned native resources
cannot provide continuity; a separate daemon adds unnecessary operational and
storage authority. Risks are stale generation callbacks and cleanup/admission
races, addressed by deterministic lifecycle and native integration tests.

## ADR-D2. Classify connection loss independently of access and target loss

Accepted 2026-10-27 by the delegated technical decision owner. Use typed internal
current/unavailable/revoked/expired outcomes. Retain existing wire codes: transient
4500, denied 4403, expiry 4408, and actual native target loss 4409. Initial and live
admission and Owner effect checks use this distinction. Keep bounded UI retries,
no mutation replay, and no new wire version or persistent state. This implements
REQ-4 and REQ-6. Keeping bool loses essential recovery meaning; new protocols are
unnecessary. Unclassifiable validation remains fail-closed.

## ADR-D3. Fail closed on unconfirmed browser cleanup

Accepted 2026-10-27 by the delegated technical decision owner. Suspend only browser
authority on cleanup uncertainty and expose failed/browser_cleanup_failed under
the same intent; do not restart native resources or replay effects. Explicit new
intent uses ordinary confirmed retirement before starting resources. Preserve the
existing sticky retirement-failure boundary: an unconfirmed native retirement is
not repaired by asserting retry success. Final shutdown still attempts cleanup.
This implements REQ-2, REQ-3 and REQ-5. Silent restart loses native state; ignoring
cleanup uncertainty can authorize stuck or stale input. Other Runner capabilities
keep their current behavior.
