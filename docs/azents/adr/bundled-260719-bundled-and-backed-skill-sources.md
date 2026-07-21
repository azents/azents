---
title: "Run-Scoped Azents Virtual Filesystem for Managed Skills and Resources"
created: 2026-07-19
tags: [architecture, backend, engine, toolkit, skill, storage, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: bundled-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0168-release-bundled-and-provider-backed-skill-sources.md"
---

# bundled-260719/ADR: Run-Scoped Azents Virtual Filesystem for Managed Skills and Resources

## Context

[filesystem-260701/ADR](./filesystem-260701-filesystem-skill-projection-revisions.md) introduced filesystem-authored Agent and Project Skill packages and session-scoped Skill projection revisions. The current implementation scans the Agent Workspace and registered Project paths, stores complete `SKILL.md` snapshots in session-bound Toolkit State, and uses an adopted projection for prompt rendering, Skill actions, and `load_skill`.

Azents also needs files that are managed outside the Agent Runtime filesystem:

- release-bundled global Skills;
- release-bundled Skills owned by Toolkit Providers;
- future Workspace-managed or catalog-published Skills;
- future Azents-managed references, templates, scripts, assets, or other file-oriented resources.

Representing each new source as a Skill-specific body field would make package resources inaccessible and would require another content contract for every future use case. Copying every managed package into each Agent Runtime would make availability depend on Runtime allocation, duplicate immutable release content, and still leave future DB- or object-storage-backed sources with a separate path.

Azents therefore needs one generalized, read-only virtual filesystem that projects eligible managed files into a stable URI namespace for each run.

## Accepted Product Direction

1. Azents provides a read-only virtual filesystem using the `azents://` URI scheme.
2. The virtual filesystem represents Azents-managed remote files and is not a Runtime filesystem mount.
3. Every Azents-managed Skill entrypoint is located at:

   ```text
   azents://skills/{namespace}/{skill}/SKILL.md
   ```

4. `load_skill` accepts that URI directly.
5. `import_file` accepts `azents://` file-location URIs and materializes the selected file into the Agent Runtime when a Runtime is available.
6. The virtual filesystem is generalized beyond Skills and may expose other top-level mounts in the future.
7. Every run receives an immutable virtual filesystem projection.
8. Existing Agent and Project filesystem Skills retain their current absolute-path behavior.

## Decision 1: Define `azents://` as a Read-Only File-Location Namespace

`azents://` identifies logical files supplied by Azents. It does not expose physical package paths, DB rows, object-storage keys, presigned URLs, or Runtime paths.

The generalized URI shape is:

```text
azents://{mount}/{path...}
```

The first mount is `skills`:

```text
azents://skills/azents/deep-research/SKILL.md
azents://skills/github/review-pull-request/SKILL.md
azents://skills/github/review-pull-request/references/checklist.md
azents://skills/github/review-pull-request/templates/review.md
```

In URI terms, the mount is the authority component and the remaining segments form the virtual path. Future mounts may be added without changing the resolver contract, for example:

```text
azents://knowledge/{namespace}/{resource...}
azents://templates/{namespace}/{resource...}
```

The first version is read-only. Producers publish immutable file revisions; consumers can resolve or import them. Creating, updating, moving, deleting, or writing back through `azents://` is outside this ADR.

A canonical URI:

- uses the exact lowercase `azents` scheme;
- has one registered lowercase mount authority;
- contains an absolute slash-separated virtual path;
- contains no userinfo, port, query, or fragment;
- rejects empty, `.` and `..` segments, encoded path separators, backslashes, and ambiguous alternate encodings;
- treats virtual path case as significant;
- normalizes to one canonical string before identity, collision, or permission checks.

Producer validation owns the detailed segment grammar. Namespace and Skill segments must be stable URL-safe slugs. File names such as `SKILL.md` remain case-sensitive.

## Decision 2: Persist a Flattened, Self-Contained Projection on Each Run

The first implementation stores the complete authorized projection in nullable JSONB on `agent_runs`. The projection contains immutable source metadata and a flattened entry for every selected file:

```text
schema_version
revision_id
projection_hash
created_at
sources[]:
  source_id
  source_kind
  namespace
  source_revision_id
  source_hash
entries[]:
  canonical_uri
  source_id
  source_revision_id
  content_hash
  size_bytes
  media_type
  body_base64
```

The flattened representation is deliberate. It lets run creation commit the authorization decision and exact bytes together, makes worker recovery independent of the currently deployed package or mutable catalog pointers, and lets run deletion or retention own projection garbage collection without a second reference graph.

The first release enforces bounded per-file and total-projection sizes. This makes inline JSONB appropriate for the initial text-oriented Skill, reference, template, and script packages. A future storage revision may replace `body_base64` with an immutable object reference for larger binary content, but must preserve the same run-scoped manifest and content-hash contract.

A virtual URI is meaningful only through an authorized run projection. The resolver does not treat the URI as a globally readable object key and does not fetch an arbitrary network location derived from URI text.

## Decision 3: Build One Immutable VFS Projection for Each Run

Each `AgentRun` owns a virtual filesystem projection selected before model-visible run context, Skill preparation, or Runtime tools may consume `azents://` files. `RunExecutor` ensures the projection immediately after it creates or claims the pending/running run and before it calls input-buffer promotion. The ensure operation locks the run row, returns an existing projection unchanged, and writes a new projection only when the column is empty.

The projection is bound to:

```text
run_id
agent_id
session_id
workspace_id
projection_revision_id
projection_hash
entries[]
```

The same projection is used throughout that run for:

- the Azents-managed Skill prompt index;
- `load_skill` URI resolution;
- SkillAction validation and body snapshotting;
- `import_file(uri="azents://...")`;
- retries, worker restart recovery, and run resume.

The projection never switches in the middle of a run. Provider refresh, Toolkit attachment changes, catalog publication, application deployment, and mutable latest pointers can affect later runs only.

The run manifest remains available for the lifetime of the retained `AgentRun`. Durable Skill events snapshot the selected `SKILL.md` body and required metadata, so transcript replay does not require a later live VFS lookup. Deleting a run deletes its inline projection through the existing row lifecycle; no independent file-object garbage collector is required in the first implementation.

A child or subagent run receives its own projection based on that run's Agent, Workspace, execution mode, and enabled Toolkit attachments. It does not inherit the parent's projection. A pre-created child pending run may have no projection until its worker claims it, but the same pre-promotion ensure boundary applies before any child input is converted to events.

This run-scoped VFS lifecycle is separate from the existing filesystem Skill `latest` and `active` lifecycle. Filesystem Skill behavior remains governed by [filesystem-260701/ADR](./filesystem-260701-filesystem-skill-projection-revisions.md).

## Decision 4: Use Source Providers to Publish Immutable File Trees

A VFS source provider publishes an immutable logical file tree plus source metadata. The provider boundary is generalized and does not depend on Skill-specific fields.

Conceptually:

```text
VfsSourceProvider
  source_id
  source_kind
  namespace
  produce_revision(context) -> VfsSourceRevision

VfsSourceRevision
  source_revision_id
  source_hash
  files[]
```

Initial source kinds are:

- Azents global release bundle;
- Toolkit Provider release bundle.

Future source kinds may include:

- Workspace-managed packages;
- user or organization catalog versions;
- generated or curated Azents resource collections.

Release-bundled sources read application package resources. They are not copied into every Agent Runtime and are not seeded into mutable DB rows as their canonical source.

Each `ToolkitProvider` owns the release-bundled files associated with that Toolkit type. `ToolkitProvider.slug` supplies the stable content namespace. Global bundled files use the `azents` namespace.

Representative paths are:

```text
azents://skills/azents/deep-research/SKILL.md
azents://skills/github/review-pull-request/SKILL.md
```

The VFS namespace identifies the content publisher or provider, not a concrete Workspace ToolkitConfig. When the GitHub Toolkit is attached with ToolkitConfig slug `corp-github`, the Skill URI remains:

```text
azents://skills/github/review-pull-request/SKILL.md
```

Skill package content and URI remain stable across Workspaces and concrete ToolkitConfig slugs. The initial release projection records source identity rather than a concrete Toolkit tool prefix; managed Skill content must therefore use provider-stable instructions instead of assuming a Workspace-local ToolkitConfig slug. A future binding-aware package contract may add explicit binding metadata without changing canonical URIs.

A Toolkit-owned source is eligible when the Agent has an enabled `AgentToolkit` attachment to an enabled `ToolkitConfig` of the owning Toolkit Provider type. Eligibility does not depend on transient credentials, network health, connection setup, or whether the Toolkit resolved successfully for the current run.

## Decision 5: Require a Single Owner for Every Canonical URI

A completed run projection maps each canonical URI to exactly one immutable projected file entry.

If two eligible source revisions publish the same canonical URI with different ownership or content, projection construction reports a collision instead of applying hidden source precedence. A provider may deduplicate identical files inside its own revision before publication, but cross-source path ownership must remain explicit.

Source revisions and projection entries are sorted deterministically before hashing. The projection hash covers canonical URI, content hash, media type, size, and source revision identity.

## Decision 6: Keep `load_skill(skill_path)` Compatible with Both Locator Forms

The existing model-visible tool input field remains `skill_path` to preserve the current Skill and SkillAction contract. Its accepted locator forms become:

```text
/workspace/agent/.../SKILL.md
azents://skills/{namespace}/{skill}/SKILL.md
```

Prompt entries and composer Skill actions carry the exact locator in the existing `skill_path` field.

Resolution is explicit by locator kind:

- an absolute POSIX path resolves only against the existing active filesystem Skill projection;
- an `azents://skills/.../SKILL.md` URI resolves only against the current run's VFS projection.

`load_skill` does not translate filesystem Skills into VFS URIs, does not resolve an `azents://` URI from a mutable latest catalog, and does not fall back to live package or Runtime reads.

For an Azents-managed Skill, `load_skill` resolves the immutable file entry from the current run projection, validates UTF-8 text and the Skill metadata contract, and returns the full `SKILL.md` body with bounded metadata including:

- canonical Skill URI;
- content hash;
- run VFS projection revision;
- source and source revision;
- publisher namespace and source identity.

SkillAction preparation uses the same run projection and snapshots the loaded body and required metadata into durable model input as required by [skill-260712/ADR](./skill-260712-skill-actions-as-producing-preparation.md).

## Decision 7: Extend `import_file` Through Its Scheme Resolver Registry

`import_file` adds an `azents` resolver alongside the existing `exchange` and `artifact` resolvers.

```text
import_file(
  uri="azents://skills/github/review-pull-request/templates/review.md",
  path="/workspace/agent/review-template.md"
)
```

The resolver:

1. parses and canonicalizes the URI;
2. loads the VFS projection bound to the current run;
3. verifies Agent, Session, Workspace, and run ownership;
4. finds the exact projected entry;
5. decodes the immutable body stored in that projected entry;
6. verifies decoded size and content hash;
7. returns bytes, media type, source URI, and final path-segment file name to the existing Runtime materialization path.

The `azents` resolver is injected with current `run_id` context when Runtime tools are constructed for a turn. It must not retain a stale run identifier in a long-lived Toolkit instance.

`import_file` remains the boundary that copies remote content into the Runtime filesystem. Ordinary Runtime `read`, `glob`, `grep`, `write`, and `edit` tools continue to accept Runtime paths only. They do not become VFS clients.

VFS access is independent of Runtime availability, but materialization requires Runtime file tools. An Agent without Runtime tools can still use `load_skill` for projected Skill text and cannot import adjacent resources.

The resolver enforces:

- exact manifest membership;
- canonical path checks before lookup;
- configured per-file size limits;
- bounded text metadata;
- no redirects or arbitrary outbound fetches;
- no path traversal into the Runtime destination;
- no write-back to the VFS.

## Decision 8: Preserve Existing Filesystem Skill Behavior

Agent and Project filesystem Skills continue to use the existing conventions:

```text
/workspace/agent/.azents/skills/{slug}/SKILL.md
{project.path}/.agents/skills/{slug}/SKILL.md
{project.path}/.claude/skills/{slug}/SKILL.md
```

They retain:

- Runtime-connected discovery;
- session-scoped filesystem Skill projection state;
- exact absolute `SKILL.md` path identity;
- current `latest` and `active` adoption behavior;
- existing Project and source labels;
- adjacent Runtime resource access through ordinary file tools;
- separate entries when `.agents` and `.claude` define Skills with the same slug.

Filesystem Skills are not copied into `azents://`, and VFS packages are not copied into Agent or Project Skill directories. Absolute paths and `azents://` URIs are disjoint locator forms, so equal Skill slugs do not create an identity collision.

The combined Skill prompt and action list may contain both forms:

```text
- **code-review**: Review this repository.
  Path: `/workspace/agent/project/.agents/skills/code-review/SKILL.md`
- **review-pull-request**: Review a GitHub pull request.
  Path: `azents://skills/github/review-pull-request/SKILL.md`
```

## Decision 9: Keep Release Source Loading Local and Freeze Its Result on the Run

The first implementation has only release-bundled global and Toolkit Provider sources. Projection construction reads those sources from local Python package resources and performs no provider API call, network refresh, credential lookup, or mutable catalog resolution.

A process-local release catalog keeps one last-successful slice per source. Each preview or run projection build rescans the eligible package roots under a lock:

- a successful scan with files replaces that source's cached slice;
- a successful empty scan replaces it with an empty slice;
- a failed scan may reuse the previous successful slice from the same process;
- if no prior slice exists, a required source failure aborts projection construction while an optional source is omitted with a bounded diagnostic;
- attachment or enablement changes affect source eligibility for later previews and runs without mutating an existing run projection.

This cache is an availability optimization, not the recovery boundary. It is not persisted and does not claim to survive process restart or deployment. The self-contained projection stored on `AgentRun` is the durable boundary: once the ensure operation succeeds, retries, worker takeover, and resume use only those stored source records and file bytes.

Future Workspace-managed, catalog, or object-storage-backed sources require their own durable publication and latest-successful revision model before they can participate. That source synchronization contract is deliberately deferred and must not introduce remote refresh I/O into `load_skill`, SkillAction promotion, or `import_file` resolution.

## Decision 10: Use Publisher-Owned Skill Namespaces

The `skills` mount uses stable publisher-owned namespaces rather than Workspace-local ToolkitConfig slugs. The initial namespaces are owned directly by Azents or a registered Toolkit Provider:

```text
azents://skills/azents/deep-research/SKILL.md
azents://skills/github/review-pull-request/SKILL.md
```

Namespace ownership follows these initial rules:

- Azents reserves the `azents` platform namespace.
- A Toolkit Provider owns the namespace equal to its stable provider slug.
- Mutable display names, Workspace names, user names, and ToolkitConfig slugs do not define or rewrite the namespace.
- A Skill package slug is unique within its source namespace.
- Local aliases are not part of the first implementation.

The run projection records source ID, source kind, namespace, source revision, hashes, and exact file content separately from the URI. URI text is therefore stable identity for the projected path, while projection membership remains the authorization decision.

Workspace-managed private publishers, catalog versions, Workspace or Agent assignments, namespace transfer, aliases, update channels, and version pinning are outside this ADR's implemented scope. Those features require a separate design for durable publication, namespace ownership, assignment precedence, and latest-successful version selection.

## Decision 11: Treat Composer Actions as a Preview, Not a Run Snapshot

The composer action list may be requested while no run exists. It therefore combines the existing filesystem Skill action snapshot with a fresh, non-persisted VFS preview built from current release sources and current Agent Toolkit attachment state.

The preview uses the same URI validation, source eligibility, collision detection, parsing, and deterministic ordering code as run projection construction. It is advisory. Selecting a previewed Skill stores only the exact URI in `SkillAction`; the subsequent run validates that URI against the run projection created before input promotion. If eligibility changed between preview and execution, the action produces the existing unavailable-Skill system error instead of reading stale preview content.

While a run is active, composer actions use that run's persisted VFS projection so action selection, `load_skill`, and `import_file` share the same immutable view.

## Decision 12: Package Release Sources and Provider Ownership

Release resources are normal Python package data below a dedicated `azents.resources.vfs` tree. A release source definition specifies a stable source ID, source kind, URI namespace, package, and package-relative root. Source publication walks files only below that root, rejects symlinks and invalid paths, determines media type, applies size limits, and hashes sorted entries into one immutable source revision.

Azents owns a global release source in namespace `azents`. A Toolkit Provider may declare one package-relative VFS root; its provider slug is the namespace and ownership boundary. The projection builder includes a provider source only when the Agent has an enabled attachment to an enabled ToolkitConfig of that provider type. Credentials and provider connection health are intentionally not consulted.

Release source loading keeps independent last-successful slices within the process: a successful scan replaces that source slice, a successful empty scan removes its files, and a failed rescan retains the prior successful slice when one exists. On a fresh process with no retained slice, an invalid required source fails preview or run projection construction. Package-build validation verifies that required bundled resources are shipped, while the persisted run projection remains the durable recovery boundary across worker restart or deployment.

## Security and Permission Boundaries

- A URI alone grants no access.
- Every resolution is authorized through the run projection and its Agent, Session, and Workspace ownership.
- Release source loading validates logical paths and content before a revision is merged into a preview or run projection.
- Toolkit-bound source eligibility derives from authoritative Agent/Toolkit attachment state.
- Future Workspace and catalog providers must publish only versions authorized for the run's Workspace, Agent, user, and execution mode.
- Credentials, physical object keys, package installation paths, and presigned URLs are not included in model-visible URIs or metadata.
- VFS file content is read-only and immutable after publication.

## Failure Behavior

- Invalid or non-canonical URI: fail with `invalid_uri`.
- Unknown VFS mount: fail with `unsupported_mount`.
- URI absent from the current run projection: fail with `not_found` without consulting a mutable latest source.
- Projection ownership mismatch: fail with `permission_denied`.
- Missing or corrupt inline entry content: fail with `storage_unavailable` and preserve the run projection for diagnosis.
- Duplicate canonical URI during projection construction: reject the candidate projection and report a provider/source collision.
- Runtime unavailable during `import_file`: return the existing Runtime tool failure; do not reinterpret it as VFS absence.
- Filesystem Skill failures continue to follow [filesystem-260701/ADR](./filesystem-260701-filesystem-skill-projection-revisions.md) and do not remove valid VFS entries.

## Consequences

- Azents-managed packages can contain `SKILL.md`, references, templates, scripts, and assets without eagerly copying every file into Runtime.
- `load_skill` and `import_file` observe one immutable content view for the entire run.
- Worker restart and run resume remain independent of application-process memory because the run projection stores exact file bytes inline.
- The Skill subsystem becomes a consumer of a generalized VFS rather than the owner of a Skill-only remote resource format.
- Existing filesystem Skill authoring remains unchanged.
- Inline projection retention and deletion follow the existing AgentRun row lifecycle; no independent VFS garbage collector is required in the first implementation.
- Runtime tool construction needs current-run VFS resolver injection.
- Source publication and run projection construction need deterministic collision and failure diagnostics.

## Rejected Alternatives

### Copy every managed package into each Agent Runtime

This couples availability to Runtime allocation, duplicates immutable content, and makes future non-package sources require another distribution path.

### Store only `SKILL.md` bodies in Skill projection items

This does not provide a package resource model and would require another API for references, templates, scripts, and assets.

### Resolve `azents://` from mutable latest source state at tool-call time

This allows `load_skill`, SkillAction, and `import_file` to observe different revisions in the same run.

### Expose VFS files directly through ordinary Runtime file tools

This conflates remote logical files with Runtime paths and would require implicit network/materialization behavior inside every file tool.

### Rewrite filesystem Skill paths into VFS URIs

This changes existing filesystem authoring, identity, resource access, and projection behavior without providing a product benefit.

## Relationship to Existing ADRs

This ADR extends [filesystem-260701/ADR](./filesystem-260701-filesystem-skill-projection-revisions.md) with an additional locator and resource system for Azents-managed files. [filesystem-260701/ADR](./filesystem-260701-filesystem-skill-projection-revisions.md) remains authoritative for Agent and Project filesystem Skill sources and their session projection lifecycle.

This ADR supersedes [filesystem-260701/ADR](./filesystem-260701-filesystem-skill-projection-revisions.md) only where [filesystem-260701/ADR](./filesystem-260701-filesystem-skill-projection-revisions.md) limits non-filesystem platform Skills to a future unspecified source and projects only `SKILL.md` content. It does not change existing filesystem source conventions or path-based Skill behavior.

[skill-260712/ADR](./skill-260712-skill-actions-as-producing-preparation.md) continues to govern SkillAction preparation. For an `azents://` Skill, the selected body and metadata come from the immutable VFS projection owned by that run.

## References

- [filesystem-260701/ADR: Filesystem Skill Projection Revisions](./filesystem-260701-filesystem-skill-projection-revisions.md)
- [skill-260712/ADR: Treat Skill Actions as Model-Producing Preparation](./skill-260712-skill-actions-as-producing-preparation.md)
- [file-260601/ADR: File Media Resource Lifecycle](./file-260601-file-media-resource-lifecycle.md)

## Migration provenance

- Historical source filename: `0168-release-bundled-and-provider-backed-skill-sources.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
