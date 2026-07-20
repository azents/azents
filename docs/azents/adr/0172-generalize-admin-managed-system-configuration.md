---
title: "ADR-0172: Generalize Admin-Managed System Configuration"
created: 2026-07-18
updated: 2026-07-20
tags: [architecture, backend, frontend, admin, configuration, security]
---

# ADR-0172: Generalize Admin-Managed System Configuration

## Context

Azents currently loads deployment and product configuration together from environment variables into a process-lifetime `Config`. Platform GitHub App credentials are one example: Public API OAuth endpoints and Worker GitHub Toolkit resolution both receive the same static environment-backed values. Changing those values requires deployment configuration changes and process restarts, while the Admin surface cannot show whether the integration is configured or healthy.

Moving only the four GitHub fields into a GitHub-specific table and service would solve the immediate input problem but repeat storage, secret handling, revision, validation, authorization, and runtime refresh behavior for every later Admin-managed setting. Planned candidates such as the default Runtime Provider, account-registration policy, email behavior, and retention policy need the same configuration lifecycle even though their schemas and consumers differ.

Deployment bootstrap settings and security roots still have a different lifecycle. Database connectivity, credential encryption roots, JWT signing material, process endpoints, and infrastructure security policy are required before Admin-managed state can be read or must remain controlled by the deployment operator.

## Decision

### Treat GitHub as the first consumer of a general system-configuration capability

The first delivery moves Platform GitHub App configuration to the Admin surface, but its persistence, authorization, secret handling, revision, validation, and consumption lifecycle must be expressed through provider-neutral system-configuration abstractions.

GitHub-specific code may define the typed GitHub schema, validation against GitHub, impact analysis for existing installations, and GitHub-specific Admin presentation. It must not own a parallel configuration store, generic encryption protocol, revision model, or process-refresh mechanism.

### Keep configuration ownership instance-scoped

Admin-managed system configuration belongs to the Azents instance and is writable only through the live database-backed `system_admin` authorization boundary. It is not owned by a Workspace, ToolkitConfig, Agent, Runtime, or individual User.

### Preserve a separate deployment-controlled configuration class

Admin-managed configuration must not absorb values required to connect to its own storage, decrypt its own secrets, establish process identity, or enforce deployment security boundaries. PostgreSQL and backing-service connectivity, credential-encryption roots, JWT material, bootstrap-token source, service endpoints and topology, telemetry bootstrap, Runtime Control authentication, Runtime Provider deployment, and network/RBAC policy remain deployment-controlled. The Admin surface may report redacted status for those concerns but cannot read or mutate their values.

### Store atomic typed domain sections through a shared configuration registry

The reusable configuration aggregate is a typed domain section, not an independently mutable key. Examples include `platform_github_app`, `runtime`, `auth_policy`, and `file_lifecycle`.

All sections use a shared lifecycle envelope that identifies the section type and schema version and carries the common revision, candidate, health, audit, validation, and secret-handling state. Current and candidate non-secret payloads use typed JSONB, complete secret payloads are encrypted with `CredentialCipher`, and non-sensitive secret-presence/change metadata is stored separately for redacted reads.

Each section type is registered with domain-specific typed configuration and secret models, validation behavior, and impact analysis. Consumers depend on the registered typed view rather than reading an untyped JSON dictionary. A section update validates and commits the complete aggregate atomically, so cross-field invariants cannot be bypassed by writing individual keys.

The shared registry owns the provider-neutral persistence and lifecycle contract. Domain modules retain ownership of their schema and external validation. Adding a section therefore does not require a parallel configuration store, while the generic layer does not need to understand GitHub, Runtime Provider, or future domain semantics.

### Keep current Admin state with optimistic-concurrency versions

Each section stores one current Admin-managed base value and a monotonically increasing `version`. Activation replaces the current typed payload and increments the version. Mutations require the caller's expected version so concurrent Admin updates and stale validation results cannot overwrite newer state.

