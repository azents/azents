---
title: "Slack Toolkit Implementation Plan"
tags: [backend, engine]
created: 2026-03-12
updated: 2026-03-23
implemented: 2026-03-23
document_role: supporting
document_type: supporting-plan
migration_source: "docs/azents/design/slack-toolkit-impl.md"
---

# Slack Toolkit Implementation Plan

Implementation plan for [Slack Toolkit design](./slack-260312-slack-toolkit.md). Phase 1 performs prerequisite refactors (interface awareness, Block Kit parsing, message formatting improvement), and Phase 2 implements the actual Slack Toolkit.

## Current Status

Service Toolkit base refactor is complete:
- Split `ToolkitProvider.resolve()` → `Toolkit` ABC ✅
- Extracted `McpBasedToolkitProvider` ✅
- DI-based `get_toolkit_registry()` ✅
- Unified `resolve_agent_tools()` code path ✅

Not complete — prerequisite work for Slack Toolkit:
- `ToolkitContext` / `SessionMessage` has no interface information
- No Block Kit parsing module
- `history.py` uses only `msg["text"]` (ignores Block Kit, does not use `original_text`)
- `streaming.py` does not store `original_text` in metadata
- File metadata has no `file_id`

## Phase 1: Prerequisite Refactors

Improvements to existing Slack integration code. These changes have independent value even without Slack Toolkit.

### 1-1. Interface awareness — extend `SessionMessage` + `ToolkitContext`

Prerequisite for automatic Slack Toolkit binding. `resolve_agent_tools()` must know interface type.

**Changed files:**

| File | Change |
|------|------|
| `broker/types.py` | Add `interface_type: str \| None`, `interface_channel_id: str \| None` to `SessionMessage` |
| `core/tools.py` | Add same fields to `ToolkitContext` |
| `worker/engine.py` | Pass `SessionMessage` → `ToolkitContext` in `process_message()` |
| `services/slack/handler.py` | Set `interface_type="slack"`, `interface_channel_id=channel_id` when creating `SessionMessage` |

`ConversationSessionType` already has `SLACK = "slack"`, `DISCORD = "discord"`, so `interface_type` value matches this enum.

### 1-2. Common Block Kit parsing module

Common utility to accurately extract text from Slack messages.

**New file:** `services/slack/blocks.py`

```python
def extract_text_from_blocks(blocks: list[dict[str, Any]]) -> str:
    """Extract markdown-like text from Block Kit blocks."""
    ...
```

Supported scope:
- Blocks: `rich_text`, `section`, `context`, `header`
- `rich_text` children: section, list (bullet/ordered), preformatted, quote
- Inline: text (preserve bold/italic/code), link (preserve URL), emoji, user/channel mention, broadcast

### 1-3. Message formatting improvement — `history.py` + `streaming.py`

Improve history collection quality of existing Slack integration.

**Changed files:**

| File | Change |
|------|------|
| `services/slack/streaming.py` | Add `original_text` to `bot_metadata.event_payload` |
| `services/slack/history.py` | Change `_msg_to_input()` text extraction to 3-step priority |
| `services/slack/history.py` | Include `file_id` in file metadata |

`_msg_to_input()` text extraction priority:
1. Our bot message + `metadata.event_payload.original_text` → original markdown
2. `blocks` exists → call `extract_text_from_blocks()`
3. `text` (mrkdwn) fallback

File metadata change:
```python
# Before
metadata["files"] = ", ".join(f.get("name", "file") for f in files)

# After
metadata["files"] = ", ".join(
    f"{f.get('name', 'file')} (id: {f.get('id', '')})" for f in files
)
```

### Phase 1 Verification

```bash
cd /home/code/repos/azents/azents/python/apps/nointern
uv run ruff check --fix . && uv run ruff format .
uv run pyright
uv run pytest
```

Verify existing Slack integration behavior with E2E:
```bash
cd /home/code/repos/azents/azents/python/apps/nointern-e2e
uv run pytest
```

---

## Phase 2: Slack Toolkit Implementation

### 2-1. Data model — `SlackAgentConfig` table

**New file:** `rdb/models/slack_agent_config.py`

```python
class RDBSlackAgentConfig(Base):
    __tablename__ = "slack_agent_configs"

    agent_id: Mapped[str]  # PK, FK → agents
    read: Mapped[bool]  # default true
    write: Mapped[bool]  # default false
    reactions: Mapped[bool]  # default true
    privacy: Mapped[bool]  # default true
```

Create **Alembic migration**.

**New file:** `repos/slack_agent_config.py`

- `get_by_agent_id()` — returns `None` when absent (use defaults)
- `upsert()` — save/update configuration

### 2-2. Add `ToolkitType.SLACK`

**Changed file:** `core/tools.py`

```python
class ToolkitType(enum.StrEnum):
    SHELL = "shell"
    MCP = "mcp"
    SLACK = "slack"
```

### 2-3. `SlackToolkitProvider` + `SlackToolkit`

**New file:** `engine/tools/slack.py`

