---
title: "Session Workspace Project Contract Historical Decision Reconstruction"
created: 2026-05-09
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: projects-260509
historical_reconstruction: true
migration_source: "docs/azents/design/session-workspace-projects.md"
---

# Session Workspace Project Contract Historical Decision Reconstruction

- Snapshot: `projects-260509`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/session-workspace-projects.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### projects-260509/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture

```mermaid
erDiagram
    Workspace ||--o{ Agent : contains
    Workspace ||--o{ ProjectSource : has
    Agent ||--|| AgentRuntime : owns
    AgentRuntime ||--o{ AgentSession : rotates
    AgentRuntime ||--o{ SessionWorkspaceProject : has
    ProjectSource ||--o{ SessionWorkspaceProject : loads

    AgentRuntime {
        string id PK
        string workspace_id FK
        string agent_id FK
        string current_session_id FK
        string runtime_state
    }
    SessionWorkspaceProject {
        string id PK
        string agent_runtime_id FK
        string project_source_id FK
        string path
        string name
        string source_type
        bool loaded
        string error_message
        datetime loaded_at
        datetime created_at
        datetime updated_at
    }
    ProjectSource {
        string id PK
        string workspace_id FK
        string source_type
        string name
        string object_key
        string sha256
        int size_bytes
    }
```

```mermaid
flowchart TD
    A[User uploads archive] --> B[Create workspace Project Source]
    B --> C[User loads source into Agent]
    C --> D[Create Project row loaded=false]
    D --> E[Sandbox poll detects unloaded Project]
    E --> F[Download source by project_id]
    F --> G[Safe extract to temp]
    G --> H[Overwrite target folder]
    H --> I[ACK loaded=true]
    I --> J[Inject loaded Projects into prompt]
```

### Explicit source section: API / Tool contract

Initial implementation keeps backend API and engine tool contract at following level.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
