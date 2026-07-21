---
title: "Declarative Improvements for Async Toolkit Loading State"
created: 2026-03-31
tags: [engine, architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: declarative-260331
historical_reconstruction: true
migration_source: "docs/azents/adr/0012-declarative-toolkit-status.md"
---

# declarative-260331/ADR: Declarative Improvements for Async Toolkit Loading State

> 📌 **Related design document**: [declarative-260331-declarative-toolkit-status.md](../design/declarative-260331-declarative-toolkit-status.md)
>
> This document records design-stage discussion.

## Background

The Toolkit State Machine design (`design/toolkit-state-machine.md`) made this decision:

> "The engine does not need to structurally understand toolkit internal state. The toolkit expresses state through natural-language prompts."

This decision was appropriate for Phase 1, which focused on interface transition, but operational problems appeared:

1. **The LLM gives up the turn after seeing "Loading tools..."**: natural language is a weak signal that the model should wait, and cannot induce declarative behavior such as wait/retry.
2. **The engine/frontend cannot distinguish states**: every abnormal state is represented as `ENABLED` plus a natural-language prompt, making structural branching impossible.
3. **No error recovery path**: when connection fails, the LLM has no action it can take. Even if natural language says "connection failed," there is no retry tool.

## What the LLM Sees by Current State

| State | status | tools | prompt |
|------|--------|-------|--------|
| Loading | ENABLED | cached or [] | "Loading tools..." |
| Error | ENABLED | cached or [] | "MCP server connection failed: ..." |
| Authorization required | ENABLED | [request_authorization] | "Authorization required..." |
| Ready | ENABLED | [tool list] | "" |
| Disabled | DISABLED | [] | "" |

All are `ENABLED`, so the engine cannot distinguish them structurally.

## Discussion Points

### 1. Should ToolkitStatus enum be extended?

**Options:**

A) **Keep natural-language prompt, current state**: the toolkit expresses state as prompt strings; the engine does not know.

- Pros: simple, no changes.
- Cons: LLM cannot structurally understand state; engine/frontend cannot branch.

B) **Extend ToolkitStatus enum**: add READY, LOADING, ERROR, AUTH_REQUIRED.

- Pros: engine can behave differently by state, including automatic tool injection.
- Cons: all toolkit implementations need updates; enum must change when adding a new state.

C) **Add metadata dict to ToolkitState**: flexible state transfer through `metadata: dict[str, str]`.

- Pros: new information can be added without schema changes.
- Cons: no type safety, convention-dependent, engine logic needs string comparisons.

**Decision: B — extend ToolkitStatus enum**

State kinds are clear and finite: READY, LOADING, ERROR, AUTH_REQUIRED, DISABLED. A metadata dict is over-engineering, and keeping natural-language prompts does not solve the problem.

### 2. Should ENABLED be renamed to READY?

**Options:**

A) **Keep ENABLED and only add new states**: minimize existing code changes.

- Pros: no existing code changes.
- Cons: the meaning difference between ENABLED and READY is confusing, as in "enabled but loading?"

B) **Rename ENABLED to READY**: clarify the meaning.

- Pros: state name accurately reflects actual meaning.
- Cons: all toolkit implementations must change ENABLED → READY.

**Decision: B — rename ENABLED to READY**

A backward-compatible alias (`ENABLED = "ready"`) allows gradual migration. For code consistency, updating all implementations at once is preferable.

### 3. Should the engine automatically inject tools by state?

Core feature proposed by the issue: inject `wait_for_toolkit` for LOADING and `retry_toolkit` for ERROR.

**Options:**

A) **Engine injects automatically**: the engine checks state and adds corresponding tools to the tool map.

- Pros: toolkit implementations do not need to care about state-specific tools; consistent UX.
- Cons: engine must directly call toolkit lifecycle methods such as `__aenter__`/`__aexit__`.

B) **Toolkit provides tools directly**: each toolkit returns its own tools when in LOADING/ERROR state.

- Pros: toolkit fully controls its own retry logic.
- Cons: duplicate implementation across all MCP-based toolkits; consistency is hard to guarantee.

C) **McpBasedToolkit provides them**: the MCP base class includes wait/retry tools.

- Pros: MCP-based toolkits get automatic support; non-MCP toolkits are unaffected.
- Cons: responsibility stays at toolkit layer rather than engine layer, weakening the reason to extend the enum.

**Decision: A — engine injects automatically**

Rationale:

- `request_authorization` is already a toolkit-provided pattern, but wait/retry are **state management** tools, so the engine layer is a better fit.
- If the engine knows state, it also opens an extension point for passing state to the frontend.
- Toolkit implementations should return state; tool injection should be delegated to the engine, matching separation of concerns.

### 4. How should wait_for_toolkit work?

When the LLM calls `wait_for_toolkit`, how does it wait?

**Options:**

A) **Polling**: inside the handler, repeatedly call `asyncio.sleep()` and `update_context()`.

- Pros: simple, no additional infrastructure.
- Cons: delayed by polling interval; requires passing a no-op TurnContext to `update_context()`.

