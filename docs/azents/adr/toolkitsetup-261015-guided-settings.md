---
title: "Guided Toolkit Settings Boundary Record"
created: 2026-10-15
document_role: primary
document_type: adr
snapshot_id: toolkitsetup-261015
tags: [toolkit, frontend, ux]
---

# Guided Toolkit Settings Boundary Record

[Requirements](../requirements/toolkitsetup-261015-guided-settings.md) authorize a UX improvement using the implemented GitHub journey as the reference. This snapshot introduces no new material architecture or product-contract decision.

## Retained contracts

Presentation reuses current provider containers rather than introducing a universal authentication wizard. GitHub and Google have existing specialized unpublished setup lifecycles; generic OAuth Toolkits require a saved configuration before account authorization. A forced common authorization workflow would change those contracts and is outside the requested presentation work.

Provider help does not determine availability, grant permission, store credentials, or certify readiness. Server definitions remain the catalog source, tests remain explicit observations, and existing ownership-specific APIs remain authoritative. No alternative persistence, compatibility layer, versioning, or operational mode is added.

## Risk and validation

Rearranging forms can remount transient credential inputs or hide required validation targets. The implementation keeps provider components mounted and required inputs visible, and tests ordinary create/edit, saved-key preservation, pending controls, and OAuth return paths. New summaries contain only local nonsecret metadata and operating selections.
