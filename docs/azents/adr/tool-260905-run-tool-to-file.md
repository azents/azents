---
title: "Run Tool Output Directly to Runtime"
created: 2026-09-05
tags: [agent, toolkit, runtime, files, architecture]
document_role: primary
document_type: adr
snapshot_id: tool-260905
---

# Run Tool Output Directly to Runtime

- Snapshot: `tool-260905`
- Document reference: `tool-260905/ADR`
- Requirements: [tool-260905/REQ](../requirements/tool-260905-run-tool-to-file.md)

## Context

Azents currently exposes client Tools as `FunctionTool` entries in a per-turn
catalog. The Engine executes a model-selected Tool through prepared-catalog
allowlisting, Tool Search recency, runtime hooks, and a Tool handler, then applies
the global text cap while constructing the durable client Tool result.

Runtime file tools are owned by the auto-bound Runtime Toolkit. Complete server to
Runtime file movement uses the verified Runtime Transfer path with destination
preflight, generation fencing, temporary-file verification, and atomic commit.

`tool-260905/REQ` adds one higher-order operation that executes another currently
available client Tool and stores its complete output as a Runtime directory
bundle. Text must be captured after target-owned behavior but before the Engine
model-visible text cap. Successful storage suppresses target bodies from model
context, while storage failure exposes the normal bounded result and an explicit
partial-success marker.

## Material Decision Map

- **D1 — Toolkit ownership and catalog assembly:** accepted.
- **D2 — Target invocation, hook, cancellation, and audit representation:** accepted.
- **D3 — Complete output-bundle materialization:** accepted.
- **D4 — Runtime staging, commit, and post-execution storage-failure recovery:** accepted.
- **D5 — Model-facing Tool description and usage guidance:** accepted.

## Fixed or Derived Outcomes

- The model-visible name is `run_tool_to_file`.
- The target is one currently model-visible prepared client Tool and cannot be
  `run_tool_to_file` itself.
- Provider-hosted Tools are outside the target catalog.
- The target Tool executes at most once per higher-order invocation.
- Successful storage returns bounded metadata without target output bodies.
- Runtime storage receives the target Tool's returned text before the Engine
  global cap, while target-owned truncation remains authoritative.
- A failed part transfer returns only that part through the ordinary bounded
  result representation plus an always-visible partial-success explanation.
- Destination preflight, per-file verified transfer, atomic file commit, and
  capability fencing reuse the existing Runtime file boundary.

## Decisions

### tool-260905/ADR-D1. Own the direct Tool in Runtime Toolkit and assemble it in the Engine

`run_tool_to_file` is an unprefixed direct Tool owned by the auto-bound Runtime
Toolkit. It is available only when the current Runtime filesystem and transfer
capabilities required by `tool-260905/REQ-8` are available.

The Engine assembles the executable handler after it has built, compatibility
projected, and model-visibility projected the current client Tool Catalog. The
handler receives the exact eligible prepared Tool entries as invocation targets.
`RuntimeToolkit` does not receive or traverse peer Toolkit instances and does not
become a second Tool Catalog owner.

The target set contains client Tools visible in the same prepared model call,
including direct Runtime Tools and activated deferred service Tools. It excludes
`run_tool_to_file` itself and provider-hosted Tools.

Affected requirements: `tool-260905/REQ-1`, `REQ-2`, `REQ-8`.

**Rejected:** A separate Tool Orchestration Toolkit would add another auto-bound
lifecycle and capability surface for an operation whose destination authority is
entirely Runtime-owned.

**Rejected:** A Toolkit-less Engine builtin would make the feature's Runtime
capability ownership and product presentation ambiguous.

### tool-260905/ADR-D2. Keep one ordinary client Tool call and result

`run_tool_to_file` uses the existing `FunctionTool`,
`ClientToolCallPayload`, and `ClientToolResultPayload` contracts without a new
Event kind, nested durable Tool call/result pair, separate call identifier,
special transcript structure, or dedicated UI activity type.

The selected target name and argument string remain visible through the ordinary
`run_tool_to_file` arguments. Its result uses the ordinary Tool output and
existing metadata capability. The implementation may log safe target and transfer
fields through established structured logging, but it does not create another
durable execution authority.

Inside the handler, target execution reuses the target's prepared handler,
Runtime capability guard, Tool Search recency behavior, before/after hooks, and
cancel handler. This reuse is an internal implementation mechanism, not a second
model-visible or durable Tool call.

Target argument decoding, Pydantic schema validation, target-owned runtime
validation, hook denial, and handler failure remain target failures. Only an
ordinary completed target result enters output-part materialization. Failure text
is never reclassified as successful output and never written to Runtime.

Affected requirements: `tool-260905/REQ-1`, `REQ-2`, `REQ-6`.

**Rejected:** Synthetic nested client Tool Events would represent a call that the
provider never produced and would complicate native Tool-pair lowering, recovery,
compaction, and activity presentation.

**Rejected:** A new execution Event or specialized UI contract would make this
ordinary Function Tool follow a separate protocol without a user requirement.

### tool-260905/ADR-D3. Materialize every output part as one Runtime directory bundle

`run_tool_to_file` treats its destination as a Runtime directory and
materializes every body-bearing part of the successful target result. Plain string
and `OutputTextPart` values become ordered UTF-8 files. Attachment and Artifact
parts reuse their authorized stored-object sources. FileParts use their current
normalized ModelFile body authority, and pending generated files use the transient
body already owned by the Tool result.

