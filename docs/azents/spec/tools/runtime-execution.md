---
title: "Runtime tool execution and network authority"
created: 2026-11-04
tags: [wiki]
---

# Runtime tool execution and network authority

Owns credential exposure, shell/runtime execution, network enforcement and Runtime Hook behavior. Tool availability is a projection; invocation must still validate current execution and resource authority.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Runtime capability and profiles](../runtime/profiles.md)
- [Runtime control](../flow/agent-runtime-control.md)
- [Toolkits](../domain/toolkit.md)
- [Interactive terminals](../runtime/terminal.md)

## Credential Isolation

Strong invariant: **raw credential is never exposed in agent prompt**.

- **DB layer**: `RDBToolkitConfig.encrypted_credentials` stores Fernet ciphertext. If `ToolkitRepository` is created without cipher, it cannot read or write `credentials` field.
- **Output layer**: API response (`ToolkitConfigResponse`) does not return plaintext credentials, only exposes existence as `has_credentials: bool` (`ToolkitOutput.has_credentials`). ([`services/toolkit/data.py` L13-21](../../../../python/apps/azents/src/azents/services/toolkit/data.py))
- **Runtime injection**: credential is passed only to toolkit provider as `ResolveContext.credentials_json`, and is used as header/token only for network calls to MCP server. LLM system prompt includes only administrator-provided `ToolkitConfig.prompt`.

## Runtime Tool Execution and Network Authority

AWS role credentials use the public STS AssumeRole SDK operation, retaining
region/endpoint, role/external ID, session name, duration and early-refresh cache.
Direct access keys do not instantiate STS. Google service-account signing and
token parsing use the public credential SDK with only the adopted email/private
key and scopes. The fixed token URI, RS256 and absence of a `kid` header remain
unchanged; opaque token URI/universe/key-ID fields cannot gain endpoint or signing
authority. UTC expiry is normalized explicitly. The existing 30-second timeout,
disabled redirects and one physical authentication dispatch are enforced through
the public Request boundary, including SDK-eligible retries. Failed refreshes
do not publish credentials; synchronous SDK work runs off the event loop and
owns resource closure.

Kubernetes CRUD remains on lightkube. Discovery and WebSocket execution reuse the
owned Kubernetes SDK client through public typed Core/Groups APIs and the public
generic operation for installed preferred group versions. Private lightkube HTTP
internals and handwritten discovery requests are not used. Preferred versions,
subresource skips, per-group HTTP-failure skips and resource ordering/cache reuse
remain unchanged. Partial initialization closes both clients before propagating
unexpected failures or cancellation. GKE discovery uses the public Container SDK
with current endpoint identity and no additional operation retries.

Runtime mutation/process/transfer tools (`exec_command`, `write_stdin`,
`write`, `delete`, `edit`, `apply_patch`, `import_file`, `present_file`, and
`read_image`) are auto-bound only when the captured Agent capability
snapshot grants the declared Runtime capability. Generic `read`/`grep`/`glob`
remain independently bound; only their absolute Runtime branch requires that
capability. The current Workspace Runtime Profile and its
resolved Provider configuration own outbound network authority. ToolkitConfig owns persisted
external-service integration configuration.

Projection and execution are separate fences. A managed-but-stopped Agent may project an authorized
operation and lazily start/wait when that operation executes. Runtime-free and removing Agents omit
the capability before Runtime ensure, Profile resolution, Runner dispatch, or credential collection.
Every admitted operation rechecks the captured capability version and current state before external
side effects; a concurrent removal fails closed instead of retargeting another Runtime incarnation.

Memory Context and Memory Write are separate auto-bound capabilities. Enabled
root/subagent `memory_context` contributes the root's persisted initial or
post-compaction boundary snapshot and live VFS lookup guidance, with no domain
read tools. Ordinary turns filter unavailable entries without reselection.
Root-only `memory_write` exposes Saved `save_memory` and `delete_memory`; subagents
do not receive those mutation tools. Saved Memory and Session-summary lookup use
generic VFS reads. Memory-enabled root and subagent execution also retain
`search_sessions`, `read_session_history` and `read_session_tool_result` through
the directly visible readable-storage Toolkit, with current root authorization
and server-bound execution identity. Disabled Memory omits these history tools,
contributes no automatic context/mutation tools and denies the live Memory mount
while generic tools can still read other authorized backends.

- `ShellToolkitConfig` is the internal shared configuration model for auto-bound Builtin, Memory,
  and Runtime Toolkit instances. It carries `allowed_domains`, `denied_domains`, `agent_data_root`,
  and `memory_enabled`; the Worker currently supplies empty domain lists and the Agent's persisted
  Memory setting when resolving these Toolkits. ([`core/tools.py`](../../../../python/apps/azents/src/azents/core/tools.py), [`worker/run/executor.py`](../../../../python/apps/azents/src/azents/worker/run/executor.py))