B) **Event-based**: toolkit exposes an internal `asyncio.Event`, and the handler waits on that event.

- Pros: immediate response, no CPU waste.
- Cons: requires a new interface in Toolkit ABC and affects existing toolkits.

C) **Await background task directly**: directly await `toolkit._bg_task`.

- Pros: most direct.
- Cons: accesses a private member and cannot be standardized in Toolkit ABC.

**Decision: A — polling**

Rationale:

- Simple and requires no Toolkit ABC changes.
- MCP connections usually complete within seconds, so a 0.5-second polling interval is sufficient.
- Event-based waiting is better but requires Toolkit ABC changes, beyond the scope of this PR.
- Future optimization is possible, such as adding `wait_ready()` to Toolkit ABC.

### 5. How should retry_toolkit reconnect?

**Options:**

A) **`__aexit__` → `__aenter__`**: reuse existing lifecycle methods.

- Pros: no additional interface; reuses existing cleanup/initialization logic.
- Cons: `__aexit__` could have unexpected side effects, such as cleaning other resources.

B) **Add dedicated `reconnect()` method**: explicit reconnect interface on Toolkit ABC.

- Pros: clear intent, fewer side effects.
- Cons: Toolkit ABC change and default implementation needed for all toolkits.

**Decision: A — `__aexit__` → `__aenter__`**

Rationale:

- `__aenter__`/`__aexit__` already represent connection start and cleanup, so they are semantically appropriate.
- `McpBasedToolkit.__aexit__` only cancels the background task and has no side effects.
- A `reconnect()` method can be added later if needed.

### 6. Should ToolkitState add error_message?

**Options:**

A) **Keep error message in prompt field, current state**: no structural change.

- Pros: no changes.
- Cons: cannot distinguish error messages from user-facing prompt text.

B) **Add `error_message: str | None` field**: used only in ERROR state.

- Pros: structured error transfer; usable by frontend.
- Cons: minimal field addition.

**Decision: B — add error_message field**

Specific error information must be structurally available in ERROR state. The frontend can display it separately or include it in retry tool result messages.

### 7. Should the engine inject tools for AUTH_REQUIRED?

**Options:**

A) **Engine does not inject**: toolkit directly returns `request_authorization`, current pattern.

- Pros: keeps existing pattern; the toolkit understands authentication logic best.
- Cons: none.

B) **Engine injects**: engine injects a generic authorization-request tool.

- Pros: consistency.
- Cons: authentication flows differ by toolkit, such as OAuth, PAT, and API key. Hard to generalize.

**Decision: A — toolkit provides directly**

`request_authorization` depends on complex toolkit-specific auth flows such as OAuth2 discovery, DCR, and rate limiting, so it cannot be generalized. The existing pattern is appropriate.

### 8. Should toolkit status be exposed to the frontend?

**Options:**

A) **Expose in this PR**: send toolkit status changes through WebSocket events.

- Pros: frontend can display loading/error states.
- Cons: requires frontend work and expands PR scope.

B) **Do not expose in this PR; do it later**: extend enum first, integrate frontend later.

- Pros: limits scope and completes backend first.
- Cons: none.

**Decision: B — separate future PR**

This PR focuses on declarative state management in the backend engine. Frontend integration should happen in a separate PR after ToolkitStatus enum stabilizes.

## Review Feedback Applied (2026-03-31)

PR #2125 review with Hardtack changed the following decisions:

### Change 1: enum → discriminated union

**Before**: ToolkitStatus enum + optional error_message in ToolkitState.

**After**: Discriminated union (Ready | Disabled | Loading | Error | Other).

- Each state has only the data it needs; only Error has error_message.
- Type-safe and pattern-matchable.

### Change 2: AUTH_REQUIRED → Other

**Before**: AUTH_REQUIRED defined as a separate enum value.

**After**: Other, a generic state described by natural-language prompt.

- AUTH_REQUIRED is not general enough.
- Other can express authorization required, incomplete configuration, and other states.

### Change 3: Remove ENABLED alias

**Before**: kept alias `ENABLED = "ready"`.

**After**: switch all at once without alias.

- Avoid unnecessary compatibility layer.

### Change 4: engine automatic injection → toolkit directly provides tools

**Before**: engine injects `wait_for_toolkit` for LOADING and `retry_toolkit` for ERROR.

**After**: toolkit, specifically `McpBasedToolkit`, returns tools directly.

- Same as the `request_authorization` pattern.
- Engine only checks Disabled; everything else passes tools+prompt through as-is.
- This is toolkit responsibility.

### Change 5: ToolkitStatus/ToolkitState changes unnecessary

**Before**: discriminated union (Ready | Disabled | Loading | Error | Other) or enum extension.

**After**: no change to ToolkitStatus, ToolkitState, or engine.py.

- If the toolkit directly provides wait/retry tools, the engine no longer needs to distinguish states.
- This is exactly the same approach as `request_authorization`.
- Change scope shrinks to a single file: `mcp_base.py`.

## Migration provenance

- Historical source filename: `0012-declarative-toolkit-status.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
