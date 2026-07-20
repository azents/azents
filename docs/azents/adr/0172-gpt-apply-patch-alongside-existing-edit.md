---
title: "ADR-0172: Add GPT-aligned apply-patch alongside the existing edit tool"
created: 2026-07-20
tags: [architecture, backend, engine, runtime, tools]
---

# ADR-0172: Add GPT-aligned apply-patch alongside the existing edit tool

## Context

Azents currently exposes `edit`, `write`, and `delete_file` as model-visible file
function tools. `edit` replaces one exact string pattern in one UTF-8 file per call. Large
GPT coding edits therefore require repeated tool calls for multiple hunks or files.

OpenAI GPT and Codex models have direct prompting and harness evidence for the V4A patch
format. Claude and Gemini production harnesses instead use exact replacement editors, and
cross-model evidence does not establish V4A as their best editing representation.

Azents will add a GPT-specific `apply_patch` function tool without changing the existing
`edit` contract or introducing provider-hosted, custom, freeform, partially executed, or
stream-preview tool semantics.

## Decision

### ADR-0172-D1 — Model-specific editing tools

Only GPT-family models receive `apply_patch`. Its ordinary JSON-schema function input is:

- `base_path`: an absolute Runtime directory.
- `patch`: one completed V4A patch string.

Every supported model retains the existing `edit` tool. GPT models may use `edit` as a
fallback for small exact replacements or after a patch failure. Claude and Gemini do not
receive `apply_patch` in the initial design.

`edit` and `apply_patch` are distinct canonical tools, not model-facing aliases for one
tool. The existing `read`, `write`, `edit`, and `delete_file` names remain unchanged.

### ADR-0172-D2 — Preserve the existing `edit` contract

Do not change the current `edit` schema or behavior:

- `path`
- `old_string`
- `new_string`
- `replace_all`

Renaming `path` to Claude's `file_path` does not provide enough model-alignment benefit to
justify a compatibility change. Exact and unique matching behavior remains unchanged.

### ADR-0172-D3 — Base path and relative patch paths

`base_path` must be an absolute Runtime directory. Every path inside the V4A patch must
be a non-empty relative path.

- Reject absolute patch paths.
- Reject lexical `..` components.
- Resolve and validate every source, destination, and parent below the canonical
  `base_path`.
- A patch cannot span multiple base roots; use separate calls instead.

### ADR-0172-D4 — Initial file operations

The first version supports:

- `*** Add File:`
- `*** Update File:`
- `*** Delete File:`

Move and rename are excluded. Models use the existing file-management or shell tools for
those operations. One file may appear in only one file-operation block per patch. An
update block may contain multiple hunks.

### ADR-0172-D5 — V4A subset and text representation

The parser requires one complete envelope:

- `*** Begin Patch`
- one or more file operations
- `*** End Patch`
- no trailing non-whitespace content

Update hunks use optional `@@ <anchor>` headers and lines prefixed with one space, `-`, or
`+`. `*** End of File` is an end-position assertion, not a newline instruction.

Every update hunk for a non-empty file must include at least one existing context or
removed line. A pure addition is allowed only for an empty existing file. Insertions into
a non-empty file must include existing context that fixes the position.

Updates preserve the source file's uniform LF or CRLF convention and its existing final
newline state. Added files use LF and end with a newline. Mixed-newline source files are
rejected in the first version.

### ADR-0172-D6 — Exact and unique context matching

Patch application uses exact content matching after logical LF/CRLF line splitting.
Whitespace, indentation, Unicode punctuation, and token content are not normalized.

- A context anchor, when present, must match exactly and uniquely in the remaining source
  range.
- Each hunk's existing sequence must match exactly and uniquely after the previous hunk.
- Hunk matches must be ordered and non-overlapping in the original snapshot.
- Replacements are calculated from the original snapshot and applied in reverse offset
  order.

Approximate matching may produce a diagnostic hint, but it never authorizes mutation.

### ADR-0172-D7 — Eligible files and destructive defaults

The first version supports UTF-8 regular files only.

- Reject directories, special files, binary or invalid UTF-8 files, mixed newline files,
  and final-path symlinks.
- Canonical path resolution must remain below the canonical base directory.
- Add fails if the destination already exists.
- Update and delete fail if the source does not exist.
- Delete never operates recursively.
- Update preserves the existing file mode where supported.
- Add creates missing parent directories below `base_path` and uses normal Runtime umask
  behavior.

### ADR-0172-D8 — Runtime Runner owns patch execution

Implement one dedicated Runtime Runner patch operation rather than composing remote
`FileStorage.get()`, `put()`, and `delete()` calls in the Engine.

The Runner owns parsing, path validation, source reads, staging, revalidation, mutation,
and the committed-delta result. The Engine function tool owns model eligibility, request
construction, timeout/error mapping, and terminal tool-result publication.

This keeps one Runtime generation and one local filesystem operation boundary for each
visible tool call.

### ADR-0172-D9 — Preflight and optimistic concurrency

