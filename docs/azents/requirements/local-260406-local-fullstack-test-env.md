---
title: "Full-Stack Local Test Environment — Discussion Record Historical Requirements Reconstruction"
created: 2026-04-06
implemented: 2026-04-06
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: local-260406
historical_reconstruction: true
migration_source: "docs/azents/adr/0017-local-fullstack-test-env.md"
---

# Full-Stack Local Test Environment — Discussion Record Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `local-260406`
- Source: `docs/azents/adr/local-260406-local-fullstack-test-env.md`
- Historical source date basis: `2026-04-06`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

**Decision**:

```python
@dataclass
class RunContext:
    repo_root: Path
    nointern_dir: Path
    env_file: Path
    env: dict[str, str]
    previous_results: dict[str, CheckResult]
```

- `.env` is injected into `os.environ` and also kept in `context.env` as a dict.
- Include `previous_results`, but checks should use it directly only as an exception. `depends_on` declarations are the default.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

| | Infra | devserver | agent-runtime | LLM Key | nointern-web |
|---|:-:|:-:|:-:|:-:|:-:|
| A. API CRUD / prompt assembly | O | O | - | - | - |
| B. WebSocket chat / LLM pipeline | O | O | - | O | - |
| C. Shell/file tool execution | O | O | O | O | - |
| D. MCP toolkit | O | O | O | O | - |
| E. Sandbox isolation verification | O | O | O | - | - |
| F. Image generation/input | O | O | - | O | - |
| G. Web UI with Playwright MCP | O | O | - | - | O |

## Supporting Scenarios

| | Infra | devserver | agent-runtime | LLM Key | nointern-web |
|---|:-:|:-:|:-:|:-:|:-:|
| A. API CRUD / prompt assembly | O | O | - | - | - |
| B. WebSocket chat / LLM pipeline | O | O | - | O | - |
| C. Shell/file tool execution | O | O | O | O | - |
| D. MCP toolkit | O | O | O | O | - |
| E. Sandbox isolation verification | O | O | O | - | - |
| F. Image generation/input | O | O | - | O | - |
| G. Web UI with Playwright MCP | O | O | - | - | O |

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
