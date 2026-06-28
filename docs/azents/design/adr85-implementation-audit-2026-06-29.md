---
title: "ADR-0085 Implementation Audit - 2026-06-29"
created: 2026-06-29
updated: 2026-06-29
implemented: 2026-06-29
tags: [backend, engine, toolkit, verification]
---

# ADR-0085 Implementation Audit - 2026-06-29

## Scope

This audit rechecked current implementation against ADR-0085 decisions for deterministic tool catalogs, MCP snapshots, AGENTS.md instruction handling, and legacy GitHub per-user PAT behavior.

## Decision Gap Table

| ADR-0085 decision | Reverified implementation gap | Resolution in this change |
| --- | --- | --- |
| D1-D3: client tools must be lowered deterministically and model-visible pseudo availability tools should not affect tool catalogs. | Core tool lowering already sorts model-visible function tools, but MCP wrapper paths still had synchronous discovery/loading-style assumptions in tests and inconsistent snapshot use. | Kept canonical final client-tool sort and moved MCP/AWS/GCP/GitHub wrapper behavior to latest-successful snapshot exposure with deterministic tool ordering. Loading/error prompt text and setup/retry pseudo-tools are not model-visible availability controls. |
| D4-D9: MCP-backed toolkits should keep `list_tools` discovery off the run-preparation critical path and expose only the latest successful serializable snapshot. | Generic MCP had snapshot infrastructure, but wrapper-specific AWS/GCP/GitHub paths needed matching lifecycle behavior and tests. | AWS/GCP/GitHub wrappers now build serializable snapshot items, refresh in background, atomically store successful snapshots, preserve the previous successful snapshot on refresh failure, and rebuild runtime-only handlers from stored metadata. |
| D10-D13: snapshot content must be deterministic and must not store runtime-only objects. | Wrapper snapshots needed stable state names and deterministic hashing while preserving per-run runtime objects such as token providers, SigV4 auth, artifact sinks, and background tasks in process memory. | Snapshot payloads store serializable tool metadata only. Runtime-only auth providers, artifact sinks, and background tasks remain in memory. Hashing uses sorted JSON payloads and stable state names. |
| D14: AGENTS.md instructions should be a `read` result appendix, not Toolkit prompt/session content. | Builtin/runtime toolkit still contained AGENTS prompt-loading state and startup/project prompt behavior. | Removed AGENTS content prompt injection and content snapshots. Successful `read` results append applicable AGENTS.md content through `on_after_tool_call`; Toolkit State stores only path-based appendix dedupe. Compaction clears the dedupe path set. |
| D14: AGENTS discovery must not touch Runtime at startup solely to find root AGENTS.md. | Prior loader design could populate prompt state independently of explicit file tool usage. | AGENTS candidates are read only while handling a successful `read` tool result. Prompt builds contain fixed guidance only and do not read Runtime files. |
| D14: initially append AGENTS only to successful `read`, not write/edit/grep/glob/import/present/read_image. | Existing hook design was broader path-observation oriented. | Appendix candidate extraction is limited to the `read` tool; other file tools do not receive AGENTS appendices. |
| D15: GitHub `per_user_pat` behavior is legacy and should be removed rather than optimized. | Backend toolkit config, `setup_github` path, GitHub PAT API/service/repo/model, web setup page, tRPC router, profile UI, and generated clients still exposed per-user PAT flows. | Removed `per_user_pat` from config, runtime, tests, public API, web UI, and generated public clients. Added a migration to drop `github_pats`. Updated living specs to make GitHub auth toolkit-level only. |

## Verification Commands

```console
$ cd python/apps/azents && uv run ruff check src db-schemas/rdb/migrations/versions/b7d540720215_drop_github_pats.py
$ cd python/apps/azents && uv run pyright src/azents/engine/tools/builtin_agents.py src/azents/engine/tools/builtin.py src/azents/engine/tools/aws.py src/azents/engine/tools/gcp.py src/azents/engine/tools/github.py src/azents/engine/tools/mcp_base.py src/azents/core/tools.py src/azents/api/public/__init__.py src/azents/engine/tools/deps.py
$ cd python/apps/azents && uv run pytest src/azents/engine/tools/builtin_test.py src/azents/engine/tools/mcp_base_test.py src/azents/engine/tools/aws_test.py src/azents/engine/tools/gcp_test.py src/azents/engine/tools/github_runtime_environment_test.py src/azents/engine/tools/goal_test.py src/azents/engine/tools/todo_test.py src/azents/engine/events/tools_test.py src/azents/engine/events/litellm_responses_test.py -q
$ cd typescript && pnpm run format --filter=@azents/web --filter=@azents/public-client
$ cd typescript && pnpm run lint --filter=@azents/web --filter=@azents/public-client
$ cd typescript && pnpm run typecheck --filter=@azents/web --filter=@azents/public-client
```

## Notes

- Historical ADR/design files still mention previous GitHub per-user PAT designs by design. Current behavior is recorded in `docs/azents/spec/domain/toolkit.md` and `docs/azents/spec/domain/user-auth.md`.
- The old migration that originally created `github_pats` remains in history; the new head migration drops the table for current deployments.