Before the first mutation, the Runner must:

1. parse and validate the complete patch;
2. resolve and validate every path;
3. read all source snapshots and relevant destination state;
4. compute every final update and add payload;
5. validate every context match and destructive precondition;
6. stage all added and updated file contents;
7. capture content hashes and lexical file metadata; and
8. revalidate all observed paths immediately before commit begins.

A preflight or pre-commit revalidation failure guarantees that no patch mutation occurred.
During commit, each path is revalidated immediately before its operation. A concurrent
change discovered after earlier commits produces a partial failure under D10.

### ADR-0172-D10 — Preserve committed changes after a partial failure

A regular filesystem cannot guarantee an atomic multi-path transaction. Azents does not
attempt rollback after commit begins because rollback is another non-atomic sequence that
can fail or overwrite concurrent work.

- Added and updated contents are fully staged before commit.
- Add and update use an atomic per-path visibility primitive where the Runtime filesystem
  supports it.
- Deletes run after successful add and update commits, reducing destructive partial
  states.
- Operations use a deterministic order and stop at the first observed failure.
- Previously committed changes remain in place.
- The call is terminally failed when any operation fails.
- The failure reports committed changes, the failed operation, not-attempted operations,
  and whether the observed delta is exact.

No result or UI message describes the multi-file operation as atomic.

### ADR-0172-D11 — Tool results and retry diagnostics

Successful output includes action and path summaries plus added and removed line counts.

Failures use stable phase and reason codes for parse, preflight, concurrency, and commit
failures. The model-visible result identifies:

- `phase`
- `reason`
- `applied`
- `failed`
- `not_attempted`
- `exact`
- a concise retry hint when the source remained unchanged

A partial commit is a failed tool result, not a successful result containing a warning.
The complete raw patch is not repeated in the result or logs.

### ADR-0172-D12 — Bounded resource use

The implementation uses explicit, tested bounds for patch bytes, file count, hunk count,
per-file source and output bytes, aggregate bytes, path length, and operation duration.
Initial constants may be adjusted from production evidence without changing the semantic
contract. Limit failures occur during preflight and perform no mutation.

### ADR-0172-D13 — Existing tool coexistence

No existing file tool is deprecated.

GPT prompting directs models to:

- use `edit` for one small exact replacement;
- use `apply_patch` for multiple hunks, multiple files, or combined add/update/delete;
- use `write` for an intentional complete-file replacement when a patch provides no
  safety or token benefit;
- use `delete_file` for a standalone direct deletion; and
- use `exec_command` only when a dedicated file tool does not express the operation.

Claude and Gemini continue to use the existing tools and prompts.

### ADR-0172-D14 — Evaluation and rollout

The parser and executor use portable filesystem fixtures covering valid operations,
malformed syntax, ambiguous and missing context, path escape, concurrent changes,
unsupported file types, resource limits, commit failure, and exact partial-delta
reporting.

GPT model evaluation compares `apply_patch` with the existing `edit` workflow for
multi-hunk and multi-file tasks. Rollout requires no wrong-location applications, stable
well-formed call generation, fewer visible tool calls for target tasks, and correct
partial-failure disclosure.

The first rollout is capability-gated to identified GPT-family models and remains
revertible by removing `apply_patch` from the prepared tool catalog.

## Consequences

### Positive

- GPT models receive the editing contract for which direct V4A harness evidence exists.
- Claude and Gemini are not forced onto a GPT-specific grammar.
- Existing `edit` callers and transcripts remain compatible.
- Multi-file edits use one Runtime round trip and one preflight boundary.
- Exact matching prevents a permissive parser from applying a plausible patch to the
  wrong location.
- Partial filesystem state is reported directly rather than obscured by a second
  best-effort rollback sequence.

### Negative

- GPT and non-GPT models have different visible file-editing capabilities.
- Multi-file patch calls can leave a committed prefix after a commit-phase failure.
- A dedicated Runner protocol operation and versioned capability rollout are required.
- Strict matching can cause retries for harmless whitespace drift.
- Added files cannot represent a missing final newline in the initial version.

## Alternatives considered

### Expose V4A to every model

Rejected because production harnesses and cross-model evidence do not establish V4A as
the best contract for Claude or Gemini.

### Replace `edit` with a Claude-named schema

Rejected because the only material schema difference is `path` versus `file_path`, which
does not justify changing an established Azents tool contract.

### Use standard unified diff

Rejected because model-generated line numbers, counts, headers, and path prefixes add
failure modes without improving the Runtime execution contract.

### Use approximate context matching

Rejected for execution because silently selecting a near match can modify the wrong code
or structured-data block. Approximate candidates are diagnostic-only.

### Roll back committed files after failure

Rejected because rollback is itself a non-atomic multi-file mutation and can fail or
clobber concurrent changes.

### Promise fully atomic multi-file patches

Rejected because arbitrary Runtime filesystems do not provide a general multi-path
transaction boundary. Stronger snapshot or worktree semantics belong to a separate
capability.