- Provider network enforcement is resolved independently through the canonical Runtime Profile
  configuration envelope. Kubernetes Profile and Workspace policy may select direct,
  proxy-required, or no-network authority; Docker remains direct-only under its supported Profile
  contract. ([`core/runtime_profile.py`](../../../../python/apps/azents/src/azents/core/runtime_profile.py), [`services/agent_runtime`](../../../../python/apps/azents/src/azents/services/agent_runtime))
- Runtime file tools guide the LLM-facing path surface for durable working files under the current Runner-reported Agent Workspace and temporary files under `/tmp/**`. Static tool schemas name the Agent Workspace generically, while the dynamic Runtime prompt renders the exact current root. User upload is copied to Runtime by `import_file` using `exchange://{object_key}` file-location URI, and internal artifact is copied with `artifact://{storage_key}` file-location URI. `/tmp/**` destination import warns that result can disappear after Runtime restart and returns original URI for reimport. `present_file` exports files from any absolute Runtime path, including `/tmp/**` and paths outside the Agent Workspace, as user-visible `exchange://{object_key}` attachments, subject to filesystem permissions and transfer verification.
- Runtime transfer, publication, and provider-delivery services are required parts of the Runtime Toolkit rather than optional capabilities. Toolkit context construction never waits for Runner readiness. The Runtime static prompt selects the applied configuration when a ready current-generation Runner is already serving it; otherwise it selects the desired configuration used for a permitted start/wait path. A blocked or malformed future desired slot does not replace the authority of an already-ready applied Runtime. When neither path supplies a usable configuration document, the prompt leaves Runtime operations unavailable.
- General Runtime file movement uses shared 128 MiB eligibility: `import_file`,
  `run_tool_to_file` parts, and `download_external_file` receive exact-attempt direct
  GET capabilities after trusted source verification; `present_file`, Runtime-file
  `channel_action`, and `read_image` use manifest-bound Runner direct PUT and verified
  immutable completion. Managed S3 sources use native copy, while already-held Tool
  bytes and provider ingress retain bounded trusted staging. Control messages carry
  metadata, not complete-file bodies, with no feature relay fallback. `read_image`
  keeps its separate image-input policy and external-service delivery keeps its
  outbound per-file/aggregate limits. URLs and signed headers are request-local.
- Each ordinary Runtime-backed Tool resolves a bounded exact target only when it executes and may request start/wait according to that operation contract. A prompt-bound target must still match the captured applied or desired sequence, digest, and target generation. An already-ready target requires the retained applied configuration, a ready positive Runner generation, and current Runner-reported Workspace evidence; Provider connection/resource observation and a future desired mismatch are not data-plane fences. Starting or replacing compute still requires the desired configuration and Provider lifecycle authority. The returned operation target freezes Runtime ID, Runtime capability version, target generation, Runner generation, configuration sequence and digest, and Workspace path. Runner loss, terminal deletion, capability change, supersession, or drift fails the Tool rather than executing against a substituted Runtime. Skill filesystem projection is non-starting and succeeds only from an immediately qualified current target.
- `read` file tool interprets both `offset` and `limit` as decoded text character counts. It reads fixed-size byte ranges from the Runtime and applies strict incremental decoding from the start of the file, so a storage boundary cannot split a multibyte character into a false decode failure. The decoder retains only the bounded requested text plus one continuation character. Invalid source bytes encountered while locating the offset or decoding that bounded range return an explicit encoding error; an unread suffix is not validated. Result range metadata and continuation offsets use the same character unit as the input schema.
- `grep` file tool accepts both file path and directory path. Directory path searches recursively by default. Built-in heavy-directory excludes such as `.git`, `node_modules`, `.next`, and build/cache directories are applied by default. `exclude` adds caller-provided exclude patterns on top of those defaults; `disable_default_excludes: true` explicitly scans paths that the defaults would skip. Grep also enforces searched-file and scanned-byte safety caps so sparse matches across very large workspaces do not monopolize Runtime operation time.
- `glob` file tool accepts absolute path patterns and implements a shell-style pathname matching subset: `*`, `?`, character classes (`[...]`), recursive `**` matching zero or more path segments, and comma-separated brace alternatives such as `*.{jpg,png}`, including nested alternatives. Recursive patterns search below the non-glob prefix and may return matching directories as well as files, so `<agent-workspace>/.claude/skills/*` exposes directory entries and `/foo/bar/**/baz.{jpg,png}` matches both `/foo/bar/baz.jpg` and nested equivalents. Brace expansion is evaluated once per tool call and is limited to 256 alternatives. Brace sequences such as `{1..10}`, extglob, variable expansion, command substitution, shell quoting, backslash escaping, and tilde expansion are not supported. Patterns beginning with `~` fail explicitly instead of depending on the Runtime process home directory. Built-in heavy-directory excludes such as `.git`, `node_modules`, `.next`, and build/cache directories are applied by default. `exclude` adds caller-provided exclude patterns on top of those defaults; `disable_default_excludes: true` explicitly scans paths that the defaults would skip.
- Runtime tool prompt guides LLM to prefer dedicated file tools for filesystem work: use `read` instead of `cat`, `grep` instead of shell `grep`/`rg`, `write`/`edit` instead of shell redirection or `sed` when possible. Use `exec_command` for command execution, package installation, or when dedicated tool does not fit. Use `wait` for interruptible command-completion waiting; use `write_stdin` for stdin input and unread output collection (`yield_time_ms=0` for immediate collection). Commands explicitly marked `fire_and_forget` do not affect shared waiting. Runtime config prompts sort registered projects and domain lists deterministically and describe the preserved Agent Workspace, temporary work, and outbound connectivity without claiming Azents-owned infrastructure isolation or exposing sensitive path inventories.
- Managed Runtime prompts tell Agents to use native `pixi search` with the
  Runner-provided Linux platform and `pixi global install` for missing user-space
  tools and not to use sudo or operating-system package managers. This guidance
  adds no ToolkitConfig, capability, Profile, API, inventory, or package-policy
  state.
