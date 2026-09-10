---
title: "Image Generation Model Selection"
created: 2026-09-10
tags: [agent, workspace, image-generation, model-catalog, architecture]
document_role: primary
document_type: adr
snapshot_id: image-260910
---

# image-260910/ADR: Image Generation Model Selection

## Context

The confirmed
[image-generation model selection Requirements](../requirements/image-260910-generation-model-selection.md)
add an automatically maintained default and credential-visible explicit image-model
choices to each selectable conversation model option.

Azents already persists conversation-model catalogs as logical catalogs with current
snapshots, entries, and synchronization attempts. Integration-scoped synchronization
provides stale refresh, cooldown, failure backoff, running-attempt recovery, fenced
publication, and last-successful-snapshot preservation. The current catalog identity does
not distinguish different catalog purposes, and its public projection is designed for
conversation models.

Agent and Workspace selectable model settings already persist semantic built-in tool
configuration. Runtime preparation copies that configuration into the selected built-in
tool specification. Provider-hosted Responses lowering accepts an optional image tool
model, while the xAI client executor owns a separate maintained default.

The requester delegated the remaining technical decisions for this snapshot to an
autonomous technical decision owner.

## Decision log

### image-260910/ADR-D1 — Reuse the catalog lifecycle with a purpose discriminator

**Decision**

Add a catalog-purpose discriminator with at least `conversation` and
`image_generation` values to the existing logical catalog identity. Include the purpose
in system and integration catalog uniqueness. Reuse the existing catalog snapshot and
attempt lifecycle for image-generation availability while exposing a purpose-specific
public projection.

Image-generation entries reuse the common catalog identity, snapshot, availability,
display, lifecycle, and source-metadata concepts. Purpose-specific API and service types
must not expose conversation-model-only semantics as if they applied to an image tool
model.

**Authority**

- `image-260910/REQ-1`
- `image-260910/REQ-3`
- `image-260910/REQ-4`
- `image-260910/REQ-5`

**Consequences**

- Existing conversation catalogs are migrated to the `conversation` purpose.
- Repository lookups, uniqueness constraints, attempt coordination, and public read
  services become purpose-aware.
- Image catalog reads return stored state immediately and use the established stale
  refresh and explicit retry policy.
- Failed synchronization preserves the last successful image-model snapshot.
- A separate set of image catalog tables is not created, avoiding duplicate lifecycle,
  concurrency, and failure policy.
- Image availability is not stored as ad hoc integration JSON and is not fetched live
  during ordinary settings rendering.

**Alternatives considered**

1. **Dedicated image catalog tables.** Rejected because they would duplicate the existing
   snapshot, attempt, stale-refresh, concurrency, and recovery mechanisms.
2. **Integration JSON snapshot or live listing.** Rejected because it would weaken
   catalog identity, attempt observability, last-good preservation, and authoritative
   pinned-model validation.

### image-260910/ADR-D2 — Store image entries in a purpose-specific table

**Decision**

Add `image_generation_catalog_entries` for image-model entries and key each entry to the
shared logical catalog and snapshot from `image-260910/ADR-D1`. Keep the existing
`llm_catalog_entries` table conversation-model-specific.

An image entry stores:

- provider and provider model identifier;
- display name and user-facing description;
- recommendation rank;
- lifecycle and visibility status;
- provider integration identity;
- source and projection metadata; and
- an optional hidden reason.

Enforce one entry per provider model identifier within a snapshot. Repository publication
must verify that image entries are written only for an `image_generation` catalog and
must never publish conversation and image entries into the same snapshot.

**Authority**

- `image-260910/REQ-1`
- `image-260910/REQ-3`
- `image-260910/REQ-4`
- `image-260910/ADR-D1`

**Consequences**

- Image entries do not require fake conversation runtime identifiers, normalized
  conversation capabilities, or execution-option values.
- Existing conversation entry constraints and API projections remain unchanged.
- Shared snapshot deletion cascades through both purpose-specific entry tables.
- Catalog counts and attempt metrics remain shared and are distinguished by catalog
  purpose.
- Existing entry data requires no transformation; only catalog identity receives the
  `conversation` backfill from `image-260910/ADR-D1`.