The persistence layer does not retain replayable configuration payload history. A separate append-only audit stream records the section, previous and new version, actor, source, changed field names, secret actions, validation result, impact confirmation, and timestamps without recording configuration values, ciphertext, or secret fingerprints.

Consumers read the current effective configuration. Multi-stage operations identify the effective configuration generation with a keyed digest of the complete effective typed payload; if that generation changes, the operation fails safely and restarts instead of retrieving a historical payload. Admin version, source labels, timestamps, and other non-effective metadata are excluded so equivalent effective values retain the same generation.

### Retain only current and candidate Admin-managed secrets

The current Admin-managed typed secret payload is encrypted with the deployment-controlled `CredentialCipher`. The cipher root key remains deployment-managed because the application must decrypt Admin-managed settings before those settings can affect runtime behavior.

An optional candidate may hold encrypted replacement secret material while validation or impact confirmation is pending. Activating the candidate replaces the current secret payload. Superseded secret ciphertext is not retained as rollback history.

Admin mutation requests express secret changes as explicit per-field actions:

- an omitted secret field keeps the current value;
- `replace` supplies a new plaintext value;
- `clear` removes the value from the candidate.

`null`, empty strings, masked placeholders, and values previously returned by the API do not represent keep or clear behavior. Plaintext exists only for request validation and internal resolution, is encrypted before persistence, and must never be returned or intentionally logged.

Admin read models expose only non-sensitive state such as whether each secret field is configured and when it was last changed. They do not expose plaintext, prefixes, suffixes, hashes, fingerprints, or an internally resolved secret model. Internal consumers obtain a typed resolved snapshot through a separate non-serializable service contract.

### Select direct, validated, or confirmed activation by section capability

Every mutation must pass typed local validation and optimistic-concurrency checks. The section definition then selects one of three activation capabilities:

- `direct` replaces current Admin state in the same transaction after local validation;
- `validated` stores the section's single candidate, runs domain-specific external validation, and automatically activates a valid candidate;
- `confirmed` stores and externally validates the candidate, produces a section-defined impact report, and requires explicit Admin confirmation before activation.

The candidate records the current Admin version from which it was created. Its validation result distinguishes `valid`, `invalid`, and `unavailable`; an external dependency failure is retryable `unavailable`, not proof that the candidate is invalid. Activation succeeds only if the current version still matches the candidate's base version.

A new candidate replaces the previous candidate for the section. Activation, cancellation, replacement, or expiry removes candidate secret material that is no longer needed. The backend does not persist incomplete form drafts.

The current Admin state remains in use until a candidate is activated. Runtime health is separate from candidate validation: an external service outage after activation may mark the section health unavailable, but it does not invalidate, deactivate, or roll back the effective configuration automatically.

Platform GitHub App changes use `validated` for externally verifiable changes that do not alter App identity and `confirmed` when the domain impact analysis detects an identity change affecting existing installations or Toolkits.

### Overlay environment-bound fields without materializing them

A registered typed field may declare an environment-variable binding. When the variable is present in the actual process environment, its value takes precedence over the Admin-managed base value for that field. Precedence is field-level, while typed parsing, cross-field validation, and external validation apply to the complete effective section after all overlays are resolved.

An environment-bound field is read-only through Admin APIs and UI. Read models expose its environment source and variable name; secret fields still expose only configured state. Write APIs enforce the same restriction rather than relying on disabled UI controls.

Environment-provided values and secrets are not copied into current or candidate Admin state, audit events, or another database materialization. The shadowed Admin-managed base value remains independently stored. Environment changes therefore follow deployment restart semantics and cannot be reconstructed from historical database state.

A present but empty environment variable remains an environment override and is validated as the provided empty value. It does not reveal a shadowed database value through an implicit fallback.

When an environment variable is removed, the field resolves to its stored Admin-managed base value after the deployment restarts. If no Admin value exists, the field is unconfigured. While an override is active, Admin read models expose whether a shadowed fallback is configured and when it was last changed, together with a warning that removing the environment variable will reactivate it. The fallback value itself remains redacted according to the normal field contract.

