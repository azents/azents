---
title: "Run Tool Output Directly to Runtime Requirements"
created: 2026-09-05
updated: 2026-09-05
implemented: 2026-09-05
tags: [agent, toolkit, runtime, files]
document_role: primary
document_type: requirements
snapshot_id: tool-260905
---

# Run Tool Output Directly to Runtime Requirements

- Snapshot: `tool-260905`
- Document reference: `tool-260905/REQ`

## Problem

When an Agent needs to use Tool-returned HTML, JSON, source code, generated files,
or other output inside its Runtime, it must currently reproduce text in a later
file write or separately materialize each referenced file. This consumes Tool
output in model context, may send the same content through the model a second
time, wastes tokens, and may fail to reproduce the Tool's result exactly.

## Primary Actor

An Agent that needs to process a client Tool's complete output with Runtime files,
commands, or scripts.

## Primary Scenario

The Agent selects a currently executable client Tool, supplies that Tool's normal
arguments and an absolute Runtime destination directory, and requests one
combined operation. The target Tool executes once under its ordinary authorization
and Toolkit context. Every output part is materialized as a Runtime bundle without
being relayed through model output. The Agent receives only a bounded storage
summary and then processes the bundle with Runtime tools.

## Supporting Scenarios

- A Tool returns a 20,000-character HTML document that the Agent stores and
  renders without reproducing the HTML in a file-write argument.
- A Tool returns text longer than the Engine's model-visible Tool output cap, and
  the complete Tool-returned text is still stored in Runtime.
- A Tool such as `exec_command` applies its own configured output limit before
  returning; the combined operation stores that Tool-returned value without
  attempting to recover content that the Tool itself omitted.
- A Tool returns text together with Attachment, Artifact, FilePart, or generated
  file output, and the Agent receives one Runtime directory containing every
  output part plus a manifest.
- A target Tool succeeds and some output parts are stored while other parts fail,
  so the Agent sees only the failed parts plus an explicit explanation that Tool
  execution succeeded and those Runtime writes failed.

## Goals

- Avoid relaying Tool output bodies through the model to create Runtime files.
- Preserve the target Tool's complete returned output as one ordered Runtime
  bundle.
- Support current Azents client Tools without restricting the capability to MCP.
- Preserve the target Tool's existing authorization, Toolkit state, hooks, and
  error semantics.
- Make part-level storage success and failure unambiguous after the target Tool
  succeeds.

## Non-Goals

- Copying the result of a previously completed Tool call.
- Invoking provider-hosted built-in Tools through the combined operation.
- Rendering HTML or interpreting the stored result.
- Changing the Engine's normal model-visible Tool output cap.
- Recovering content removed by a target Tool's own output-limit contract.
- Changing the source lifecycle or public availability of existing Attachment,
  Artifact, or ModelFile resources.

## Requirements

### REQ-1. Execute an eligible client Tool directly to a Runtime output bundle

The Agent must be able to select a currently executable Azents client Tool,
provide that Tool's normal arguments, and select an absolute Runtime destination
directory in one operation.

**Acceptance criteria**

- The target is not limited by Toolkit type, including MCP.
- The target Tool executes no more than once for one combined operation.
- An unknown, unavailable, provider-hosted, or recursively selected combined Tool
  fails before target execution.
- A successful operation creates the requested Runtime output bundle and returns
  a bounded summary rather than the target result body.

### REQ-2. Preserve target Tool execution semantics

The target Tool must execute with the same authorization, credentials, Toolkit
state, argument interpretation, hooks, and cancellation behavior that apply to a
normal direct call in the same prepared model turn.

**Acceptance criteria**

- A target Tool denied by existing policy or hooks does not execute and does not
  create a destination bundle.
- Target argument decoding, schema validation, or target-owned runtime validation
  failure is a target Tool failure and does not enter output storage.
- Target Tool errors remain Tool errors and do not create a destination bundle.
- The combined operation does not bypass Tool Search activation or the current
  prepared Tool availability boundary.
- The target Tool's own side effects and output-limit behavior are unchanged.

### REQ-3. Store Tool-returned text without Engine truncation

Runtime storage must use the target Tool's textual result before the Engine
applies its global model-visible Tool output cap.

**Acceptance criteria**

- The stored file receives no additional truncation from the combined operation
  or the Engine's normal Tool result cap.
- A 20,000-character textual result is stored completely.
- A textual result exceeding the Engine's 30,000-character model-visible cap is
  stored completely.
- Tool-level truncation or limiting, including `exec_command.max_output_bytes`, is
  preserved as part of the target Tool's returned result and is not bypassed.