**Alternatives considered**

1. **Store image entries in `llm_catalog_entries`.** Rejected because required
   conversation-only fields would need semantically empty placeholder values.
2. **Generalize the existing entry table into a nullable polymorphic record.** Rejected
   because it would weaken current conversation-entry invariants and require a broad
   migration unrelated to the new purpose.

### image-260910/ADR-D3 — Publish the supported-registry and credential-visibility intersection

**Decision**

Azents owns an exact provider image-model registry containing the compatibility,
display, recommendation, and lifecycle metadata that Azents is prepared to support.

An OpenAI API-key image catalog synchronization calls the official OpenAI SDK model-list
API with that integration's credential. The published explicit entries are the exact
model identifier intersection between the Azents registry and the complete
credential-visible provider result.

Model-name patterns, generic image modalities, provider visibility alone, and hidden
conversation-model catalog entries are not eligibility authority.

The maintained default is a semantic option produced by Azents rather than an explicit
catalog entry. It remains available for a provider whose current image-generation
executor supports default dispatch even when no explicit model entry is available.

Initial provider policy is:

- OpenAI API key: maintained default plus verified explicit entries;
- ChatGPT OAuth: maintained default only; and
- xAI API key and OAuth: maintained default only, without exposing the internal Imagine
  model identifier.

Adding explicit choices for another provider requires both an approved discovery source
and a verified runtime mapping, not only a registry entry.

**Authority**

- `image-260910/REQ-1`
- `image-260910/REQ-4`
- `image-260910/REQ-5`

**Consequences**

- Registry metadata remains stable and reviewable even when provider listing metadata is
  incomplete or changes shape.
- Synchronization must consume all provider pages before publishing a snapshot.
- Authentication, permission, rate-limit, transport, malformed-response, and partial
  pagination failures do not publish a snapshot and preserve the last successful one.
- A never-synchronized or failed-without-snapshot OpenAI integration offers the
  maintained default but no explicit entries.
- Deterministic tests cover exact intersection, pagination, duplicates, ordering,
  partial failure, and last-good preservation.

**Alternatives considered**

1. **Derive image eligibility from hidden LiteLLM conversation entries.** Rejected
   because conversation metadata is not authority for provider-tool model compatibility
   or credential visibility.
2. **Expose provider-visible models by image-like naming or mode.** Rejected because
   visibility and naming do not prove support by Azents' image-generation execution
   path.

### image-260910/ADR-D4 — Persist explicit image models in built-in tool configuration

**Decision**

Use the existing `BuiltinToolConfig` for `image_generation` as the single persisted
configuration authority:

- the maintained default omits the `config.model` key; and
- an explicit pin stores the exact validated provider model identifier in
  `config.model`.

Do not persist a default sentinel or resolve the default to a transient concrete model
identifier. Backend normalization owns a purpose-specific image-generation config
decoder. A missing `model` key is canonical default intent; a non-empty string is
canonical explicit intent. Null, blank, non-string, and sentinel values are invalid.

Changing the image model updates only the `model` key and preserves other existing tool
configuration keys. Frontend stored-to-form and form-to-input mapping must round-trip the
complete built-in configuration rather than reconstructing name-only tool entries.

An explicit value is accepted only when:

1. the selected conversation model advertises `image_generation`;
2. the selected integration/provider supports explicit image-model selection;
3. the current last-successful image catalog snapshot contains the model as available;
   and
4. the model remains in the Azents supported registry.

ChatGPT OAuth and xAI integrations reject explicit `config.model` values while retaining
default behavior.

**Authority**

- `image-260910/REQ-1`
- `image-260910/REQ-2`
- `image-260910/REQ-3`
- `image-260910/REQ-5`

**Consequences**

- Agent and Workspace default options use the same representation and copy behavior.
- The existing public built-in config map and selectable-options JSON storage remain the
  persistence path; no separate Agent settings column is added.
- Provider default changes require no stored configuration migration.
- Runtime hosted lowering receives an explicit model only for a validated pin.
- Existing invalid values are surfaced as configuration errors rather than silently
  interpreted as default.

**Alternatives considered**

1. **Add `image_generation_model` to selectable model settings.** Rejected because it
   would create a second source of truth that must be translated back into the semantic
   built-in configuration.