### Keep correctness and propagation independent of Redis

PostgreSQL remains the source of truth for current Admin state, candidates, versions, and audit events. System Settings reads and writes must remain correct when Redis is unavailable and must not assume that a Redis deployment exists once the broader product makes Redis optional.

A notification or cache provider may be added as an optional performance optimization. Notifications never carry configuration payloads or secrets, and missed or unavailable notifications cannot be the only mechanism by which another process observes a committed database change. The baseline database read contract and operation boundaries determine consistency without Redis Pub/Sub.

### Read current settings directly at operation boundaries

The initial implementation performs a PostgreSQL read through `SystemSettingsService` whenever a consumer begins an operation that requires a system setting. It does not introduce a process-local TTL cache, PostgreSQL notification listener, or Redis invalidation path.

An operation boundary is the point at which the setting becomes an input to one coherent action, rather than every lower-level external request. Examples include Platform GitHub App OAuth start, OAuth callback, installation-token issuance, Agent or Runtime creation that selects a default provider, and an Admin settings read.

Each operation holds the resolved typed configuration in memory for that operation only. The next operation reads committed database state again and applies the local process environment overlay. `SystemSettingsService` hides the storage strategy so an optional measured cache may be introduced later without changing consumers or correctness semantics.

### Fail and restart multi-stage operations when effective generation changes

The resolver produces an opaque effective generation by applying a keyed digest to canonical JSON containing the Section key, schema version, and complete effective config and secret payload. The digest uses a domain-separated key derived from deployment-controlled root material so secret values cannot be compared through an unkeyed public fingerprint. Admin version and field source are not inputs because they do not change consumer behavior when the effective values remain equal.

A single-stage operation keeps its resolved typed snapshot in memory until the operation ends. A multi-stage protocol that requires the same external identity persists only the opaque generation in its signed or durable protocol state. Each later stage reads the current effective configuration and compares generations.

A mismatch fails with a domain-specific configuration-changed result and requires the protocol to restart. The system does not retrieve superseded Admin values or prior environment secrets. Generation values are internal control data and are not exposed through Admin APIs, audit events, or normal logs.

Values selected at resource creation, such as a default Runtime Provider, are copied as the resolved resource identifier. They do not require a long-lived generation reference. Generation persistence is limited to protocols whose correctness depends on using the same configuration across stages, such as Platform GitHub App OAuth start and callback.

### Bind GitHub installations and Platform Toolkits to App ID

The GitHub App ID alone defines Platform App identity for installation ownership. `github_user_installations` records and `github_app_platform` Toolkit credentials store the App ID with their installation targets. Runtime token issuance compares the stored App ID with the current effective App ID before calling GitHub.

Private key and client secret changes are credential rotations within the same App and do not invalidate installations or Toolkits. A Client ID change is OAuth configuration, not installation identity; external validation must verify that it belongs to the configured App ID. Any configuration change may invalidate an in-flight OAuth generation, but only an App ID change requires existing installation reconnection.

An Admin candidate that changes App ID uses `confirmed` activation and reports affected users, installation records, Platform Toolkits, and attached Agents. Activation does not delete those records. A stored App ID mismatch produces `reconnect_required` before token exchange, preserving Toolkit name, toolsets, prompt, and other configuration until the user replaces its installation binding through the new App.

An environment-provided App ID change cannot use Admin confirmation. After restart, the same App ID comparison marks existing records and Toolkits as requiring reconnection and the Admin surface reports the affected counts and environment source.

### Backfill legacy GitHub bindings only from the upgrade-time environment App ID

The schema migration adds nullable App ID binding fields without guessing a value. An idempotent application data migration then runs with `CredentialCipher` access. If the existing `AZ_GITHUB_PLATFORM_APP_ID` environment variable is present during the first upgraded startup, the migration binds legacy `github_user_installations` records to that App ID and decrypts, updates, and re-encrypts legacy `github_app_platform` Toolkit credentials with the same App ID.