```python
class SlackToolkitConfig(BaseModel):
    """Config converted from SlackAgentConfig."""
    read: bool = True
    write: bool = False
    reactions: bool = True
    privacy: bool = True

class SlackToolkitProvider(ToolkitProvider[SlackToolkitConfig]):
    """Slack Toolkit Provider. resolve() resolves bot token."""
    # DI: slack_installation_repository, session_data_storage

    async def resolve(self, config, context) -> SlackToolkit:
        # Fetch bot token from slack_installations
        # Return SlackToolkit instance
        ...

class SlackToolkit(Toolkit[SlackToolkitConfig]):
    """Resolved Slack Toolkit. create_tools() creates tool list."""

    async def create_tools(self, config, context) -> list[Tool]:
        # Filter tools according to config.read/write/reactions
        # Decide access scope through config.privacy + context.interface_channel_id
        ...
```

### 2-4. Tool implementation

Implement tool functions by category in `engine/tools/slack.py` or submodules.

**Read:**

| Tool | Slack API | Description |
|------|-----------|------|
| `list_channels` | `conversations.list` | List accessible channels |
| `read_channel_history` | `conversations.history` | Read channel messages (limit, oldest, latest) |
| `read_thread` | `conversations.replies` | Read thread |
| `get_user_info` | `users.info` | Get user info |
| `download_file` | `files.info` + URL download | Download file → SharedDataStorage |

**Reactions:**

| Tool | Slack API | Description |
|------|-----------|------|
| `add_reaction` | `reactions.add` | Add emoji reaction |
| `remove_reaction` | `reactions.remove` | Remove emoji reaction |

**Write:**

| Tool | Slack API | Description |
|------|-----------|------|
| `send_message` | `chat.postMessage` | Send message |
| `reply_to_thread` | `chat.postMessage` (thread_ts) | Reply to thread |
| `upload_file` | `files.uploadV2` | Upload file (read from SharedDataStorage) |

### 2-5. Privacy mode implementation

Inside `SlackToolkit.create_tools()`, restrict channel access scope according to Privacy mode.

- Check current channel ID through `context.interface_channel_id`
- Determine channel type with `conversations.info` (`is_channel`, `is_group`, `is_im`)
- Apply Privacy policy to channel parameter validation logic for read/write tools

### 2-6. Extend `resolve_agent_tools()` — automatic binding

**Changed file:** `engine/run/resolve.py`

Add interface-dependent Toolkit injection logic **after** existing AgentToolkit list handling.

```python
async def resolve_agent_tools(
    agent_id: str,
    context: ToolkitContext,
    *,
    toolkit_registry: dict[str, ToolkitProvider[Any]],
    # ... existing parameters
    slack_toolkit_provider: SlackToolkitProvider | None = None,
    slack_agent_config_repository: SlackAgentConfigRepository | None = None,
) -> list[ResolvedToolkit]:
    # Existing AgentToolkit handling (unchanged)
    ...

    # Interface-dependent Toolkit automatic binding
    if context.interface_type == "slack" and slack_toolkit_provider is not None:
        config = await _resolve_slack_config(
            agent_id, session, slack_agent_config_repository
        )
        if config.read or config.write or config.reactions:
            resolved = await slack_toolkit_provider.resolve(config, ...)
            tools = await resolved.create_tools(config, context)
            if tools:
                results.append(ResolvedToolkit(...))

    return results
```

### 2-7. DI wiring

**Changed files:**

| File | Change |
|------|------|
| `engine/tools/deps.py` | Register `SlackToolkitProvider` DI, do not add to `get_toolkit_registry()` |
| `worker/deps.py` | Pass `slack_toolkit_provider` to `get_engine_worker()` |
| `worker/engine.py` | Add `slack_toolkit_provider` field to `EngineWorker`, pass it when calling `resolve_agent_tools()` |

### Phase 2 Verification

```bash
cd /home/code/repos/azents/azents/python/apps/nointern
uv run ruff check --fix . && uv run ruff format .
uv run pyright
uv run pytest
```

E2E: Ask agent in Slack channel to read channel history, add reaction, and similar operations, then verify behavior.

## Execution Order Summary

| Step | Content | Impact scope |
|------|------|----------|
| **Phase 1** | | |
| 1-1 | Interface awareness (SessionMessage + ToolkitContext) | `broker/types.py`, `core/tools.py`, `worker/engine.py`, `services/slack/handler.py` |
| 1-2 | Block Kit parsing module | `services/slack/blocks.py` (new) |
| 1-3 | Message formatting improvement (history + streaming) | `services/slack/history.py`, `services/slack/streaming.py` |
| **Phase 2** | | |
| 2-1 | SlackAgentConfig table + repository | `rdb/models/`, `repos/`, migration |
| 2-2 | ToolkitType.SLACK | `core/tools.py` |
| 2-3 | SlackToolkitProvider + SlackToolkit | `engine/tools/slack.py` (new) |
| 2-4 | Tool implementation (read/reactions/write) | `engine/tools/slack.py` |
| 2-5 | Privacy mode | `engine/tools/slack.py` |
| 2-6 | Extend resolve_agent_tools() | `engine/run/resolve.py` |
| 2-7 | DI wiring | `engine/tools/deps.py`, `worker/deps.py`, `worker/engine.py` |
