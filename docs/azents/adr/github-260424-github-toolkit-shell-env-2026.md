---
title: "GitHubToolkit Shell Env Injection Feature Historical Decision Reconstruction"
created: 2026-04-24
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: github-260424
historical_reconstruction: true
migration_source: "docs/azents/design/github-toolkit-shell-env-2026-04-24.md"
---

# GitHubToolkit Shell Env Injection Feature Historical Decision Reconstruction

- Snapshot: `github-260424`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/github-toolkit-shell-env-2026-04-24.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### github-260424/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture

```mermaid
flowchart LR
  subgraph GitHubToolkit["GitHubToolkit (existing)"]
    P["per_user_pat<br/>GitHubPATRepository"]
    A["github_app<br/>JWT → installation"]
    AP["github_app_platform<br/>JWT → installation"]
  end
  subgraph Resolver["at resolve() time"]
    P --> TOK{issue token}
    A --> TOK
    AP --> TOK
  end
  TOK -->|MCP secret (existing)| MCP["GitHub MCP Toolkit"]
  TOK -->|expose_env() (new)| SHELL["Agent shell sandbox"]
  SHELL -->|credential helper| HELPER["/usr/local/bin/<br/>nointern-git-credential"]
  HELPER -->|GH_TOKEN env| GIT["git push / fetch"]
  SHELL -->|GH_TOKEN env| GH["gh CLI"]
  MCP --> API[(api.github.com)]
  GIT --> API
  GH --> API
```

1. At Agent session start, `GitHubToolkitProvider.resolve()` issues token by auth mode.
2. Same token branches into two paths:
   - **MCP secret** (existing) — for Octokit function calls
   - **Shell env** (new) — return by `Toolkit.expose_env()` → `BuiltinToolkit.set_peer_toolkits` → `_collect_secret_env` → `sandbox.exec(env=...)`
3. `git` / `gh` in Sandbox authenticate automatically through env path.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
