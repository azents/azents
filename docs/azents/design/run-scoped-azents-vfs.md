---
title: "Run-Scoped Azents Virtual Filesystem"
created: 2026-07-19
updated: 2026-07-21
tags: [architecture, backend, engine, toolkit, skill, storage]
---

# Run-Scoped Azents Virtual Filesystem

## Problem

Azents currently discovers Skills only from the Agent Runtime filesystem. Release-bundled and Toolkit Provider-owned Skills need stable model-visible locators, adjacent package resources, deterministic authorization, and recovery-safe content without copying every package into every Runtime.

## Goals

- Provide a general-purpose read-only `azents://` virtual filesystem.
- Freeze one immutable VFS projection for every AgentRun before SkillAction input promotion.
- Load managed Skills directly from `azents://skills/{namespace}/{skill}/SKILL.md`.
- Materialize adjacent managed resources into Runtime only through `import_file`.
- Preserve all existing filesystem Skill paths, discovery, active/latest adoption, and resource behavior.
- Support global release bundles and Toolkit Provider-owned release bundles.
- Keep retries, worker takeover, and run resume on the exact same projected bytes.

## Non-Goals

- Writable VFS operations.
- Runtime mounting or transparent VFS access through ordinary file tools.
- Catalog publishing and Workspace/Agent package assignment APIs in the first implementation.
- Large binary package storage or object-store-backed VFS blobs in the first implementation.
- Replacing filesystem Skill projection state.

## Current Behavior

Filesystem Skills are scanned from Agent and registered Project directories into session-bound Toolkit State. The state has `latest` and `active` snapshots. Composer actions use `latest` while idle and `active` while running. `load_skill` and SkillAction preparation resolve exact absolute `SKILL.md` paths from `active`.

RunExecutor creates or claims an AgentRun and then promotes the initial input before registered and auto-bound Toolkits are resolved. This ordering means a managed Skill selected as a SkillAction must already be present in a run-owned projection before toolkit construction.

`import_file` uses a scheme resolver registry and currently supports `exchange://` and `artifact://`.

## Proposed Design

### URI Contract

The canonical URI shape is:

```text
azents://{mount}/{path...}
```

The first mount is `skills`:

```text
azents://skills/azents/deep-research/SKILL.md
azents://skills/github/review-pull-request/SKILL.md
azents://skills/github/review-pull-request/references/checklist.md
```

Canonicalization requires the lowercase `azents` scheme, a registered lowercase authority/mount, non-empty path segments, no query or fragment, no userinfo or port, no backslash, no dot segment, and no encoded separator or alternate traversal encoding. Path case is significant.

### Release Source Model

A release source definition contains:

- stable source ID;
- source kind (`global_release` or `toolkit_release`);
- namespace;
- Python package and package-relative resource root;
- whether projection construction may omit the source when no successful in-process slice exists.

Each preview or run projection build scans package resources below the root, rejects invalid entries, determines media type, enforces limits, and emits deterministic entries sorted by canonical URI. Source revision and source hash are content-derived. A process-local catalog retains the last successful slice for each source, but the persisted run projection—not that cache—is the recovery boundary.

Azents ships a global source in namespace `azents`. Toolkit Providers may declare one VFS resource root; `ToolkitProvider.slug` is the namespace. A provider source is eligible when the Agent has an enabled AgentToolkit attachment to an enabled ToolkitConfig of that provider type. Credential and connection health do not affect content eligibility.

### Run Projection

`agent_runs.vfs_projection` is nullable JSONB. New runs receive a projection before input-buffer promotion. The ensure operation locks the run row and is idempotent: an existing projection is returned unchanged.

The projection stores:

- schema version, revision ID, projection hash, and creation time;
- selected source IDs, kinds, namespaces, source revisions, and hashes;
- flattened file entries with canonical URI, source identity, content hash, media type, size, and Base64 body;
- bounded diagnostics for optional sources that were unavailable.

The first implementation permits at most 2 MiB per file and 8 MiB total decoded content per projection. `SKILL.md` must be UTF-8 and remains additionally bounded by the existing Skill read limit.

Storing exact bytes on the run makes recovery independent of deployment changes. Inline storage also gives projection content the same retention and deletion lifecycle as its AgentRun. A later schema version may replace inline bodies with immutable object references.

### Run Lifecycle

1. RunExecutor creates or claims a pending/running AgentRun.
2. `VfsProjectionService.ensure_run_projection(...)` builds or returns the persisted projection.
3. Initial input promotion receives the run ID.
4. SkillAction resolution checks filesystem active state for absolute paths and the persisted run projection for `azents://` URIs.
5. Toolkit resolution constructs Skill and Runtime tools.
6. `load_skill` and `import_file` query the same persisted projection by current run ID.
7. Retry, resume, and worker takeover reuse the stored projection.

Old pre-migration runs may have no projection. Their first recovery after deployment uses the same ensure path once; all runs created after deployment are frozen before promotion.

Subagent runs build their own projection from the child Agent and current attachment state. They do not inherit the parent projection.

### Skill Integration

The combined Skill view is an ordered union of:

- the existing filesystem active snapshot;
- managed Skill items parsed from projected `azents://skills/.../SKILL.md` entries.

Filesystem items retain their exact absolute path and source metadata. Managed items use the URI as `skill_path`, the URI directory as `skill_dir_path`, and source metadata from the VFS manifest. Equal slugs are allowed because exact locators differ.