2. **Persist a provider-default sentinel in `config.model`.** Rejected because it would
   mix control state with provider model identifiers and could leak to provider
   dispatch.

### image-260910/ADR-D5 — Derive unavailable state from saved intent and the current catalog

**Decision**

Keep the saved `image_generation.config.model` value as the only selection authority and
derive its availability against the selected integration's current published image
catalog snapshot. Do not persist an unavailable flag on Agent or Workspace settings and
do not mutate settings during catalog synchronization.

The settings experience combines the unchanged saved config with the stored image
catalog response:

- a pin present in a fresh or stale last-successful snapshot is available;
- a pin absent from that snapshot is unavailable;
- a pin with no successful snapshot is unverified and cannot be saved;
- a pin for a provider without explicit selection support is unavailable; and
- the maintained default is independent of explicit discovery state.

Staleness alone does not make a pin unavailable. Background refresh proceeds while the
last-successful snapshot remains authoritative. A failed refresh retains the same
availability result.

The UI keeps an unavailable or unverified saved identifier as a disabled synthetic
option and requires the administrator to choose the maintained default, choose an
available explicit model, or disable image generation. Backend Agent and Workspace save
validation derives the same result from server-owned catalog state and does not trust a
client availability flag. Disabling image generation in the same replacement request
allows recovery.

Runtime preparation defensively verifies explicit configuration again before image
provider dispatch. A failed defensive check produces a configuration error and never
falls back to the maintained default.

**Authority**

- `image-260910/REQ-2`
- `image-260910/REQ-3`
- `image-260910/REQ-4`
- `image-260910/REQ-5`
- `image-260910/ADR-D3`
- `image-260910/ADR-D4`

**Consequences**

- Catalog publication performs no fan-out update to Agent or Workspace rows.
- Agent and Workspace reads preserve the exact saved model identifier.
- Availability state cannot become a stale duplicated boolean.
- Save validation uses one atomically published catalog snapshot. A later catalog
  replacement is treated as a new availability change and is covered by runtime
  defensive validation.
- Existing explicit values that cannot be verified remain visible but cannot be
  re-saved unchanged.

**Alternatives considered**

1. **Persist availability beside each selection.** Rejected because every catalog change
   would require fan-out updates and could leave settings with stale derived state.
2. **Fall back only at runtime.** Rejected because it would hide lost administrator
   intent and violate the required deliberate recovery flow.

### image-260910/ADR-D6 — Synchronize image catalogs independently through the shared policy

**Decision**

Each `image_generation` catalog owns an independent attempt and snapshot lifecycle while
reusing the existing integration-catalog synchronization policy, including
single-flight claims, workspace cooldown, transient failure backoff, running-attempt
lease recovery, and fenced publication.

Initial image catalog synchronization applies only to OpenAI API-key integrations and is
requested after:

1. supported integration creation;
2. a credential or discovery-affecting integration update;
3. an authorized explicit image catalog sync request; or
4. a stale image catalog read.

Create and update transactions enqueue synchronization only after commit. Duplicate
requests coalesce at the `(integration_id, purpose)` catalog claim. A stale read returns
stored state immediately and requests background work without blocking settings
rendering.

Image synchronization failures affect only the image catalog attempt and preserve its
last-successful snapshot. They do not affect a system-scoped conversation catalog.
Agent and Workspace settings services read and validate catalog state but do not call
provider discovery APIs.

The maintained default remains available independently of explicit image catalog
synchronization when the provider integration supports default image dispatch.

**Authority**

- `image-260910/REQ-1`
- `image-260910/REQ-4`
- `image-260910/REQ-5`
- `image-260910/ADR-D1`
- `image-260910/ADR-D3`

**Consequences**

- The public Integration/Catalog API owns image catalog read and explicit sync endpoints.
- Conversation and image purposes have separate single-flight identities and
  publications but share workspace-wide synchronization resource limits.
- ChatGPT OAuth and xAI integrations do not create image catalog sync attempts in the
  initial release.
- A credential-affecting update requires a new image snapshot before explicit choices
  can be saved against the new credential state.

**Alternatives considered**

