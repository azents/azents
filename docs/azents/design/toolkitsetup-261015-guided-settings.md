---
title: "Guided Toolkit Settings Design"
created: 2026-10-15
implemented: 2026-10-15
document_role: primary
document_type: design
snapshot_id: toolkitsetup-261015
tags: [toolkit, frontend, ux]
---

# Guided Toolkit Settings Design

## Authority and delivery

[Requirements](../requirements/toolkitsetup-261015-guided-settings.md) record the requester's direct implementation instruction and delegated in-scope UX choices. This is one frontend-focused PR, not a staged authorization redesign. The primary agent implements, integrates, and executes validation. The single read-only reviewer is `wizard-reviewer`. No material backend, storage, authorization, or lifecycle decision is introduced; [the boundary record](../adr/toolkitsetup-261015-guided-settings.md) captures retained contracts.

## Mechanisms

- **M1 — Ordered settings presentation** (REQ-1, REQ-2): a provider-neutral numbered section component presents preparation, existing connection/settings fields, and final naming/usage/review. Keep all provider fields mounted and preserve the single form. Only optional alias/custom prompt fields use disclosure; required fields remain visible. No new stage-completion gates or implicit tests.
- **M2 — Provider guidance** (REQ-1, REQ-3): localized purpose, prerequisites, ordered instructions, permission cautions, recovery advice, and official documentation links for the eleven registered provider types. The guide registry is presentation metadata, not the availability catalog. Existing GitHub/Google new-creation branches retain their specialized journeys; saved forms receive context. Unknown types retain their ordinary server-provided label and safe general instructions. The legacy Shell edit path is not promoted into catalog availability.
- **M3 — Safe final review** (REQ-4): summarize current local name, provider and ownership plus enabled/tool-discovery selections. Never stringify credentials/config or show resource URLs. Explain that explicit Add/Save commits settings, while existing authorization and tests are separate actions. OAuth-first/after-save instructions must match each provider's existing lifecycle. Persisted keys remain redacted.
- **M4 — Honest evidence and recovery** (REQ-3): explain optional test limits and retry actions next to real provider configuration. Service account email copy describes supplied key metadata, not authenticated identity. Do not add fake testing to EnvVar/Shell or require test success. Keep existing error output and credential replacement handlers.
- **M5 — Localization/accessibility/verification** (REQ-5): all new guidance and structural copy use four aligned locale namespaces. Use existing Mantine tokens and native headings/disclosures. Verify light/dark contrast and 390px overflow with actual product components. Permanent stories cover provider guidance, safe summary, optional fields, pending/error/saved credential states, and real field composition. Browser E2E covers generic shared CRUD plus existing GitHub/Google callbacks.

## Preserved boundaries

Workspace/Agent ownership remains the form entry context. Existing hooks own tests, discovery, mutable credentials, save, callbacks, cancellation, and pending fences. New GitHub/Google setup remains outside the ordinary form; saved Google metadata keeps its existing config omission. No API generation or migrations are needed. Do not reset inputs or remount fields for stage navigation.

Saved AWS/GCP/Analytics forms use the existing credential-presence flag to show
their retained-key notice and replacement action when identifiers are redacted.
This restores the existing replacement contract in that visible state; opening
the inputs still does not mutate credentials, require a metadata edit to replace
keys, or manufacture an account identity. New explanatory text uses the product's
normal text token rather than a low-contrast muted foreground.

## Design Authority

Design revision: 1. The exact mechanism set is M1, M2, M3, M4, M5.
M1/M2/M3/M5 are derived presentation mechanisms for the directly requested
REQ-1 through REQ-5 outcomes. M4 combines those outcomes with existing credential
and connection-test contracts. All unchanged lifecycle, ownership and API
mechanisms are existing authority from the Toolkit, Google Connection and MCP
OAuth Living Specs. None creates a new operational or authorization contract.

## Design Approval

Mode: direct implementation within delegated UX scope. Decision owner: requester
for product scope; primary agent for local presentation details. Date: 2026-10-15.
Revision 1 and M1–M5 implement the requester's instruction to apply the established
GitHub UX standard across settings without clarification questions. This records
that execution authority, not a separate document-signoff event. No new material
technical decision or independently approved authentication flow is claimed.

## Removal and Replacement

Replace the flat generic form layout with ordered sections; retain all functional controls. Remove misleading verification wording in touched service-account views. No Provider, route, API, credential contract or lifecycle is removed.

## Feasibility and acceptance

ToolkitForm already supports pure field composition via `configurationFields`, all provider containers are reusable, and four-locale composition has invariant tests. Existing catalog filtering, endpoint tests, ownership, and OAuth acceptance remain authoritative. Technical design stays within the directly requested UX improvement; no new material authority is delegated to a subagent.

Design delta: None. Reviewable scope is M1–M5; any new operational or authorization mechanism is out of scope.

## Test Strategy

Primary assembled browser verification runs Workspace create/edit/toggle/delete
with advanced alias persistence, Agent-owned management, and the existing
GitHub/Google callback flows. Existing synthetic provider fixtures need no live
credentials or new preparation support. Browser failure is a failure, not an
optional skip; infrastructure interruptions retain logs and require a fresh run.
Permanent unit/component tests cover all help types, unknown-provider fallback,
four-locale keys, safe summaries, optional-field input preservation, and pending
controls. Native light/dark/mobile component captures record fonts, DPR, zoom,
and overflow. The primary agent runs integrated checks, records exact results in
the PR, and requests the single independent reviewer only after the diff is stable.
