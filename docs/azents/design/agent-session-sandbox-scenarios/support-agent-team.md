---
title: "Scenario: Agent Support Team"
tags: [architecture, engine, delegation]
created: 2026-05-03
updated: 2026-05-03
implemented: 2026-05-03
document_role: supporting
document_type: supporting-supporting
migration_source: "docs/azents/design/agent-session-sandbox-scenarios/support-agent-team.md"
---

# Scenario: Agent Support Team

## Scenario Summary

When a user asks a question in Slack IT team channel, a Slack thread is created and one support agent is assigned. One thread is handled exclusively by assigned agent, and that agent also handles only one thread. Since a new agent is created for each question, 300 questions per day can create 300 agents.

Manager agent summarizes work records of all support agents once per day and proposes new work flows.

## Requirement Analysis

### Functional Requirements

- Create Slack thread when new question is detected.
- Create ephemeral support agent per thread.
- Support agent watches only one thread.
- Support agent uses API tools such as FAQ, internal document search, Slack history, and ticket creation.
- Delegate difficult work requiring sandbox to specialist agent.
- Manager agent reads WorkLog and creates daily report.
- Workflow proposed by manager must be reflectable as template/team skill.

### Non-functional Requirements

- Support agent is high-cardinality spawned agent, so sandbox disabled is default.
- Agent count can grow large, but sandbox count must be bounded by specialist agent count.
- Thread ownership must be clear, and multiple support agents must not attach to one thread.
- Work record must remain as structured WorkLog, not only raw session transcript.

## Required Concepts

- Agent Template
- Ephemeral Agent
- Slack Thread Watch
- Assignment Router
- WorkLog
- Manager Agent
- Task Delegation
- Specialist Agent
- Template / Team Skill

## Technical Spec

### Agent template

```yaml
template: it-support-agent
spawn_mode: per_slack_thread
sandbox_policy: disabled
run_concurrency: 1
capabilities:
  docs_search: true
  slack_history_search: true
  ticket_create: true
  shell: false
  filesystem: false
```

### Thread watch constraint

```text
unique(source, channel_id, thread_ts)
unique(agent_id) for support spawned agents
```

### WorkLog

```text
agent_id
template_id
source
channel_id
thread_ts
question
actions_taken
resolution
status
started_at
completed_at
```

### Delegation

Support agent puts work into specialist agent queue through `delegate_task`. DelegationTask must include original Slack thread origin. Result is received by source support agent, which explicitly calls Slack output tool to explain to user if needed.

## Acceptance Criteria

- One thread and one support agent are created per question.
- sandbox/file/shell tools are not exposed to support agent.
- Difficult work enters specialist agent queue as delegation task.
- Manager agent can create daily report based on WorkLog.