1. **Publish conversation and image entries in one provider attempt.** Rejected because
   OpenAI conversation selection remains system-scoped and the two purposes have
   different entry schemas and failure ownership.
2. **Synchronize only when Agent settings are opened.** Rejected because integration
   creation and credential changes should establish availability proactively and
   settings endpoints must not own provider discovery.

### image-260910/ADR-D7 — Fence catalog authority by integration configuration version

**Decision**

Add a monotonic `catalog_configuration_version` to each provider integration. Increment
it only when a committed change can affect provider discovery or model usability:

- credential creation, replacement, or removal;
- provider account, project, endpoint, or other discovery-affecting configuration;
- disable; or
- re-enable.

Name-only and presentation-metadata changes do not increment the version.

An integration-scoped catalog attempt captures the current configuration version.
Published snapshots record that version, and publication rechecks it inside the
completion transaction. A result produced for an older version is recorded as
superseded and cannot replace the current snapshot.

An older last-successful image snapshot remains available for displaying a saved model
and diagnostics, but it is a stale-generation snapshot and cannot authorize an explicit
save. Explicit authorization requires an enabled integration and a current published
snapshot whose configuration version matches the integration. The maintained default
does not require listing evidence, but a disabled integration remains unusable.

The version belongs to the common integration-catalog lifecycle rather than an image
entry. System catalogs do not have an integration configuration version.

**Authority**

- `image-260910/REQ-1`
- `image-260910/REQ-3`
- `image-260910/REQ-4`
- `image-260910/REQ-5`
- `image-260910/ADR-D1`
- `image-260910/ADR-D6`

**Consequences**

- Slow synchronization started under replaced credentials cannot publish after the
  replacement.
- Settings can explain that the last-good list belongs to an older integration
  configuration while preserving unavailable pinned identifiers.
- Initial schema migration assigns a baseline version to existing integrations and
  integration-scoped catalog state; current conversation behavior does not begin using
  the new authorization fence unless separately designed.
- New image attempts and snapshots require the captured configuration version.

**Alternatives considered**

1. **Delete or clear the current snapshot on every credential update.** Rejected because
   it would remove useful last-good display and recovery evidence.
2. **Compare timestamps or rely on eventual synchronization.** Rejected because
   timestamps do not provide a deterministic publication fence and allow old credential
   results to win races.

### image-260910/ADR-D8 — Validate explicit image models during RunRequest resolution

**Decision**

After resolving the effective selectable model option and its provider integration, but
before engine or provider dispatch, RunRequest resolution validates every explicit image
model against:

1. the selected conversation model's `image_generation` capability;
2. the integration's enabled provider and explicit-selection policy;
3. the Azents supported image-model registry;
4. the current published image snapshot;
5. the integration configuration version captured by that snapshot; and
6. exact entry availability.

Validation runs for each effective option selection, including subagent target changes
and reconstructed requests using a previously resolved profile. Long-lived saved
configuration is therefore rechecked after catalog, registry, credential, or integration
state changes.

Resolved runtime behavior is:

- OpenAI API key with an explicit model: preserve `config.model` for hosted Responses
  lowering;
- OpenAI API key without a model: use hosted default behavior;
- ChatGPT OAuth without a model: use hosted default behavior;
- xAI without a model: use the client Imagine executor's internal default; and
- ChatGPT OAuth or xAI with an explicit model: reject the configuration.

The resolver never substitutes a concrete default identifier. Failure produces a typed,
non-retryable image-model configuration error before provider dispatch. Safe reason
codes distinguish disabled integration, unsupported explicit selection, unavailable or
generation-mismatched catalog, unavailable model, and provider/model mismatch.
Credentials and provider response content are not exposed.

Provider lowerers and client executors consume the resolved invariant and retain narrow
defensive assertions; they do not independently reimplement catalog policy.

**Authority**

- `image-260910/REQ-1`
- `image-260910/REQ-2`
- `image-260910/REQ-3`
- `image-260910/REQ-5`
- `image-260910/ADR-D3`
- `image-260910/ADR-D4`
- `image-260910/ADR-D5`
- `image-260910/ADR-D7`

**Consequences**

