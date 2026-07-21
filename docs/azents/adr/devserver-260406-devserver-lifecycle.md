---
title: "Full-stack Local Test Environment — Stage 1b (devserver lifecycle) Historical Decision Reconstruction"
created: 2026-04-06
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: devserver-260406
historical_reconstruction: true
migration_source: "docs/azents/design/devserver-lifecycle.md"
---

# Full-stack Local Test Environment — Stage 1b (devserver lifecycle) Historical Decision Reconstruction

- Snapshot: `devserver-260406`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/devserver-lifecycle.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### devserver-260406/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture

```mermaid
flowchart LR
    Agent([Agent]) -->|up/down/status/logs| CLI[testenv/nointern/devserver.py]
    CLI -->|docker compose up -d| Compose[testenv compose]
    CLI -->|uv run alembic upgrade head| Alembic[Alembic]
    CLI -->|tmux new-session| Tmux[tmux: nointern-testenv-devserver]
    Tmux -->|uv run python src/cli/devserver.py| Devserver[devserver process]
    Devserver --> PublicAPI[:8010 Public API]
    Devserver --> AdminAPI[:8011 Admin API]
    Devserver --> Worker[Engine Worker]
    CLI -->|pipe-pane -o| Log[.state/devserver.log]
    CLI -.->|readiness poll| PublicAPI
    CLI -.->|readiness poll| AdminAPI
    CLI --- State[.state/devserver.state.json]

    Human([Developer]) -->|tmux attach| Tmux
    Human -->|python bin/devserver.sh| DevserverFG[foreground devserver]
    DevserverFG -->|same src/cli/devserver.py| Devserver
```

**Key point**: tmux session serves as "process supervisor". Instead of PID management, check liveness with `tmux has-session`, send SIGINT with `tmux send-keys C-c` to induce graceful shutdown, and capture stdout/stderr to file with `tmux pipe-pane`.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