- `exec_command(command, workdir?, yield_time_ms?, max_output_bytes?, fire_and_forget = false)` starts a pipe-based Runner-owned process. If the process exits within the yield window, the tool result includes final output and exit code. If it is still running, the result includes collected output plus a process `process_id` for later interaction. `yield_time_ms` defaults to 10000 ms and accepts 250-10000 ms. Ordinary commands participate in shared `wait`; explicitly fire-and-forget commands do not keep waiting eligible or release it on completion. Starting a command does not force a wait call.
- `write_stdin(process_id, chars = "", yield_time_ms?, max_output_bytes?)` writes to an existing process. Empty `chars` polls and drains unread output. `yield_time_ms=0` collects currently buffered output immediately. Non-empty writes default to 250 ms; empty polls default to 5000 ms; both accept 0-10000 ms. Use `wait` for longer interruptible waiting. These bounds apply to process-yield windows, not Runtime preparation/transport/drain latency. Missing/expired/terminated process ids remain normal observations with structured metadata. Per [exec-260628/ADR](../../adr/exec-260628-exec-stop-termination.md), user stop requests TERM for all live exec processes owned by the stopped `AgentSession`; worker graceful shutdown/handover does not TERM runner-owned exec processes by itself.
- Runtime process tool results are text for model visibility plus generic `metadata` on the client tool result payload. Metadata includes process status, process id when present, exit code when exited, truncation facts, and missing reason when unavailable. The engine preserves this metadata generically and does not branch on exec-specific keys.
- The legacy `bash` tool is no longer exposed as the model-visible runtime shell command tool. Existing file tools continue to use Runner file operations.

One `RuntimeRunnerFileStorage` instance is created per Runtime Toolkit turn and shared by visible file tools and instruction appendix loaders. The storage is bound to the Runtime Agent identity and carries the invoking Agent Session ID as `owner_session_id` on every Runner file operation. It clears its cached target at every model-visible file-tool boundary and resolves a fresh exact qualified target using the prompt-selected applied or desired authority; appendix reads within that boundary share the same target. A subagent therefore uses its parent Agent Runtime while retaining its own Session ownership. An in-flight boundary does not retry a failed mutation against a replacement Runner generation.

Shell and managed process execution runs directly through the Runner process service. Native file,
edit, patch, search, Git, import, image, publication, provider-delivery, and transfer operations
also execute directly in the Runner without a helper subprocess. Relative paths resolve from the
Agent Workspace; absolute paths are governed by the Runtime operating-system user's ordinary
filesystem permissions. `present_file` requires absolute Runtime paths, while Session authority,
regular-file verification, source stability, size, and checksum checks remain enforced by the
publication and transfer services. None of these behaviors is represented
as Azents-owned process or infrastructure isolation.

Structured logs separate visible file-tool duration and Runtime operation count from appendix processing. They include tool status, Session identity, phase duration, candidate/discovery/cache/dedupe counts, and internal list/stat/read counts as applicable. Raw file content, rendered appendix content, and model-visible output are not logged.

## Runtime Hook Provider Contract