The destination contains `manifest.json` as the authoritative bundle index. It
records the original output-part order, part kind, media type, selected safe
filename, stored relative path, byte count, and digest. Existing safe filenames
are retained. Deterministic suffixes resolve collisions. One text output uses
`output.txt`; multiple text parts use `output-1.txt`, `output-2.txt`, and so on.

Successful bundle creation suppresses all target output bodies from the outer
model-visible result. Existing Attachment, Artifact, and ModelFile resources keep
their current ownership and lifecycle; bundle materialization copies bytes and
does not consume or delete a source.

If a required body is unavailable or one part cannot be materialized, that part
follows the successful-target/storage-failure fallback required by
`tool-260905/REQ-6`. Independently successful files remain in the destination.

Affected requirements: `tool-260905/REQ-3`, `REQ-4`, `REQ-5`, `REQ-7`.

**Rejected:** Text-only success with normal-result fallback for mixed output would
make behavior depend on output shape and would force the model to handle rich
parts differently from text.

**Rejected:** Saving text while hiding or dropping non-text parts would lose
existing file references or generated output from the Agent-visible result.

### tool-260905/ADR-D4. Commit each part independently and return only failed parts

The handler creates or validates the requested Runtime destination directory, then
materializes output parts independently through the current per-file verified
transfer and atomic destination commit. It does not introduce a directory-level
transaction, archive, staging-directory swap, or rollback of files that already
committed successfully.

The handler writes `manifest.json` after processing the output parts. Each entry
records its original order and kind, selected relative path, `stored` or `failed`
status, and successful size and digest. The manifest is operational output rather
than a commit fence; the ordinary Tool result remains the authority for which
failed parts were returned to the model.

On complete success, the outer result contains only a bounded summary. On partial
storage failure, it contains a bounded summary of stored files followed by only
the failed original output parts. Text in those failed parts is subject to the
ordinary Engine hard cap. Non-text failed parts retain their ordinary output-part
representation. A final text marker states that the target Tool already executed
successfully and only the identified Runtime storage operations failed. Its final
position ensures the current tail-preserving hard cap keeps the marker visible.

The operation neither re-executes the target Tool nor removes successfully stored
files after a part failure. A target Tool failure remains the ordinary target
failure path and starts no output-part transfers.

Affected requirements: `tool-260905/REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`.

**Rejected:** Directory-level atomic commit was disproportionate to the requested
workflow and would require a new multi-file Runtime protocol and replacement
semantics.

**Rejected:** Returning every original output part after one storage failure would
reintroduce avoidable model context for parts already stored successfully.

### tool-260905/ADR-D5. Keep usage guidance in concise Tool and field descriptions

The Runtime Toolkit adds no static or dynamic prompt for this capability.
`run_tool_to_file` uses this model-visible description:

> Run one currently visible client tool and save its output parts to a Runtime
> directory. Use this when Runtime commands or scripts will consume the output;
> call the target tool directly when the model must inspect it. Activate deferred
> tools first. Saved parts are summarized. Parts that fail to save are returned
> normally with notice that the target already ran.

Its input fields use the following guidance:

- `tool_name`: Exact name of the visible client tool to run.
- `arguments`: Target tool input as a string; JSON object string for JSON-function
  tools, raw text for plaintext-custom tools.
- `directory`: Absolute Runtime directory for saved output parts.
- `overwrite`: Replace conflicting files; false preserves them.

The partial-storage result notice states that the target Tool already ran and
identifies only the parts whose Runtime storage failed. It does not imply target
execution failure or recommend blind re-execution.

Affected requirements: `tool-260905/REQ-1`, `REQ-2`, `REQ-4`, `REQ-6`, `REQ-8`.

**Rejected:** Duplicating this stable usage guidance in the Runtime Toolkit prompt
would consume prompt context before Tool selection and create another
documentation authority.

**Rejected:** A longer description enumerating implementation details would make
the selection guidance harder to scan without changing the Tool contract.

## Rejected Directions

### Select an earlier result by provider Tool call ID

Rejected because the provider call ID is durable protocol pairing data but is not
reliably exposed as model-readable Tool result content.

### Add an Azents result reference and copy an earlier result

Rejected because the requested workflow should choose direct Runtime storage
before executing the target Tool rather than require a second result-selection
step.

### Preserve only output that exceeds the Engine text cap

Rejected because exact direct materialization is also required for outputs below
the cap, such as a 20,000-character HTML document.

### Restrict the capability to MCP

Rejected because the higher-order operation must support eligible client Tools
regardless of Toolkit type.

## Consequences

- The higher-order operation is available through the existing Runtime capability
  surface and uses no new Toolkit lifecycle.
- One normal client Tool Event pair represents the operation. Target execution
  details remain ordinary arguments and result behavior rather than a nested
  transcript protocol.
- Tool output bodies can remain out of model context when their Runtime writes
  succeed, including results below the existing text cap.
- Mixed output can produce a partial Runtime bundle; the manifest and outer Tool
  result identify stored and failed parts.
- Target input validation and execution failures remain distinct from output-part
  storage failures.
- Existing per-file transfer limits and target-owned output limits remain
  authoritative.