The application records an applied or skipped completion marker so multiple processes or restarts do not repeat the decision. Only product entrypoints that receive the Platform GitHub App environment overlay participate in this migration decision; a scheduler or ad hoc operator CLI without that overlay must not win the lock and record a skipped outcome. If no environment App ID is available at the migration point, legacy records remain unbound and are not automatically claimed by an App configured later. The first Admin App activation must explicitly choose either to claim all still-unbound resources as belonging to that pre-existing App or to leave them unbound and require user reconnection. A verified user OAuth reconnect may also bind the specific installations it returns.

This backfill is an application data migration rather than an Alembic data rewrite because Toolkit credentials require the deployment-controlled encryption key. It does not copy environment private keys or client secrets into database state.

### Keep existing GitHub environment names and separate their Helm Secret surface

The four existing environment variables remain permanent field bindings for the `platform_github_app` Section:

- `AZ_GITHUB_PLATFORM_APP_ID`;
- `AZ_GITHUB_PLATFORM_PRIVATE_KEY`;
- `AZ_GITHUB_PLATFORM_CLIENT_ID`;
- `AZ_GITHUB_PLATFORM_CLIENT_SECRET`.

They move out of the process-lifetime `Config.github` object and are read by the shared environment-overlay resolver. Public API OAuth paths and Worker installation-token issuance resolve the Section through `SystemSettingsService` at their operation boundaries. `GitHubToolkitProvider` no longer captures Platform App credentials when the process-level Toolkit registry is constructed.

The Helm chart removes GitHub keys from the core auth Secret contract. A separate optional Platform GitHub App environment block references an `existingSecret` and configurable per-field key names. The helper renders a field only when its key name is non-empty, so omitted bindings remain absent and operators may combine environment-owned and Admin-owned fields. Secret literals are not added to chart defaults.

The existing environment variable names do not receive compatibility aliases or one-time import behavior. Existing deployments move the Secret reference from the shared auth block to the dedicated optional block during chart upgrade. Deployments that omit the block have no GitHub environment overrides and may configure the Section through Admin.

### Accept an unconfigured interval when moving environment-owned fields to Admin

The system does not copy environment values into Admin state and does not provide a separate shadowed-fallback preparation API. While an environment binding is present, its field remains read-only through the normal and handoff Admin surfaces.

To transfer ownership, the operator removes the environment binding and restarts the affected processes. A previously stored Admin base value becomes effective automatically; otherwise the field and potentially the complete Section become unconfigured until a system administrator submits and validates new Admin values. Operators plan a maintenance interval when the Section cannot remain usable during this transition.

This explicit interruption preserves the no-materialization and no-duplicate-secret contract. New installations choose environment or Admin ownership before first use, while existing installations that require a source transition perform it as an operational migration rather than an application-level secret copy.

## Consequences

- The GitHub migration must establish reusable configuration infrastructure before replacing GitHub environment variables.
- Later system settings can reuse the same authorization, optimistic-concurrency, redaction, validation, audit, and runtime-consumption contracts without adopting a GitHub-shaped data model.
- Deployment configuration and Admin-managed system configuration remain visibly distinct to operators.
- The initial design is larger than a GitHub credential form, but it avoids multiple incompatible configuration stores and refresh paths.
- New section types require an explicit typed schema registration and schema-version migration policy rather than arbitrary runtime key creation.
- Generic Admin inventory and lifecycle tooling can enumerate sections without interpreting their domain payloads.
- Configuration and secret payload history cannot be used for rollback or replay; operators rely on audit metadata and submit a new change when recovery is required.
- Superseded Admin-managed secret ciphertext is not retained beyond the current and candidate lifecycle.
- Admin APIs cannot be used to retrieve or fingerprint stored secret values.
- Operators may override individual fields through deployment environment variables while managing the remaining fields through Admin.
- Environment source metadata and write protection must be computed by the same runtime resolver that supplies effective values to consumers.
- Environment-managed secrets remain outside the database, so a deployment or Admin configuration change can invalidate a multi-stage operation that started with an earlier effective generation.
- Removing an environment override restores the shadowed Admin value, so operators must be able to inspect fallback presence and age before deployment changes.
- Simple locally validated settings retain a direct update path, while external validation and disruptive changes reuse one bounded candidate lifecycle.
- Redis availability does not affect System Settings correctness; future notification or cache integrations remain replaceable optional optimizations.
- The initial implementation adds a database read at each settings-dependent operation boundary in exchange for immediate cross-process consistency and simpler failure analysis.
- Multi-stage protocols cannot continue across an effective generation change; they fail explicitly and restart instead of depending on retained historical secrets.
- Platform GitHub App credential rotation preserves existing installation bindings, while an App ID change makes those bindings explicitly reconnectable rather than deleting them or failing lazily.
- Existing installations and Platform Toolkits upgrade without reconnecting when the prior environment App ID remains available, while ambiguous legacy bindings require an explicit claim or reconnect decision.
- Existing GitHub environment variables remain a stable deployment interface, but the core auth Secret no longer requires optional GitHub keys and runtime consumers no longer depend on static `Config.github` injection.
- Moving an environment-owned field to Admin may require a planned unconfigured interval; the system does not duplicate deployment secrets to provide a transparent handoff.