Runtime `Toolkit` instance can explicitly register supported lifecycle callbacks through `hooks() -> RuntimeHooks`. Registration is `TypedDict(total=False)` mapping. Dispatcher does not infer by method existence; it only calls callbacks present in mapping key.

- Default `hooks()` implementation returns empty mapping, so toolkit without hooks behaves as no-op provider.
- One lifecycle key registers at most one callback per provider. If provider needs to compose multiple behaviors, it owns ordering inside that callback.
- Dispatcher records normal exceptions from all hooks as structured warning and trace event, then isolates them fail-open. `asyncio.CancelledError` is execution stop signal and propagates.
- Dispatch target is not every Toolkit connected to run, but only Toolkit bindings that remained `ToolkitStatus.ENABLED` and activated without exception in that turn's `update_context()`. Sandbox lifecycle uses a resolver injected into sandbox manager to determine provider list separately.
- Trace stores only provider slug, lifecycle, status, result kind, exception class, duration, short-circuit status. Raw args, raw output, prompt text, and credential are not stored.

Supported lifecycles:

| Lifecycle | Context | Result | Meaning |
|---|---|---|---|
| `on_session_start` | `SessionStartHookContext` | `None` | called once on first run of session lifetime |
| `on_session_clear` | `SessionClearHookContext` | `None` | defined in provider contract but not yet dispatched in current clear path |
| `on_session_compact` | `SessionCompactHookContext` | `None` | defined in provider contract but not yet dispatched in current compaction path |
| `on_run_start` | `RunStartHookContext` | `None` | called right after run execution starts |
| `on_run_end` | `RunEndHookContext` | `None` | called for every started run with `completed` / `error` / `cancelled` / `unknown` reason |
| `on_turn_start` | `TurnStartHookContext` | `TurnStartResult` or `None` | can inject additional user prompt at turn start |
| `on_turn_end` | `TurnEndHookContext` | `None` | called for every started turn with reason |
| `on_before_tool_call` | `BeforeToolCallHookContext` | `ToolCallDecision` or `None` | decide allow/deny before tool handler execution |
| `on_after_tool_call` | `AfterToolCallHookContext` | `ToolOutputDecision` or `None` | keep or replace text channel of tool handler result |
| `on_sandbox_hibernate` | `SandboxHibernateHookContext` | `None` | legacy sandbox hibernate hook; Provider persistence is event in Agent Runtime path |
| `on_sandbox_restore` | `SandboxRestoreHookContext` | `None` | legacy sandbox restore hook; Provider persistence is event in Agent Runtime path |

Injected prompt returned by `on_turn_start` is passed to engine as event hook prompt result with `hook_provider_slug` and `hook_prompt_index` filled by dispatcher. `persistence=visible_user_input` is stored as normal user input, and `hidden_internal_input` is stored as internal user input, both included in replay/resume.

`deny` decision from `on_before_tool_call` short-circuits on first deny, returns deny message as tool output, and does not run handler. `on_after_tool_call` forms provider-order pipeline. If earlier provider returns `replace_output`, next provider receives replaced `output_text`; final replacement applies only to SDK output text channel. Image artifact block is preserved and output cap is reapplied after replacement.

AGENTS.md instruction loader registers runtime hooks through `hooks()`. It does not inject AGENTS.md content into Toolkit prompts.

## Runtime-Only Toolkit Boundary

Memory Context/Write, generic VFS reads, Goal, Todo, managed VFS Skills, subagent
collaboration, schedule, and compatible remote Toolkit operations do not require
a managed Runtime. Absolute-path read branches, Runtime mutation/process tools,
filesystem Skill discovery/materialization, AGENTS.md/Claude Rules filesystem projection, Runtime
transfer, Workspace/Project/Git operations, and Runtime credential exposure declare stable Runtime
capabilities and are projected exactly when the captured and current Agent capability is `managed`
at the same optimistic version. `none` and `removing` project none of those capabilities. The
independent browser `terminal_enabled` policy is never read by Toolkit resolution.

Toolkit resolution receives an execution mode. Root sessions use root mode. Child sessions whose
`AgentSession.session_kind` is `subagent` use subagent mode. This filter keeps root/user-facing
capabilities such as Memory Write and Goal Toolkit out of subagent auto-binding without changing
DB-registered ToolkitConfig resolution. Runtime-free mode retains generic VFS
reads and compatible server/remote capabilities while omitting Runtime-dependent
tool branches, prompts, hooks, filesystem projection, and credential injection.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/engine/tools`](../../../../python/apps/azents/src/azents/engine/tools)
- [`python/apps/azents/src/azents/core/runtime_admission.py`](../../../../python/apps/azents/src/azents/core/runtime_admission.py)
- [`python/libs/azents-runtime-control`](../../../../python/libs/azents-runtime-control)
