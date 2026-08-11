---
title: "Runtime Process Containment Removal Implementation Plan"
created: 2026-08-11
tags: [runtime, security, implementation]
---

# Runtime Process Containment Removal Implementation Plan

- Requirements: `runtime-260811/REQ`
- ADR: `runtime-260811/ADR`
- Design: `runtime-260811/DESIGN`, revision 1
- Approved mechanisms: M1, M2, M3, M4, M5, M6, M7
- Design delta: None
- Delivery shape: one cohesive PR because Profile, Provider, Runner, deployment, and generated contracts cannot be removed independently without unsupported intermediate states.
- Owner: primary agent
- Independent reviewer: code-review skill, read-only review against the approved snapshot and final diff

## Phase

1. Remove the active containment contract and implementation across Core/Profile, Runner, Providers, deployment, E2E, UI, generated clients, and living specifications; validate compatibility and repository-wide absence; create one PR and monitor CI.

## Removal obligations

- Remove Profile containment modules, statuses, capability derivation, API schemas, generated clients, and UI.
- Remove bwrap, qualification, launcher, bootstrap configuration, and image dependency.
- Remove Docker and Kubernetes AppArmor, RuntimeClass, capabilities, privilege, mounts, environment, probes, and deployment settings used only by containment.
- Remove containment-specific CI/E2E lanes and fixtures.
- Preserve old `process_containment: null` input compatibility while rejecting non-null documents.
- Preserve direct and DinD runtime behavior and ordinary Workspace path authorization.

## Validation

- Focused tests for Core/Profile, Runner, Docker Provider, Kubernetes Provider, Helm, runtime-control, admin web, and testenv.
- Regenerate OpenAPI and Python/TypeScript clients from source.
- Run Ruff, ty, pytest, TypeScript format/lint/typecheck/build as applicable.
- Run repository-wide active-reference absence checks outside immutable historical snapshot documents.
- Run code review and spec review before commit and PR creation.
