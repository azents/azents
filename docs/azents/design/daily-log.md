---
title: "nointern Daily Log Design"
tags: [architecture, engine]
created: 2026-03-22
updated: 2026-03-22
implemented: 2026-03-22
---

# nointern Daily Log Design

## Purpose

Record what the agent did without relying on model judgment.

This is separate from Memory (curated):

| | Memory | Daily Log |
|--|--------|-----------|
| **Purpose** | Accumulate expertise | Activity record |
| **Analogy** | Textbook | Work journal |
| **Author** | Agent model (judgment during conversation) | Engine (background batch) |
| **Judgment** | "Is this important for the future?" | No judgment, mechanical record |
| **Update** | Can update/delete | append-only |
| **Path** | `shared:///agent/memories/` | `shared:///agent/daily-log/` |

### Problems Solved by Daily Log

**1. Handoff — in-progress context not yet knowledge**

```
User A: "I'm investigating GPU OOM. Batch size is suspected, not confirmed yet"
→ Not confirmed, so not stored in memory
→ If User B asks about same case, agent does not know
→ Recorded in daily log
```

**2. Compensation — things model did not judge important**

```
User: "I tested it in staging and it was not great"
→ Model judges "not important enough to save"
→ Later: "What did we try in staging?" → can find from daily log
```

### Agent Setting

`daily_log_enabled` (default: on) — can be enabled/disabled per agent. Disable for agents that do not need long-term activity records, such as simple translation agents. Disabled for **Subagents**.

### Privacy

Daily log is stored at agent scope (team-shared). Other users can see it, and it is defined as **team work record**. This is similar to team members' activities being visible in a Slack channel.

## Storage

### Path

```
shared:///agent/daily-log/
├── 2026-03-20.md
├── 2026-03-21.md
└── 2026-03-22.md
```

### Format

One entry = one line. Timestamp is assigned by engine.

```markdown
[14:15] Investigated GPU OOM incident. Confirmed batch size as cause. Deployment planned tomorrow.
[16:10] Guided deployment process question to runbook.
[17:40] Reviewed GPU OOM fix PR. Confirmed batch size change 512→256.
```

- Do not include user information — from agent perspective, what happened matters.
- One line means 10 entries = 10 lines, predictable tokens (~30 tokens/line).

### `append_log` tool

Single-purpose tool given to summary model. Provide only this tool instead of general write to block access to other files at source.

```python
append_log(summary="Investigated GPU OOM incident. Confirmed batch size as cause. Deployment planned tomorrow.")
```

Engine handles:
- which file to write (`agent/daily-log/2026-03-22.md`)
- timestamp assignment (`[14:15]`)
- append-only guarantee

Model generates **only summary text**.

## Triggers

### Default trigger: session idle 30 minutes

If 30 minutes have passed since session's last message and unsummarized messages exist, summarize that session's conversation.

30 minutes represents end of one conversation segment:
- does not cut off mid-conversation
- one conversation context becomes one summary
- summary quality is high (sees full context)

Advanced setting can adjust interval per agent.

### Fallback trigger: on compaction

If user keeps talking without resting for 30 minutes, idle trigger does not run. If unsummarized conversation exists when compaction occurs, run summary first.

```
normal:   idle 30 min → batch job detects → summarize
fallback: compaction occurs → summarize first → continue compaction
```

### Batch job

A batch job running every 5 minutes scans all agent sessions.

```
every 5 minutes:
  query "sessions whose last_message_at is older than 30 minutes and have unsummarized messages"
  → run summary for those sessions
```

No per-session timer is needed; idle sessions are detected only by DB query. idle 30 minutes + batch 5 minutes = recorded after at most 35 minutes.

## Summary Generation

### Model

Use agent's `summary_model` (formerly `compaction_model`). This model is shared for compaction summaries, daily log summaries, and title summaries. Using lightweight model (Haiku-level) as default reduces cost.

### Input

Query unsummarized messages for that session from DB. Original conversation is already stored in `events` table, so no separate per-turn record is needed.

### When context window is exceeded

Since summaries are session-scoped, single session rarely exceeds context window. If it happens, take only latest N tokens from that session.

### Prompt

```
Summarize what should be remembered from this conversation in one line.
If nothing is worth recording, respond with SKIP.
```

Model output only goes through `append_log` tool and has no path delivered to user.

## Duplicate Prevention

Store `last_summarized_message_id` or `last_summarized_at` per session in DB to avoid summarizing already summarized messages again.

```
14:00 messages 1~5  → 14:35 idle → summary (1~5) → marker update
14:40 messages 6~8  → 15:15 idle → summary (6~8 only)
```

## Prompt Injection

### Injection timing

Read once and cache at session or run start. If read every turn, prompt prefix changes and breaks LLM cache, so fix at session/run scope.

### Injected content

Latest 10 entries from today + yesterday logs + older log path guidance:

```
## Recent Activity
[17:40] Reviewed GPU OOM fix PR. Confirmed batch size change 512→256.
[16:10] Guided deployment process question to runbook.
[16:00] Investigated GPU OOM incident. Confirmed batch size as cause. Deployment planned tomorrow.
(Older entries: shared:///agent/daily-log/)
```

- Max 10 lines (~300 tokens), fixed size
- If agent needs older records, access with `read`/`grep`

### Injection order with Memory

```
┌──────────────────────────┐
│ ## Shared Storage        │
├──────────────────────────┤
│ ## Skills                │
├──────────────────────────┤
│ ## Memories              │ ← curated memory index
├──────────────────────────┤
│ ## Recent Activity       │ ← latest 10 daily log entries
├──────────────────────────┤
│ Allowed/Denied domains   │
└──────────────────────────┘
```

## Retention Period

Old daily logs are automatically deleted. Default is 7 days — if information older than 7 days was important, it should already have been promoted to curated memory.

## Comparison with OpenClaw

| | OpenClaw | nointern |
|--|---------|---------|
| **Purpose** | Prevent context loss (structure before compaction) | Activity record (what agent did) |
| **Trigger** | silent turn right before compaction | session idle 30 minutes (batch detection) |
| **Author** | main model (silent turn) | summary model (background) |
| **Format** | free-form (model decides) | one-line summary (`append_log` tool) |
| **Injection** | model reads all with read tool | engine injects latest 10 |
| **User exposure** | hidden with NO_REPLY (structurally not delivered) | completely separate from user conversation |

## Implementation Notes

### Use Existing Infrastructure

| Need | Existing infrastructure |
|------|-----------|
| conversation data | `events` table (already stores all messages) |
| idle detection | query `events.created_at` |
| summary model | `summary_model` (agent setting) |
| S3 write | `put_by_scope` API |
| compaction timing | 90% threshold detection in `engine.py` |

### Newly Needed

| Need | Description |
|------|------|
| batch job | every 5 minutes, scan all agent sessions |
| duplicate prevention marker | per-session `last_summarized_message_id` (DB table/column) |
| `append_log` tool | summary-model-only, single purpose |
| `collect_daily_log_prompt()` | collect latest 10 entries and inject prompt |
| retention management | auto-delete old log files |