## Alternatives Considered

### Copy environment values into Admin state during handoff

Rejected. Automatic copy violates the no-materialization contract, and manual prepopulation would still retain duplicate secret values under two management sources before the environment binding is removed.

### Provide a separate API for preparing shadowed Admin fallback values

Rejected. Although the Admin would re-enter rather than reveal environment values, the result still creates deliberate duplicate secret storage to avoid a short handoff interruption. The design instead keeps environment-owned fields fully read-only until their bindings are removed.

### Replace the existing GitHub environment variables with a generic manifest

Rejected for the first system-setting consumer. A manifest adds deployment parsing and lifecycle complexity without improving field-level precedence, and existing Helm and non-Kubernetes deployments already have stable environment bindings.

### Import GitHub environment values once and remove environment support

Rejected. It would reduce source combinations but would not support operators who intentionally keep deployment-owned settings authoritative over Admin values.

### Keep GitHub keys inside the shared auth Secret contract

Rejected. Platform GitHub App support is optional and must not require unrelated installations to provision placeholder keys. A dedicated optional Secret surface preserves Helm-managed configuration without expanding bootstrap requirements.

### Bind all legacy records to whichever App is configured later

Rejected. A later Admin configuration may represent a different App, and silently claiming legacy installation IDs would defer the mismatch to runtime token exchange.

### Require every legacy installation and Toolkit to reconnect after upgrade

Rejected. Existing records were created through the previously configured environment App, so the upgrade-time App ID provides a safe compatibility binding when it is still present.

### Rewrite encrypted Toolkit credentials inside the Alembic migration

Rejected. Schema migrations must not depend on deployment secret material or application credential services. The schema remains nullable until an idempotent application data migration can use `CredentialCipher` safely.

### Treat App ID and Client ID together as Platform App identity

Rejected. GitHub installation authorization is bound to the App, while private keys and OAuth credentials may rotate or be corrected without changing the App installation identity. App ID is the persisted binding key; Client ID remains externally validated OAuth configuration.

### Let existing Platform Toolkits fail lazily after an App ID change

Rejected. Current records do not identify their App and would attempt token exchange with an incompatible App credential. Explicit App ID binding detects the mismatch before external calls and gives users a reconnect path.

### Block App ID changes while any installation or Toolkit exists

Rejected. It protects existing bindings but turns planned App migration into destructive manual cleanup. Confirmed activation with an impact report preserves Toolkit configuration and marks only installation authorization for reconnection.

### Let every stage resolve and use the latest configuration without comparison

Rejected. A multi-stage external protocol could combine authorization or identity state created with one configuration and credentials loaded from another configuration.

### Compare only the Admin version across stages

Rejected. It detects database changes but cannot detect different environment overlays during a rolling deployment or after an environment-variable change.