- A pin that became invalid after save cannot reach provider dispatch.
- Stale but current-generation last-good snapshots remain valid runtime authority.
- A missing or older-generation snapshot rejects explicit execution without affecting
  maintained default behavior.
- Explicit model identifiers cannot cross provider integrations during model-option
  switching.

**Alternatives considered**

1. **Validate only in provider adapters.** Rejected because it would duplicate catalog
   policy across adapters and allow failures to occur after dispatch preparation.
2. **Use a separate image provider independent of the conversation integration.**
   Rejected because the confirmed product contract scopes image choices to the selected
   conversation integration.

### image-260910/ADR-D9 — Expand and backfill the existing schema in one new migration

**Decision**

Create one new additive Alembic migration without modifying any executed migration. The
migration:

1. adds catalog purpose and backfills every existing catalog to `conversation`;
2. replaces catalog uniqueness with purpose-aware system and integration indexes;
3. adds non-null provider integration `catalog_configuration_version` with baseline
   value `1`;
4. adds nullable captured integration configuration versions to common catalog attempts
   and snapshots;
5. backfills existing integration-scoped attempt and snapshot versions to their
   integration baseline while leaving system-scoped versions null; and
6. creates the purpose-specific image generation entry table and its foreign keys,
   cascade behavior, and snapshot/model uniqueness.

Application code explicitly supplies the conversation purpose for existing paths and
does not rely on a long-term database default. Image catalog creation begins only after
the schema and purpose-aware application code are deployed.

Downgrade restores the conversation uniqueness indexes and removes the added image and
version structures. It does not convert image entries into conversation placeholders;
therefore downgrade after image data is published is data-destructive and requires
explicit operational approval.

**Authority**

- `image-260910/REQ-1`
- `image-260910/REQ-4`
- `image-260910/REQ-5`
- `image-260910/ADR-D1`
- `image-260910/ADR-D2`
- `image-260910/ADR-D7`

**Consequences**

- Existing conversation catalog and entry identities remain intact after backfill.
- The same integration and lowerer target may own separate conversation and image
  catalogs.
- New integration-scoped attempts and snapshots capture configuration version; system
  catalog state leaves it null.
- Migration verification covers old-schema upgrade, backfill, purpose uniqueness,
  version scope, image entry constraints, cascade deletion, and safe downgrade.
- Generated database schema artifacts are refreshed in the same change.

**Alternatives considered**

1. **Create a fully separate versioned image catalog schema.** Rejected by
   `image-260910/ADR-D1` because it would duplicate lifecycle and fencing.
2. **Depend on database defaults without backfill.** Rejected because existing catalog
   identity and integration-scoped version authority would remain ambiguous.

### image-260910/ADR-D10 — Seed the initial OpenAI registry with Flare and Sunburst

**Decision**

The initial OpenAI API-key image-model registry contains these exact undated identifiers:

1. `gpt-image-2.5-flare` as the first explicit choice, described as the fast,
   cost-balanced everyday model; and
2. `gpt-image-2.5-sunburst` as the second explicit choice, described as the
   highest-capability model for demanding generation and editing.

Both entries begin with active lifecycle and selectable registry visibility. The
maintained default remains a separate semantic option and appears before all explicit
entries.

The official OpenAI model references identify both models as supported by the Responses
Image generation tool:

- `https://developers.openai.com/api/docs/models/gpt-image-2.5-flare`
- `https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst`

The installed OpenAI request schema accepts an image-generation `model` string, and the
existing hosted lowerer preserves a validated `config.model`.

An explicit registry entry is published only when the integration credential's complete
model listing contains the exact identifier. A later model, alias, rename, or dated
revision is a separate registry entry and never silently migrates an existing pin.

**Authority**

- `image-260910/REQ-1`
- `image-260910/REQ` fixed initial OpenAI choices
- `image-260910/ADR-D3`

**Consequences**

- Provider listing visibility alone cannot add a third explicit model.
- Removing compatibility or provider visibility removes the model from new snapshots
  while preserving existing saved pins as unavailable.
- Lifecycle changes are reviewed compatibility changes. Deprecated entries may retain
  diagnostic metadata, while selectable visibility remains the authority for new
  selection.
- Recommendation order does not define default resolution or runtime fallback.
