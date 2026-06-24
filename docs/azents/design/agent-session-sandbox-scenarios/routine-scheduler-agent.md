---
title: "Scenario: Routine Scheduler Agent"
tags: [architecture, engine, scheduler]
created: 2026-05-03
updated: 2026-05-03
implemented: 2026-05-03
---

# Scenario: Routine Scheduler Agent

## Scenario Summary

Routine scheduler posts daily morning weather, lunch menu, today's schedule, and similar information to a Discord channel at scheduled times. When users ask schedule details, it checks them and also handles simple web searches.

## Requirement Analysis

### Functional Requirements

- Send proactive message at fixed time or interval.
- Deliver user questions to raw session through Discord channel watch.
- Use API tools such as weather, schedule, menu, and web search.
- Result of scheduled trigger is posted to configured Discord channel/thread only when agent explicitly calls Discord output tool.
- Web raw session can be used for admin debugging/manual execution/status check.

### Non-functional Requirements

- Since sandbox is mostly unnecessary, sandbox disabled should be default.
- Even when scheduled trigger and user question arrive at same time, agent run is serialized by default.
- Proactive output permission must be explicitly specified in watch/trigger configuration.

## Required Concepts

- Persistent Agent
- Raw Session
- Scheduled Trigger
- Discord Channel Watch
- Event Origin / Schedule Origin
- Output Sink
- Capability Profile

## Technical Spec

### Agent policy

```yaml
agent_kind: persistent
sandbox_policy: disabled
run_concurrency: 1
capabilities:
  web_search: true
  calendar: true
  weather: true
  filesystem: false
  shell: false
```

### Schedule model

```text
schedule_id
agent_id
target_watch_id
cron or interval
last_run_at
next_run_at
```

### Event origin

Scheduled event has following origin.

```json
{
  "source": "scheduler",
  "schedule_id": "morning-weather",
  "target": {
    "source": "discord",
    "channel_id": "..."
  }
}
```

## Acceptance Criteria

- Scheduled trigger can send message to Discord channel without sandbox.
- Discord channel question enters same raw session.
- filesystem/shell tools are not exposed.
- If schedule target does not exist or outbound permission is absent, proactive post is rejected.
