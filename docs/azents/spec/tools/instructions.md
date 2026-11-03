---
title: "Instructions and Skills"
created: 2026-11-04
tags: [wiki]
---

# Instructions and Skills

Owns filesystem instructions, Claude rules, managed Skill materialization and per-context deduplication. Project eligibility is established before loading instructions; source text does not grant new execution authority.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Projects, working folders and worktrees](../runtime/projects.md)
- [Toolkits](../domain/toolkit.md)
- [Toolkit State and execution binding](../execution/tool-state.md)
- [File exchange and storage](../flow/file-exchange-storage.md)

## Managed Skill VFS

`load_skill` remains available when the current filesystem and managed Skill
inventories are empty. Prompt inventory and invocation still enforce the current
Runtime capability and exact active filesystem or Run VFS projection; exposing
the loader does not grant access to an unprojected Skill.

The global `azents` source includes the `browser` Skill and its focused
open/observe, actions/human-help and captures/files references. The three fixed
`browser_open`, `browser_observe` and `browser_act` tools bind trusted current
Session/Runtime authority; neither model arguments nor Skill instructions select
another Session or profile. The Skill is guidance inside the existing immutable
Run projection, not a new permission, ToolkitConfig or Runtime installer.
Browser tools are projected only after the Agent's default-off `browser_enabled`
setting is explicitly enabled. Their current setting is checked again on
invocation. Chat activities categorize all three public names under the dedicated
localized Browser group rather than Other.
See the [Session Browser flow](../flow/session-browser.md).

Azents-managed Skill packages use a read-only virtual filesystem distinct from the Agent Runtime filesystem. The first registered mount is `skills`, and every managed Skill entrypoint has the canonical form:

```text
azents://skills/{namespace}/{skill}/SKILL.md
```

The `azents` namespace is reserved for approved global release-bundled packages. A Toolkit Provider may declare one approved release resource root under the namespace equal to its stable Provider slug, such as `github`. A Provider package is eligible only when the Agent has an enabled attachment to an enabled ToolkitConfig of that Provider type. Credential state, provider connection health, and the Workspace-local ToolkitConfig slug do not change content eligibility or rewrite the URI. The initial projection records source identity but not a concrete ToolkitConfig tool prefix, so managed package instructions cannot assume one Workspace-local prefix.

Every AgentRun stores one self-contained immutable Skills VFS projection in
`agent_runs.vfs_projection`; this does not store the live Memory tree. The
projection records schema/revision identity, deterministic source records,
canonical entries, hashes, media types, decoded sizes, and Base64 bodies.
Release sources are scanned from local package resources. A process-local catalog
may retain the last successful source slice, but recovery authority is the
persisted projection. Retries, takeover, and resume never replace it with current
package bytes. Existing hashes/source revisions and the at-most-eight-MiB
projection bound remain unchanged.

The Skill Toolkit combines managed entrypoints with the existing filesystem Skill snapshot. Filesystem Skills keep absolute `SKILL.md` paths and the session-scoped `latest`/`active` adoption lifecycle. Managed Skills use their exact `azents://` URI as `skill_path`; equal slugs remain separate when their locators differ. `load_skill` dispatches absolute paths only to the active filesystem projection and canonical managed URIs only to the current run VFS projection, with no cross-source fallback.

Filesystem Skill synchronization obtains the Session Project source set through a
completed Project operation repository read. Runtime directory listing and Skill
file reads occur after that database transaction closes. The resulting projection
is persisted through a later completed Skill State repository operation; the
projection service receives neither a session manager nor a session-taking
Project repository.

The currently approved global release bundle contains `azents://skills/azents/skill-creator/SKILL.md`. It guides Agents to create or repair filesystem Skills through the Shell Runtime tools. It requires the standard `name` and non-empty `description` frontmatter fields, treats `summary` as non-discoverable metadata, validates the saved file before reporting success, and explains that runtime Skill projection refresh completes after the current run.

The Skill owner contributes zero or more definitions to the shared closed
TurnAction composer catalog. Discovery uses a fresh non-persisted VFS preview
while the Session is idle and the active AgentRun projection while it is running.
A selected managed SkillAction stores only its exact URI. Run input preparation
validates that URI through the same Skill-owned capability against the projection
ensured for the active run before the final Mailbox database transaction. The
final transaction re-locks the Session and FIFO head; a filesystem Skill also
revalidates the exact active projection item before emitting the durable
`skill_loaded` event and deleting the source Mailbox row.
Eligibility drift between an idle preview and run creation therefore produces the
normal unavailable-Skill error rather than reading stale preview content.

`import_file` registers an `azents` resolver alongside `exchange` and `artifact`.
For importable Skills it validates the canonical URI, current run ownership,
exact projection membership, Base64 content, decoded size, and SHA-256 hash
before passing bytes to Runtime materialization. Generic `read`, `glob`, and
`grep` resolve managed URIs through readable storage without import. Runtime
mutation adapters remain filesystem-only, and foreground Memory has no import/transfer
capability. Only the materialized Runtime copy follows Runtime path retention
rules; the Skill source remains in the retained immutable AgentRun projection.

Root and subagent executions use the same admission contract. Each AgentRun independently ensures a projection for its resolved Agent, Session, and Workspace context rather than inheriting another run's projection.

## AGENTS.md Instruction Loading

