---
title: "nointern Memory Design"
tags: [architecture, engine]
created: 2026-03-22
updated: 2026-04-26
implemented: 2026-04-26
---

# nointern Memory Design

Provides a feature for agent to accumulate **domain expertise** beyond conversation.

When model judges during conversation that "this is important in future," it stores information as markdown file, and at every conversation start an index is injected into system prompt so agent can use knowledge learned from previous conversations.

**Note:** Daily Log (activity log) is designed as separate feature. This document covers only memory.

## Implementation Status (2026-04-24)

Design's **scope structure (agent/user)**, **file format (YAML frontmatter + Markdown)**, **MEMORIES.md index**, and **prompt injection rules** are implemented. However, items below differ from original design:

- **URI scheme**: `/data/agent/memories/...` → adopted as **absolute paths** `/data/agent/memories/...`, `/data/user/{user_id}/memories/...`. `shared:///` notation in document body is not used in current prompts/code.
- **Storage medium**: "S3 (RustFS)" → **EFS + sandbox-daemon File-API facade**. In K8s, PVC `agent-home-efs` subPath `agents/{agent_id}/data` is mounted at `/data` (`python/apps/nointern/src/nointern/runtime/sandbox/agent_home_k8s.py:463-474`). In Docker, host bind (`agent_home_docker.py:89`). Main container and sandbox-daemon container share same mount, and daemon serves same path as HTTP File-API.
- **FileApiClient**: `services/file_api_client.py`. Only `agent_id` is required parameter. Design-time resolve arguments such as `workspace_id / session_id / SharedScope` enum were not adopted.
- **`collect_memory_prompt()` signature**: Unlike example in "Implementation Details" section below, actual implementation receives only three arguments `(ss, agent_id, user_id)` and directly queries absolute path strings with `ss.get(abs_path, agent_id=...)` (`engine/tools/shell.py:255-326`).
- **DB model**: no memory-specific table. Only `RDBAgent.memory_enabled` flag exists.

Design intent in body (memory center of gravity, scope selection criteria, file rules, etc.) remains valid; read only path notation according to facts above.

## Core Principles

- **Agent is protagonist**: center of gravity of memory is accumulation of agent role expertise.
- **No new tools**: managed with existing file tools (read, write, edit, glob, grep, delete).
- **Prompt-driven**: save/query/delete rules are defined in system prompt.
- **Progressive Disclosure**: only MEMORIES.md index is always loaded; details are read as needed.
- **Current state first**: if memory and actual state conflict, current state is source of truth.

## Difference from CC