`load_skill(skill_path)` dispatches by locator form. Absolute paths resolve only from filesystem active state. Canonical `azents://` Skill URIs resolve only from the current run projection. There is no cross-kind fallback.

SkillAction creates the existing durable `skill_loaded` event with the exact URI, full selected body, content hash, and bounded source hints. Lowering and transcript replay remain unchanged.

### Composer Preview

While a run is active, the action list uses its persisted VFS projection. While idle, the API builds a non-persisted preview from current release sources and attachment state and combines it with filesystem `latest`.

The preview is advisory. Execution stores only the exact URI in SkillAction and validates it against the newly created run projection. Eligibility changes between preview and execution produce the existing unavailable-Skill error.

### import_file Integration

The existing resolver registry gains `AzentsImportResolver`. It receives current run, Agent, Session, and Workspace identity, canonicalizes the URI, loads the run projection, verifies ownership and exact membership, verifies decoded size and SHA-256, and returns bytes plus media type and basename to the existing Runtime materialization path.

Only `import_file` materializes VFS bytes. `read`, `glob`, `grep`, `write`, and `edit` continue to operate on Runtime paths only.

### Error Handling

- Invalid/non-canonical URI: `invalid_uri`.
- Unsupported authority/mount: `unsupported_mount`.
- URI absent from the run projection: `not_found`.
- Run ownership mismatch: `permission_denied`.
- Invalid Base64, size mismatch, or hash mismatch: `storage_unavailable`.
- Cross-source canonical URI collision: projection construction fails.
- Required release source invalid: projection construction fails when no last-successful in-process slice exists.
- Optional release source unavailable: retain its last successful in-process slice; if none exists, omit it with a bounded diagnostic.

### Security

- URI text never grants access; run projection membership is the authorization capability.
- Physical package paths, credentials, object keys, and presigned URLs are never model-visible.
- Traversal and ambiguous encodings are rejected before lookup.
- Provider content eligibility uses authoritative enabled attachment/config state.
- Runtime destination policy remains owned by existing FileStorage and import path validation.
- Content integrity is verified during source publication and again during import resolution.

## Data Model Changes

- Add nullable JSONB `agent_runs.vfs_projection`.
- Add `vfs_projection` to AgentRunState and repository build/patch behavior.
- Add repository methods to atomically set-if-empty and load the run projection.
- No new public API schema is required; SkillAction continues using `skill_path`.

## Rollout

1. Deploy the nullable column and VFS domain/repository code.
2. Ship release sources and projection construction.
3. Enable combined Skill prompt/action/load behavior.
4. Enable `azents://` import resolution.
5. Validate package data in wheel/build CI.
6. Update current specs after behavior verification.

Rollback is safe because existing filesystem Skills remain independent. Runs that already contain a projection retain inert JSON if older code does not consume it.

## Alternatives Considered

### Store only package revision references

Rejected for the first implementation because recovery after deployment would still require the old package bytes or a new durable blob graph.

### Create normalized source, revision, file, and projection tables immediately

Deferred. The first bounded release use case does not justify the operational and garbage-collection complexity. The logical manifest remains compatible with future normalization.

### Copy packages into Runtime

Rejected because it duplicates immutable content, requires Runtime availability before Skill loading, and conflates logical resources with filesystem state.

### Merge managed Skills into session Toolkit State

Rejected because Toolkit State follows session latest/active lifecycle rather than the AgentRun recovery boundary and would allow later refreshes to affect a resumed run.

## Test Strategy

### E2E Primary Validation Matrix

| Scenario | Expected behavior |
| --- | --- |
| Idle action list | Includes global managed Skill and eligible provider Skill URIs alongside filesystem Skills. |
| Managed Skill action | Creates `skill_loaded` before the user message using the run-frozen body. |
| Direct `load_skill` | Accepts the exact managed URI and returns metadata plus body. |
| Adjacent resource import | `import_file(azents://...)` writes verified bytes to Runtime. |
| Provider disabled between preview and execution | Action fails as unavailable for the new run. |
| Release content changes after run creation | Existing run continues using stored bytes; later run uses new bytes. |
| Subagent run | Builds and uses its own projection without parent inheritance. |
| Filesystem regression | Existing absolute-path discovery, action, and load behavior remains unchanged. |

The primary product verification uses backend-integrated chat/run E2E where a deterministic model fixture can select and invoke the managed Skill and import its resource. If the existing fixture surface cannot deterministically issue both tool calls, API/worker integration tests are the required fallback and the limitation must be recorded in validation evidence.

### Fixture and Prerequisite Support

- Add deterministic bundled Skill resources to the backend package.
- Add test Agent/Toolkit fixtures for one enabled and one disabled provider attachment.
- No live third-party credentials are required because provider content eligibility does not call the provider.
- Runtime import verification requires the normal test Runtime prerequisite; tests without Runtime cover resolver output directly.

### Evidence

Record commands, environment, selected URIs, persisted projection hash, Skill event payload hash, imported file hash, and pass/fail results in the validation PR.

### CI Policy

Unit, repository, migration, package-build, backend integration, and applicable E2E tests are required. Live external-provider tests remain optional and must skip only for missing credentials; all deterministic VFS tests fail normally.

## Open Risks

- JSONB projection size must remain bounded and observable.
- Package build configuration must include non-Python resource files.
- Composer preview and run admission can intentionally differ during concurrent configuration changes; user-facing failure remains explicit.
- Future catalog sources need durable last-successful source revisions rather than the release-only in-process source cache.