### Retain historical effective snapshots for multi-stage protocols

Rejected. Non-materialized environment secrets cannot be reconstructed, and retaining Admin secret history solely for these protocols would reintroduce asymmetric rollback and destruction semantics. An opaque generation check fails safely without payload history.

### Add a process-local TTL cache in the initial implementation

Rejected for the first delivery. Settings-dependent operation volume is expected to be low, while even a short TTL introduces observable cross-process staleness. The storage boundary permits adding a measured cache later if database load justifies it.

### Use PostgreSQL LISTEN/NOTIFY for immediate invalidation

Rejected for the first delivery. It avoids an additional component but still requires dedicated connection lifecycle, reconnection, and missed-notification recovery. Direct operation-boundary reads are simpler and already satisfy the expected workload.

### Require Redis invalidation for cross-process consistency

Rejected. It would make a presently deployed supporting component part of the long-term System Settings correctness contract and conflict with the goal of making Redis optional. Any notifier must be replaceable and backed by a database-consistent read path.

### Apply every valid mutation directly to current state

Rejected. It is appropriate for local-only settings but would expose unverified external credentials or disruptive identity changes before validation and impact confirmation complete.

### Require a candidate and explicit activation for every mutation

Rejected. It provides one uniform workflow but adds unnecessary persistence and operator steps to simple local policy changes. Candidate lifecycle is selected only when section capabilities require it.

### Require explicit Admin reactivation after removing an environment override

Rejected. It avoids reactivating a stale fallback but turns ordinary Helm rollback or environment cleanup into a service interruption requiring an additional control-plane action. Source precedence is more predictable when removing an overlay reveals the stored base value.

### Configure fallback behavior separately for each field

Rejected. Per-field fallback policies would make source resolution and operator expectations harder to understand. All environment-bound fields follow the same overlay-removal rule, while typed validation determines whether the resulting complete section is usable.

### Materialize environment-provided values into database state

Rejected for environment overrides. Operators commonly use environment secrets specifically as deployment-owned runtime inputs, and persisting them would create a second retained copy with different destruction semantics. Environment changes instead invalidate any operation that requires an unavailable prior deployment value.

### Lock an entire section when any environment variable is present

Rejected. Environment precedence can be enforced per typed field while the complete effective section is still validated atomically. Locking the whole section would prevent valid mixed deployment/Admin configuration without improving schema validation.

### Retain immutable configuration and secret payload revisions

Rejected after comparison with established open-source system-setting models. Replayable history would retain stale secret material, while non-materialized environment overlays would still make the historical effective configuration incomplete. A current version, a candidate, and metadata-only audit events provide concurrency and accountability without promising rollback or replay.

### Keep mutable current state without a version or audit stream

Rejected. Optimistic concurrency, stale candidate detection, cache invalidation, and operator accountability require a monotonic current version and append-only metadata events even though payload history is not retained.

### Return masked secret placeholders through the Admin API

Rejected. Placeholder values can be confused with replacement inputs and reveal unnecessary value shape. Read responses expose configuration state only, and mutation requests use explicit actions.

### Store configuration as independently mutable generic key-value entries

Rejected. This would reproduce an untyped environment-variable model in the database. Atomic cross-field validation, secret replacement, revision consistency, and domain-level impact analysis would become fragmented across individual keys.

### Create a dedicated singleton table for every typed domain section

Rejected as the common persistence model. Dedicated tables provide strong database-level field constraints, but they duplicate revision, audit, validation, redaction, and inventory behavior for every section. Domain-specific typed models remain required, but they are registered behind the shared section lifecycle instead of owning separate stores.

### Store Platform GitHub App settings in a GitHub-specific singleton table and inject them directly

Rejected. It would make the first implementation fast but force later settings to duplicate or depend on GitHub-specific persistence, secret-update, validation, and cache behavior.

### Keep all settings in environment variables and add a read-only Admin inventory

Rejected as the target direction. It improves discoverability but does not reduce bootstrap burden or allow authorized runtime changes.
