---
title: "Agent Toolkit Catalog Presentation and Icon Ownership"
created: 2026-10-08
tags: [toolkit, agent, frontend, ux, architecture]
document_role: primary
document_type: adr
snapshot_id: toolkit-261008
---

# Agent Toolkit Catalog Presentation and Icon Ownership

- Snapshot: `toolkit-261008`
- Document reference: `toolkit-261008/ADR`
- Requirements: [toolkit-261008/REQ](../requirements/toolkit-261008-catalog-ux.md)
- Mode: Collaborative
- Decision owner: Requester

## Decision Map

### Fixed and derived outcomes

- Replace the managed type-first/ownership-selection surface with the confirmed two-tab catalog, compact connected cards, and details (`REQ-1`, `REQ-2`, `REQ-3`, `REQ-5`, `REQ-6`).
- Preserve provider availability and persisted state authority on the existing server, including ownership-specific CRUD, shared attachment, OAuth, and readiness (`REQ-8`; [Toolkit Spec](../spec/domain/toolkit.md)).
- Retain existing provider forms initially and separate their presentation boundary from catalog discovery (`REQ-2`).
- Commit each addition through its current mutation without submitting the parent Agent form (`REQ-4`). Existing code already performs those completed operations.
- Render only currently available non-secret configuration and access explanations in details; external grant/account introspection is outside scope (`REQ-6`).
- No database migration, new icon/configuration API, new runtime tool catalog, or new application mode follows from these outcomes.

### Material technical decisions

- [x] **D1 — Accepted:** frontend-owned bundled Toolkit icon presentation, using the existing Tabler package with vetted local SVG assets for missing service marks, through one common rendering treatment.

There are no other unresolved material technical decisions in this bounded change. Equivalent UI component decomposition, file names, grid sizing, typed projection helpers, and fixture composition remain Agent-owned details.

## toolkit-261008/ADR-D1. Bundle service icons in the frontend with one presentation owner

**Affects:** `toolkit-261008/REQ-2`, `REQ-3`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`.

**Decision:** Accepted by the requester on 2026-10-08. Use the already installed `@tabler/icons-react` icons where the appropriate service mark exists. Supplement missing service marks with reviewed local SVG assets distributed with Main Web. A single frontend presentation mapping keyed by the server's stable `toolkit_type`/Provider slug and a common icon wrapper serve catalog tiles, Workspace instance tiles, connected cards, and details.

The requester explicitly selected local asset supplementation and a consistent look and feel. This decision records that choice; it does not reopen icon source selection or add an icon-upload/admin feature.

### Current evidence

- Main Web already imports Tabler brand icons for GitHub, Google Analytics, Slack, and Discord.
- The current Main Web manifest requests `@tabler/icons-react ^3.46.0`; the inspected lock resolves `3.48.0`.
- That package includes `IconBrandGithub`, `IconBrandNotion`, `IconBrandSentry`, `IconBrandAws`, and `IconBrandGoogleAnalytics`.
- Corresponding `IconBrandGoogleCloud`, `IconBrandBrave`, `IconBrandMcp`, and `IconBrandKubernetes` exports are absent in the inspected release.
- Public `ToolkitResponse` contains slug/name/description/config schema/system prompt, not an icon URL. ToolkitConfig contains configuration and ownership, not mutable logo state.

### Consequences

- The server remains the sole owner of which Provider types exist and which Toolkit instances are eligible. Presentation metadata does not become an availability registry or suppress a discovered Provider solely because an icon entry is missing.
- Icons are release assets, not credential-dependent data. No browser request to a third-party icon CDN or provider favicon endpoint is required.
- There is no public `icon_url`, icon-storage service, migration, per-Toolkit logo, arbitrary SVG upload, or settings knob.
- Explicit imports/local asset references keep the rendering surface bounded. A valid but unknown Provider uses the neutral Toolkit glyph with its real server-provided name; existing records and test-only Providers remain renderable.
- The wrapper standardizes optical size, display envelope, theme treatment, padding, and background. It preserves the service mark's proportions and original path geometry; matching the application does not mean redrawing every brand into an artificial outline.
- Tabler outline glyphs retain their normal stroke treatment. Local filled marks do not receive synthetic strokes. Approved monochrome/light/dark asset variants are used when source terms permit; a color mark is not recolored without checking its usage terms.
- Third-party SVGs are reviewed and converted to fixed local rendering nodes before inclusion. Active content, external references, scripts, event handlers, and embedded credentials are not accepted.
- Source URL, retrieved source revision/date, applicable license and brand-guideline links, original geometry, and permitted local transformations are recorded alongside local assets. Dependency/license notices are preserved.

### Alternatives considered

1. **Tabler only, including generic semantic glyphs for missing brands:** smallest maintenance cost and consistent strokes, but weaker service recognition for catalog selection. Not selected because the requester chose local supplementation.
2. **Tabler plus vetted local service marks:** accepted. It preserves the existing integration while filling the actual coverage gaps without a new data/configuration authority.
3. **A second complete brand-icon dependency:** introduces package-wide coverage/removal churn for a few missing assets. It also does not remove per-brand usage obligations. Not selected for this scope.
4. **Backend icon URLs or mutable uploaded icons:** adds a new interface/state/security/operational surface not required by the approved UX. Not selected.
5. **Remote icons/favicons at render time:** adds network, privacy, availability, and content-trust dependencies to a deterministic catalog. Not selected.

### Asset admission and reference evidence

- [Tabler README](https://github.com/tabler/tabler-icons) documents ES-module tree shaking and MIT licensing; preserve copyright/license notices.
- [Simple Icons disclaimer](https://github.com/simple-icons/simple-icons/blob/develop/DISCLAIMER.md) explicitly distinguishes its package license from individual icon licenses and trademarks. Its metadata may help discover upstream assets; it is not sufficient by itself to prove unrestricted logo usage.
- [Brave branding assets](https://brave.com/brave-branding-assets/) provides official packages including monotone variants.
- [Google Cloud icons](https://cloud.google.com/icons) provides official icon resources; use an appropriate service mark and its applicable guidelines rather than an arbitrary product icon.
- [Kubernetes upstream logo directory](https://github.com/kubernetes/kubernetes/tree/master/logo) and [MCP documentation logo](https://github.com/modelcontextprotocol/docs/tree/main/logo) are source candidates identified through upstream metadata.

Specific SVG files must pass provenance and content review before implementation includes them. This is an asset-admission prerequisite, not authority to introduce a remote fallback or silently redraw a brand. If a source prevents the required local usage, resolve that exact asset before shipping; do not expand product scope.
