---
title: "Independent Runtime Reads Decisions"
created: 2026-10-04
tags: [concurrency, runtime, read-paths]
document_role: primary
document_type: adr
snapshot_id: readleaves-261004
---

# Independent Runtime Reads Decisions

Authority: [Requirements](../requirements/readleaves-261004-independent-runtime-reads.md).

## D1. Remove read-side lock switches

The five independent revision/Profile/configuration getters accept `ReadSession`
and perform ordinary SELECT. Remove `for_update` arguments rather than retaining a
locking mode on descriptive reads. Lag and disappearing references are normal
read conditions; unchanged Workspace/resource scoping still applies.

This follows the requester-approved read contract, rather than a new cache or
coherence mechanism. Callers requiring actual mutation fencing retain that fence
at the mutation boundary. This phase does not remove those mutation implementations.