| Item | Claude Code | nointern |
|------|------------|---------|
| **Storage** | local filesystem | EFS mount (`/data/agent`, `/data/user/{user_id}`) + sandbox-daemon File-API facade |
| **User** | one user per project | N users per agent |
| **Scope** | single project | `agent` (shared globally) + `user` (per-user isolation) |
| **Memory center of gravity** | user (user's project learning) | agent (role expertise accumulation) |

### Memory Center of Gravity

```
CC:       user memory ████████████  |  project memory ████
nointern: agent memory ████████████████  |  user memory ████
```

nointern agent **receives one role and performs long-term mission**.

**Agent memory = role expertise (heavyweight)**

| Agent role | Accumulated knowledge |
|-------------|-------------|
| on-call agent | infra topology, incident history, known issues, runbook locations |
| business analysis agent | product domain model, KPI definitions, dashboard locations, market context |
| code review agent | codebase architecture, team coding rules, past review patterns |

**User memory = personalization (lightweight)**

| Type | Example |
|------|------|
| profile | "has engineering background" |
| preference | "prefers viewing metrics directly" |

## Agent Settings

### memory_enabled (default: on)

Memory can be enabled/disabled per agent. Disable when long-term memory is unnecessary, such as simple translation agent. When disabled, memory index and rules are not injected into prompt.

### Subagent

Memory is **disabled** in Subagent. No prompt injection, and no memory storage.

Current subagent's `shared:///agent/` connects to its own scope, not parent, so it cannot read parent's memory. These two are technical debt tracked in separate issues:
- `issues/subagent-shared-scope-routing.md`
- `issues/subagent-memory-write-restriction.md`

## Storage Structure

### Directory Layout

```
/data/agent/memories/          ← agent role expertise (shared by all users)
├── MEMORIES.md                    ← index (injected into system prompt)
├── reference_infra_topology.md    ← infra structure
├── reference_runbooks.md          ← runbook locations
├── project_known_issues.md        ← known issues list
├── feedback_pr_review.md          ← common agent feedback
└── reference_dashboards.md        ← dashboard/metric locations

/data/user/{user_id}/memories/           ← per-user personalization (only that user)
├── MEMORIES.md                    ← per-user index
├── user_profile.md                ← user profile
└── feedback_response_style.md     ← per-user preference
```

### Filename Convention

`{type}_{topic}.md`:

| Prefix | Type | Example |
|--------|------|------|
| `user_` | user | `user_profile.md` |
| `feedback_` | feedback | `feedback_no_mocking.md` |
| `project_` | project | `project_auth_migration.md` |
| `reference_` | reference | `reference_jira.md` |

### Scope Selection Criteria

| CC type | Default scope | Save to agent | Save to user |
|---------|-----------|-------------|-------------|
| **user** | `user/` | — | always |
| **feedback** | judgment needed | team rule | personal preference |
| **project** | judgment needed | team-wide context | personal work |
| **reference** | `agent/` | always | — |

## Memory File Format

YAML frontmatter + Markdown body:

```markdown
---
name: no-mocking
description: Don't mock the database in integration tests — use real DB instead
type: feedback
created: 2026-03-22
---

Integration tests must hit a real database, not mocks.

**Why:** Last quarter, mocked tests passed but the prod migration failed.

**When to apply:** Writing or reviewing integration tests that touch the database.
```

### Fields

| Field | Required | Description |
|------|------|------|
| `name` | O | memory identifier |
| `description` | O | one-line summary — shown in index, evidence for relevance judgment |
| `type` | O | `user`, `feedback`, `project`, `reference` |
| `created` | O | creation date |

### Body Structure by Type

**feedback**: rule → **Why** → **When to apply**
**project**: fact/decision → **Why** → **Impact**
**reference**: location/access method → **When to reference**
**user**: profile/preference → **How this affects collaboration**

## MEMORIES.md Index

Separated by type sections, each item is link + one-line description:

```markdown
# Agent Memories

## Feedback
- [No mocking](feedback_no_mocking.md) — Don't mock DB in integration tests

## Reference
- [Infra topology](reference_infra_topology.md) — EKS 3 clusters
- [Runbooks](reference_runbooks.md) — Runbook locations and procedures
```

### Size Limit

| Item | Limit |
|------|------|
| agent MEMORIES.md | max 100 lines |
| user MEMORIES.md | max 100 lines |

Agent memory is likely to reach 100 lines first. This point is trigger to consider introducing search feature.

## System Prompt Injection

### Injection Structure

```
┌──────────────────────────┐
│ ## Shared Storage        │ ← scope guide
├──────────────────────────┤
│ ## Skills                │ ← skill list
├──────────────────────────┤
│ ## Memories              │ ← memory index + rules
│   ### Agent Memories     │
│   ### User Memories      │
│   ### Memory Rules       │
├──────────────────────────┤
│ Allowed/Denied domains   │ ← domain settings
└──────────────────────────┘
```

### Conditional Injection

- no agent_id → omit Agent Memories section
- no user_id → omit User Memories section
- no MEMORIES.md → omit that section
- Memory Rules always injected (to enable first memory save)

## Memory Lifecycle

### Creation

When model judges during conversation "this is important in future":
1. Check existing memory (read index)
2. write new file or edit existing file
3. update MEMORIES.md index

### Query

Check relevant items in index → load individual file with `read` → cross-check with current state

### Deletion

Remove file with `delete` → remove corresponding line from MEMORIES.md

### Stale Handling

- If memory mentions filename/function name, verify in code before using.
- If conflict found, current state wins, update/delete memory.
- `project` type is most likely to become stale.

## Usage Scenarios

### Agent expertise accumulation

```
[On-call agent — week 1]
User A: "Our infra has 3 EKS clusters. prod-main, prod-gpu, staging"
Agent: → write("/data/agent/memories/reference_infra_topology.md", ...)

[On-call agent — week 2]
User B: "My pipeline dies on GPU cluster"
Agent: (check infra topology + known issues from index)
  → "There is known OOM issue on prod-gpu. Try reducing batch size."
```

### User personalization

```
User C: "I prefer seeing numbers directly, in table instead of chart"
Agent: → write("/data/user/{user_id}/memories/feedback_data_format.md", ...)
  Later, provide data to User C in table format
```

### Memory Conflict — Agent vs User

user scope overrides agent scope. When talking with that user, follow user memory; when talking with other users, follow agent memory.

## Relationship with Skill System

| Item | Skill | Memory |
|------|------|--------|
| **Storage path** | `/data/{scope}/skills/` | `/data/{scope}/memories/` |
| **Purpose** | procedural knowledge (how-to) | contextual knowledge (what/why) |
| **Update actor** | mainly admin/user | agent itself |

## Implementation Details

### Target Files

| File | Change |
|------|----------|
| `builtin.py` | add `collect_memory_prompt()`, modify `BuiltinToolkit` |
| `memory_prompt_test.py` | tests |
| `platform-skills/memory-guide/SKILL.md` | Platform skill |

### `_MEMORY_RULES_PROMPT` constant

```python
_MEMORY_RULES_PROMPT = dedent("""\
    ### Memory Rules

    Save memories when you learn something useful for **future conversations**.
    Use `write` to create memory files and `edit` to update the index.

    **When to save:**
    - User's role, expertise, preferences → `/data/user/{user_id}/memories/user_*.md`
    - Behavioral corrections ("don't do X") or confirmations → `feedback_*.md`
    - Project context not obvious from code → `project_*.md`
    - External system references → `/data/agent/memories/reference_*.md`

    **Where to save:**
    - This user only → `/data/user/{user_id}/memories/`
    - All users of this agent → `/data/agent/memories/`
    - Writing to agent/ affects ALL users — only save universally applicable knowledge

    **Do NOT save:**
    - Code patterns/architecture (read from code)
    - Git history (use git log)
    - Content already in MEMORIES.md or SKILL.md
    - Ephemeral task details only useful in this conversation

    **How to save (2-step):**
    1. Write memory file with YAML frontmatter (name, description, type, created) + body:
       `write(uri="/data/{scope}/memories/{type}_{topic}.md", content="---\n...")`
    2. Update index:
       `edit(uri="/data/{scope}/memories/MEMORIES.md", old_string="...", new_string="...")`
    If MEMORIES.md doesn't exist yet, create it with `write`.

    **Priority:** When agent and user memories conflict, follow user memory.
    **Stale check:** Verify memory claims against current state before acting on them.
    **Cleanup:** When index approaches 100 lines, remove outdated entries.""")
```

### `collect_memory_prompt()` function

```python
_MAX_MEMORY_INDEX_LINES = 100


async def collect_memory_prompt(
    ss: SkillStorageReader,
    workspace_id: str,
    session_id: str,
    agent_id: str,
    user_id: str,
) -> str:
    """Read MEMORIES.md from agent/user scopes and create prompt string."""
    parts: list[str] = [
        "## Memories", "",
        "You have a persistent memory system."
        " Memories persist across conversations.", "",
    ]

    async def _read_index(
        scope: SharedScope, aid: str, uid: str
    ) -> str | None:
        try:
            data = await ss.get_by_scope(
                scope, "memories/MEMORIES.md",
                workspace_id=workspace_id, agent_id=aid,
                user_id=uid, session_id=session_id,
            )
        except (FileNotFoundError, ValueError, OSError):
            return None
        content = data.decode("utf-8").strip()
        if not content:
            return None
        lines = content.split("\n")
        if len(lines) > _MAX_MEMORY_INDEX_LINES:
            content = "\n".join(lines[:_MAX_MEMORY_INDEX_LINES])
            content += (
                "\n\n(Index truncated at "
                f"{_MAX_MEMORY_INDEX_LINES} lines."
                " Consider cleaning up old memories.)"
            )
        return content

    tasks: list[tuple[str, SharedScope, str, str]] = []
    if agent_id:
        tasks.append(("agent", SharedScope.AGENT, agent_id, ""))
    if user_id:
        tasks.append(("user", SharedScope.USER, agent_id, user_id))

    results: dict[str, str | None] = {}
    if tasks:
        gathered = await asyncio.gather(
            *[_read_index(scope, aid, uid) for _, scope, aid, uid in tasks]
        )
        for (label, _, _, _), content in zip(tasks, gathered):
            results[label] = content

    agent_content = results.get("agent")
    if agent_content:
        parts.extend(["### Agent Memories (shared with all users)", "", agent_content, ""])

    user_content = results.get("user")
    if user_content:
        parts.extend(["### Your Memories about this User", "", user_content, ""])

    parts.append(_MEMORY_RULES_PROMPT)
    return "\n".join(parts)
```

### `BuiltinToolkit` Modification

Three places: add `self._memory_prompt = ""` to `__init__`, call `collect_memory_prompt()` in `create_tools`, inject memory section in `render_config_prompt`.

### Tests (`memory_prompt_test.py`)

Same pattern as `skill_prompt_test.py`. Reuse `FakeSharedStorage`.

Main tests:
- returns rules even with no memories
- includes agent/user index respectively
- includes both
- omits corresponding section when agent_id/user_id absent
- treats empty index as absent
- truncation + warning over 100 lines
- agent section appears before user section

### `memory-guide` Platform Skill

Loaded by agent with `/memory-guide` or automatically when memory-related question occurs. Contains storage guide by type, scope judgment criteria, index management, and stale handling rules.

## Evolution Path

```
Initial design           Phase 2               Phase 3
CC style                 CC + FTS5 search      Hybrid search
Index scan               keyword search        vector + BM25
0~50 memories            50~200                200+
```

**Phase 2 trigger**: agent memory 50+ or cases of missing relevant memory.
Markdown files from initial design are used as-is in all phases.

## Edge Cases

1. **Concurrent write**: last-write-wins on EFS. Memory is summary information, so precise concurrency unnecessary.
2. **Session without user scope**: omit User Memories; can save only to agent scope.
3. **Broken MEMORIES.md format**: injected as plain text, so no error. Naturally fixed in next conversation.
4. **Memory and skill naming**: `memories/` and `skills/` are separated. Intended coexistence.
5. **User says "ignore memory"**: handled by prompt rule. Do not delete.
