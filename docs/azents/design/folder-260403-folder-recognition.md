---
title: "Agent User Folder Recognition Design"
tags: [infra, engine, historical-reconstruction]
created: 2026-04-03
updated: 2026-04-03
implemented: 2026-04-03
document_role: primary
document_type: design
snapshot_id: folder-260403
migration_source: "docs/azents/design/user-folder-recognition.md"
historical_reconstruction: true
---

# Agent User Folder Recognition Design

## Overview

### Problem

Current sandbox guarantees file isolation by mounting `/data/user/` differently per user through bwrap per-user mount namespace. This mechanism was the only way to make LLM recognize user folder through fixed path `/data/user/`.

However, Discussion #2246 decided:

- **Privacy purpose of file isolation is discarded**: bwrap per-user mount prevents "B explicitly asking agent for A's file," but cannot prevent A's memory from being exposed in A session response in public channel.
- **Privacy boundary = bot access control**: assume user memory sharing among people who can access bot (→ #2242)
- **Keep user memory path**: `agents/{agent_id}/users/{nointern_user_id}/` structure remains for personalization, without isolation guarantee

→ If bwrap per-user mount is removed, LLM can no longer know user folder location. This design solves that.

### Solution

Make LLM recognize user folder with **A+B combination**:

- **A (system prompt)**: specify actual path in dynamic config prompt.
- **B (env var)**: inject `USER_DIR` into bwrap environment → use `$USER_DIR` shorthand in shell.

## Discussion Points and Decisions

### 1. bwrap removal scope

| Option | Decision |
|--------|------|
| A) Remove only `--user-dir` bind mount, keep bwrap itself | **✅ selected** |
| B) Remove all bwrap | out of scope |

**Rationale:** bwrap network isolation (mitmproxy domain filtering) is independent security feature. Removing only per-user mount resolves BYOC/Privileged sandbox compatibility issue.

### 2. Path handling in shell exec

| Option | Decision |
|--------|------|
| A) Keep symlink (`/data/user → /mnt/agent-data/users/{user_id}`) | rejected |
| B) Expose actual path (A+B combination) | **✅ selected** |

**Rationale:** symlink requires mounting entire `/mnt/agent-data/` inside bwrap, which recreates previous isolation structure. Exposing actual path is clearer and more consistent.

**Rejected alternative:** static symlink at container level — impossible because user_id is determined at runtime.

### 3. system prompt (A) implementation

| Option | Decision |
|--------|------|
| Describe storage in both static `system_prompt` and dynamic config prompt | rejected (duplicate) |
| Integrate into dynamic `_render_config_prompt()`, remove storage path description from static prompt | **✅ selected** |

**Rationale:** Dynamic config prompt can context-aware show only actually usable paths depending on agent_id/user_id presence. Static prompt is always injected, so describing paths without knowing availability becomes inaccurate.

**Changes:**
- `_render_config_prompt()` parameter: `has_user_id: bool` → `user_id: str | None`
- Add actual path + `$USER_DIR` guidance to dynamic config prompt.
- Remove storage path table (`/data/user/`, `/data/agent/` related) from static `system_prompt`.

### 4. USER_DIR env var (B) implementation — injection location

| Option | Decision |
|--------|------|
| A) Add `--setenv USER_DIR` to bwrap-exec script | **✅ selected** |
| B) Inject env var directly in executor.py | rejected |

**Rationale:** Change bwrap-exec to receive `--user-dir` option and inject env var instead of mount. No executor.py interface change. bwrap-exec is single source of truth.

**Note:** Meaning of `--user-dir` option changes from "bind mount" to "env var injection," so update script comments/header explanation together.

## Architecture

### Before (current)

```
executor.py
  └─ _build_bwrap_cmd(user_id=uid)
       └─ bwrap-exec --user-dir /mnt/agent-data/users/{uid}
            └─ bwrap
                 --bind /mnt/agent-data/users/{uid} /data/user   ← /data/user alias
                 └─ LLM shell: cat /data/user/memories/...
```

```
_render_config_prompt(has_user_id=True)
  └─ "- /data/user/ — Per-user storage (private)"
```

### After

```
executor.py
  └─ _build_bwrap_cmd(user_id=uid)   ← no interface change
       └─ bwrap-exec --user-dir /mnt/agent-data/users/{uid}
            └─ bwrap
                 --bind /mnt/agent-data/users/{uid} /mnt/agent-data/users/{uid}  ← mount at actual path
                 --setenv USER_DIR /mnt/agent-data/users/{uid}
                 └─ LLM shell: cat $USER_DIR/memories/...
```

```
_render_config_prompt(user_id="abc-123")
  └─ "- /mnt/agent-data/users/abc-123/ — Your personal folder (also: $USER_DIR)"
```

