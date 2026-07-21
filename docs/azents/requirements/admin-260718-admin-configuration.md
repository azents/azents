---
title: "Generalize Admin-Managed System Configuration Historical Requirements Reconstruction"
created: 2026-07-18
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: admin-260718
historical_reconstruction: true
migration_source: "docs/azents/adr/0172-generalize-admin-managed-system-configuration.md"
---

# Generalize Admin-Managed System Configuration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `admin-260718`
- Source: `docs/azents/adr/admin-260718-admin-configuration.md`
- Historical source date basis: `2026-07-18`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently loads deployment and product configuration together from environment variables into a process-lifetime `Config`. Platform GitHub App credentials are one example: Public API OAuth endpoints and Worker GitHub Toolkit resolution both receive the same static environment-backed values. Changing those values requires deployment configuration changes and process restarts, while the Admin surface cannot show whether the integration is configured or healthy.

Moving only the four GitHub fields into a GitHub-specific table and service would solve the immediate input problem but repeat storage, secret handling, revision, validation, authorization, and runtime refresh behavior for every later Admin-managed setting. Planned candidates such as the default Runtime Provider, account-registration policy, email behavior, and retention policy need the same configuration lifecycle even though their schemas and consumers differ.

Deployment bootstrap settings and security roots still have a different lifecycle. Database connectivity, credential encryption roots, JWT signing material, process endpoints, and infrastructure security policy are required before Admin-managed state can be read or must remain controlled by the deployment operator.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
