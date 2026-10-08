---
title: "Normalized Usage Retention Decisions"
created: 2026-10-05
tags: [engine, usage, architecture]
document_role: primary
document_type: adr
snapshot_id: usage-261005
---

# Normalized Usage Retention Decisions

Authority: [usage-261005/REQ](../requirements/usage-261005-normalized-retention.md), confirmed by the requester's explicit removal request.

## D1 — Native receipts are transient; normalized usage is durable

**Decision:** Remove native raw usage and hidden-parameter fields from durable usage contracts. Adapters retain receipt evidence locally only through normalization and captured-price evaluation; durable output contains normalized quantities and finalized cost/provenance.

**Addresses:** usage-261005/REQ-1, usage-261005/REQ-2, usage-261005/REQ-3.

**Rationale:** One observed receipt contained nearly 201 KB of attribution while common totals were small. Complete receipts were repeatedly loaded with transcript history despite being omitted from model input. Separating receipt lifetime from accounting preserves current functionality without pretending a stripped dictionary is a lossless `raw` value. Public Codex also separates transient raw response-completed events from durable token accounting.

**Rejected options:** Keep all raw but narrow only model-input queries (retains exploratory data indefinitely); remove only attribution (still retains unspecified provider data and changes the meaning of raw); persist an empty raw placeholder (misrepresents absent evidence); add a receipt archive/retention configuration (unrequested system scope).

**Consequences:** Future records cannot reconstruct item attribution or re-decode newly discovered provider fields. Some detailed cache/media evidence is consumed for pricing but not independently durable. If later product work needs that evidence, it must define typed normalized quantities in a new snapshot. This change is not a guarantee that the historical 12.331-second preparation interval is fully solved.

## D2 — No historical physical rewrite in this delivery

**Decision:** Existing JSON records are parsed into the normalized contract and reprojected without removed receipt fields. This PR does not physically rewrite stored historical receipts or reclaim table space.

**Addresses:** usage-261005/REQ-4.

**Rationale and risks:** Historical receipt deletion is irreversible and operationally distinct from removing future retention. Existing bytes can still affect historical transcript reads until compaction/head advancement or separately approved cleanup. Normal schema parsing is sufficient; no added legacy fallback reader or replacement raw storage is introduced.
