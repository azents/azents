---
title: "Sequential Input Buffer Preparation Historical Decision Reconstruction"
created: 2026-07-12
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: sequential-260712
historical_reconstruction: true
migration_source: "docs/azents/design/sequential-input-buffer-preparation.md"
---

# Sequential Input Buffer Preparation Historical Decision Reconstruction

- Snapshot: `sequential-260712`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/sequential-input-buffer-preparation.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### sequential-260712/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Processor contract

Use an explicit constructor-injected Protocol or equivalent interface:

```python
class InputBufferProcessor(Protocol):
    async def process(
        self,
        context: InputBufferPreparationContext,
        buffer: InputBuffer,
    ) -> InputBufferPreparationOutcome: ...
```

The closed processor registry selects by Buffer kind and, for `action_message`, by action discriminator. Registration is explicit application composition, not import-time global plugin registration.

Concrete processors:

- `UserMessageInputBufferProcessor`
- `GoalActionInputBufferProcessor`
- `SkillActionInputBufferProcessor`
- `CreateGitWorktreeActionInputBufferProcessor`
- `GoalContinuationInputBufferProcessor`
- `AgentMessageInputBufferProcessor`

### Explicit source section: Evidence format and CI policy

Implementation PRs must include:

- backend Ruff, Pyright, and Pytest results;
- TypeScript format, lint, typecheck, and build results for affected workspaces;
- generated-client diff validation;
- E2E scenario names and CI job links;
- migration upgrade verification on a representative pre-change database snapshot.

Mandatory deterministic tests may not be skipped. Optional live-provider tests may skip only for a documented missing credential prerequisite; an available credential with a failing test is a CI failure.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