- Text is written as UTF-8 and retains output-part order.

### REQ-4. Avoid successful-result body relay through the model

When target execution and Runtime bundle storage both succeed, target output
bodies must not be included in the model-visible combined Tool result.

**Acceptance criteria**

- The success result contains only bounded operational metadata such as target
  Tool name, destination directory, manifest path, file count, aggregate byte
  count, and bundle digest.
- The Agent does not need to reproduce or quote the target output in another Tool
  call to create the file.

### REQ-5. Apply safe part-level Runtime destination behavior

The combined operation must use a safe Runtime directory destination and commit
each output file independently.

**Acceptance criteria**

- Relative destination directories are rejected.
- The destination directory may already exist. Each conflicting destination file
  is preserved unless overwrite is explicitly requested.
- Destination errors that can be established before target execution fail before
  the target Tool is called.
- A failed or cancelled part transfer does not partially commit that file or
  replace its previous content.
- A successfully stored part remains available when another part fails; the
  operation does not roll back successful files.
- The committed directory contains a manifest that records output-part order,
  source type, media type, selected relative path, per-part `stored` or `failed`
  status, and successful byte count and content hash.
- File names are safe Runtime-relative names, and deterministic suffixes resolve
  collisions within the bundle.

### REQ-6. Distinguish target failure from part-level storage failure

The Agent must receive different observable outcomes for target Tool failure and
for output-part storage failure after successful target execution.

**Acceptance criteria**

- Target Tool failure returns the target's normal bounded failure result and
  states that no Runtime output bundle was created.
- An input-validation failure is never interpreted as a successful textual result
  or written into the Runtime destination.
- When the target Tool succeeds, output bodies for successfully stored parts are
  not exposed to the model.
- Each failed part is returned in its ordinary Tool output representation.
- Failed text parts are collectively subject to the existing 30,000-character
  Engine cap, while failed non-text parts retain their normal output-part
  representation.
- The storage-failure fallback appends a bounded instruction stating that the
  target Tool already executed successfully, the identified part failed Runtime
  storage, and that part is being returned instead.
- The storage-failure fallback marker remains visible even when the target output
  is truncated.
- The system does not automatically execute the target Tool again or roll back
  successfully stored parts after storage failure.

### REQ-7. Materialize every output part

The Runtime bundle must contain every body-bearing part returned by the target
Tool while preserving the source resource's existing lifecycle and authority.

**Acceptance criteria**

- Plain strings and OutputTextParts are stored as ordered UTF-8 files.
- Attachment and Artifact bodies are copied through their existing authorized
  source-resolution and Runtime transfer boundaries.
- FilePart and generated-file bodies are stored through their current normalized
  or transient body authority.
- Original safe filenames are retained when available. Textual output uses
  deterministic default names.
- Existing source resources remain governed by their current lifecycle and are
  not consumed or deleted by bundle creation.
- If an output body is unavailable or cannot be stored, only that part follows the
  successful-target/storage-failure fallback; independently successful parts
  remain stored.

### REQ-8. Require Runtime storage capability

The combined operation must be available only when the Agent can safely write and
transfer data into its current Runtime.

**Acceptance criteria**

- The Tool is not exposed without the required current Runtime filesystem and
  transfer capabilities.
- Runtime readiness and destination authority are validated before target
  execution whenever the failure can be determined in advance.
- Runtime capability or authority drift fails closed.

## Fixed Constraints

- The model-visible Tool name is `run_tool_to_file`.
- The Tool accepts the target Tool name, the target's argument string, an absolute
  Runtime destination directory, and explicit overwrite intent.
- The target must belong to the current prepared client Tool catalog and be
  available to the model in that turn.
- The combined Tool cannot select itself.
- Target execution and Runtime storage remain one Agent-visible Tool call, while
  the outcome must retain enough target identity for audit and diagnostics.
- Git-tracked artifacts and user-facing service text remain in English.

## Open Assumptions

- Existing client Tool handlers already materialize their complete return value in
  server memory, so direct-to-Runtime storage does not introduce a new streaming
  return contract in the first version.
- Runtime transfer maximum-size policy remains an operational upper bound; an
  oversized part follows the successful-target/storage-failure fallback.

## Confirmation

Confirmed by the requester on 2026-09-05 after reviewing the primary scenario,
client-Tool-wide scope, `run_tool_to_file` name, exact-text boundary, Tool-level
truncation exception, complete output-bundle behavior, and
part-level successful-target/storage-failure fallback.