**Core:** bwrap uses allow-list mount approach, so paths not explicitly mounted do not exist in namespace. If `/data/user/` alias is removed and actual path (`/mnt/agent-data/users/{uid}`) is directly mounted, `/data/user/` disappears but actual path remains accessible.

## Implementation Plan

### Phase 1: bwrap-exec script change

File: `docker/nointern/agent-runtime/bwrap-exec`

Changes:
- Header comment: change `--user-dir <path>` description to "mount to actual path instead of /data/user alias + inject USER_DIR env var".
- In `if [[ -n "$USER_DIR" ]]; then` block:
  - `BWRAP_ARGS+=(--bind "$USER_DIR" /data/user)` → `BWRAP_ARGS+=(--bind "$USER_DIR" "$USER_DIR")` (mount to actual path)
  - Add `BWRAP_ARGS+=(--setenv USER_DIR "$USER_DIR")`
- Keep `/data/user` mkdir → `"$USER_DIR"` mkdir behavior (directory auto creation remains).
- Add `--setenv USER_DIR` near existing `--setenv HOME /home/sandbox`.

**Reason for bwrap allow-list:** Paths not explicitly mounted in bwrap do not exist inside namespace. Need `--bind "$USER_DIR" "$USER_DIR"` to access `$USER_DIR` path inside shell.

### Phase 2: shell.py changes

File: `python/apps/nointern/src/nointern/engine/tools/shell.py`

**Change `_render_config_prompt()` parameter:**
```python
# before
def _render_config_prompt(self, *, has_agent_id: bool, has_user_id: bool, ...):
    if has_user_id:
        scope_lines.append("- `/data/user/` — Per-user storage (private)")

# after
def _render_config_prompt(self, *, has_agent_id: bool, user_id: str | None, ...):
    if user_id:
        root = self._config.agent_data_root  # or read path from settings
        user_path = f"{root}/users/{user_id}"
        scope_lines.append(
            f"- `{user_path}/` — Your personal folder (also: `$USER_DIR` in shell)"
        )
```

**Clean up `BuiltinToolkitProvider.system_prompt`:**
- Remove `/data/user/`, `/data/agent/` path table from File Storage section.
- Remove or generalize hardcoded `/data/user/`, `/data/agent/` in `present_file` example code.
- Keep only shell usage explanation (command execution, package installation).

**Change `update_context()` call sites:**
```python
# has_user_id=bool → user_id=str | None
prompt = self._render_config_prompt(
    has_agent_id=bool(agent_id),
    user_id=user_id or None,
    ...
)
```

### Phase 3: executor.py changes

File: `python/apps/nointern-sandbox-daemon/src/nointern_sandbox_daemon/executor.py`

Changes:
- Update `_build_bwrap_cmd()` comment: `--user-dir for mount` → `for USER_DIR env var injection`.
- Update `execute_command()` comment similarly.

Keep interface (`user_id` parameter) unchanged.

### Phase 4: agent_home.py and other reference cleanup

File: `python/apps/nointern/src/nointern/runtime/sandbox/agent_home.py`

- Remove or update comment if `/data/user` path constant exists.

File: `python/apps/nointern/src/nointern/services/file_api_client.py`

- Check `/data/user` references and clean if needed (file-api already handles path based on user_id, so impact is minimal).

## Feasibility Verification

| Item | Result |
|------|----------|
| bwrap `--setenv` support | ✅ already used for `HTTP_PROXY`, etc. |
| bwrap `--bind "$USER_DIR" "$USER_DIR"` behavior | ✅ bwrap automatically creates destination directory inside namespace |
| executor.py interface unchanged | ✅ keep `user_id` parameter |
| file-api tool impact | ✅ none — file-api already handles path based on user_id |
| memory collection (`collect_memory_prompt`) | ✅ none — goes through file-api layer, unrelated to bwrap mount |
| `$USER_DIR` usage in shell exec | ✅ accessible with `--bind "$USER_DIR" "$USER_DIR"` + `--setenv USER_DIR` combination |
| pass `user_id` into `_render_config_prompt()` | ✅ `context.user_id` already available in `update_context()`, only parameter change needed |
| actual path construction (`/mnt/agent-data/users/{user_id}`) | ✅ same pattern already used in `agent_home.py` — construct same way |

## Risks

| Risk | Mitigation |
|--------|----------|
| Existing LLM prompt patterns hardcode `/data/user/` | Remove from `_render_config_prompt()` and `system_prompt`, so LLM naturally switches to `$USER_DIR` pattern |
| Confusion from changed meaning of bwrap-exec `--user-dir` | Clearly update header/comment/option explanation |
| LLM behavior in existing session uses `/data/user/` path | After deployment, LLM prompt updates and naturally transitions. During transition, `/data/user/` path failure is visible as error message and LLM can retry with `$USER_DIR` |
