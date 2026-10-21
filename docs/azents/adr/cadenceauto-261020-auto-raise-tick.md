---
title: "Automatic Routine Tick Adjustment"
created: 2026-10-20
tags: [agent, routine]
document_role: primary
document_type: adr
snapshot_id: cadenceauto-261020
---

# Automatic Routine Tick Adjustment

Authority: [cadenceauto-261020/REQ](../requirements/cadenceauto-261020-auto-raise-tick.md).

## ADR-D1. Normalize delay updates inside the existing mutation fence

REQ-1 replaces rejection of an inverted pair when the update supplies minimum
delay with `tick = max(effective tick, supplied delay)`. Use the existing refreshed
Agent lock and paired database constraint. Tick-only updates retain the prior
validation error. The requester fixes this behavior; no new configuration,
retry, scheduler or persistence authority is introduced. Normalizing before
locking is rejected because it can use a stale tick during concurrent saves.