Shell runtime treats AGENTS.md as a successful `read` tool result appendix, not as a Toolkit/system prompt fragment.

- Root instruction candidate is `<current-agent-workspace>/AGENTS.md` for read targets under the current Runner-reported root.
- Registered Project instruction candidates are `AGENTS.md` files from the Project root to the read target directory, parent-to-child.
- Candidate content is read fresh from Runtime file storage only while handling a successful `read` result. AGENTS.md content is not cached.
- Missing and non-file candidates are ignored and cached as discovery misses for five seconds within the Session-managed Toolkit instance, avoiding repeated stat operations during read bursts.
- The Toolkit instance serializes appendix processing with a Session-local lock. After acquiring it, each caller reloads persistent dedupe state and removes already-appended paths before stat/read I/O, so parallel reads append and read each candidate at most once per dedupe lifecycle.
- Reading an `AGENTS.md` file does not append that same file as its own appendix.
- `write`, `edit`, `delete`, `grep`, `glob`, `import_file`, `present_file`, and `read_image` do not append AGENTS.md instructions in this contract.
- Toolkit State stores only a sorted dedupe path list under namespace `builtin`, state name `agents_md_appendix_dedupe`; it does not store AGENTS.md content.
- `on_session_compact` clears both the dedupe path list and the local missing-candidate cache so future reads may discover and append current AGENTS.md content again.
- Appendix content uses the existing AGENTS.md content cap and is appended after the original read output in a `<system-reminder>` block.
- Prompt builds and toolkit startup must not start or touch Runtime solely to discover AGENTS.md.

The shell runtime prompt contains only fixed guidance that read results may include `<system-reminder>` AGENTS.md appendix blocks and that the agent should follow them for the paths they apply to.

## Claude Rules Instruction Loading

The `claude_rules` auto-bound runtime Toolkit treats `.claude/rules/**/*.md` files as successful `read` tool result appendices. It exposes no model-visible tools and no Toolkit prompt fragments.

Activation and context:

- `ClaudeRulesToolkitProvider` is auto-bound whenever runtime tools are enabled.
- The Toolkit shares the runtime instruction context prepared for file-instruction loaders: Runtime `FileStorage`, sorted registered Projects, and runtime-scoped agent/session identity.
- Prompt builds and toolkit startup must not start or touch Runtime solely to discover Claude rules.

Candidate roots:

- Workspace rules are discovered under `<current-agent-workspace>/.claude/rules/**/*.md` for read targets under the current Runner-reported root.
- If the read target is inside a registered Project, Project rules are also discovered under `<project.path>/.claude/rules/**/*.md`.
- Workspace-root rules are evaluated before Project-root rules.
- Nested `.claude/rules` roots below arbitrary subdirectories are not discovered.
- Only Markdown files (`.md`) are candidates.
- Each supported root's sorted Markdown path list is cached for five seconds within the Session-managed Toolkit instance. The cache stores discovery paths only; rule content, parsed frontmatter, and path-match results remain uncached.
- Missing rule roots and repo/config-level issues are skipped quietly.

Matching and safety:

- A rule without `paths` frontmatter is global for its source owner root.
- `paths` frontmatter may be a string or a list of strings. Unsupported shapes or malformed frontmatter cause the rule to be skipped quietly.
- Relative `paths` globs match paths relative to the source owner root (the current Runner-reported Agent Workspace for workspace rules, `<project.path>` for Project rules).
- Absolute `paths` globs match normalized absolute runtime paths.
- Glob matching is path-segment aware; `**` matches zero or more path segments.
- Discovered rules are ordered deterministically by normalized runtime path within each root.
- If multiple candidates resolve to the same real path, the first root-order occurrence is kept and later duplicates are skipped.
- A candidate whose resolved real path is outside its source owner root is skipped.
- Reading a rule file does not append that same file as its own appendix.

Appendix and state:

- Candidate content is read fresh from Runtime file storage only while handling a successful `read` result.
- The Toolkit instance serializes discovery, persistent dedupe reload, pre-I/O path filtering, stat/read work, state update, and rendering with a Session-local lock. A parallel caller that acquires the lock later skips paths appended by the first caller before content I/O.
- `write`, `edit`, `delete`, `grep`, `glob`, `import_file`, `present_file`, and `read_image` do not append Claude rules in this contract.
- Rule content is rendered raw, including frontmatter, inside a `<system-reminder>` appendix after the original read output.
- Claude rules use their own per-file content cap and truncation marker.
- Toolkit State stores only a sorted dedupe path list under namespace `claude_rules`, state name `claude_rules_appendix_dedupe`; it does not store rule file content.
- `on_session_compact` clears both the dedupe path list and the local rule-path discovery cache so future reads may discover and append current Claude rules again.
- Runtime/FileStorage communication failures after a successful read are logged as errors and leave the read output unchanged.
- Toolkit State failures and code bugs are not swallowed by `ClaudeRulesToolkit`; they flow to the runtime hook dispatcher fail-open path.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/resources/vfs`](../../../../python/apps/azents/src/azents/resources/vfs)
- [`python/apps/azents/src/azents/engine/tools`](../../../../python/apps/azents/src/azents/engine/tools)
- [`python/apps/azents/src/azents/services/toolkit`](../../../../python/apps/azents/src/azents/services/toolkit)
