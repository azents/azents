---
title: "Agent Vault Phase 2: Settings and Runtime"
created: 2026-11-28
tags: [vault, agent, security, runtime]
---

## Phase Execution Plan

- Phase: `2/3` — Settings and explicit confidential Runtime use.
- Branch/base: `feat/agent-vault-runtime` → `feat/agent-vault-storage`.
- PR boundary: manager settings and execution-scoped CLI, Browser and file registration, with generated API/Control contracts. No request cards or channel links.
- Inputs: [approved design](../design/vault-261127-agent-vault.md), [phase 1](agent-vault-phase-1-storage.md), reviewed storage commit `7c9263acd`.
- Deliverables: metadata-only Agent settings and explicit create/replace/delete; separate confidential Runner context for CLI/file; compatible Browser fill by reference and file registration without readback.
- Non-goals: general environment changes, automatic secret injection, source removal, object store/side-channel transport, or new approval gates.
- Interfaces: authenticated Agent settings API with value-bearing input and redacted responses; `vault_env`, `vault_entry`, `vault_register_file`; exact-generation capability and authenticated public keys with typed, purpose-bound Control operations.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M11`, `M12`.
- Authority references: REQ-1–REQ-3 and REQ-5, ADR-D1–D3 and ADR-D6–D8, current Runtime Control, Session Browser and Agent lifecycle.
- Design delta: `None`.
- Removal obligations: none.
- Absence verification: no value readback, no auto-injection, plaintext transport or shell fallback; unchanged ordinary operations and storage.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Management | Primary agent | Public API, Vault service, generated clients, Agent settings web | Phase 1 storage | Scoped metadata and create/replace/delete | API redaction and auth, browser settings journey |
| Runner transport | Primary agent | Runtime Control protocol and generated types, Runner registration and handlers | Current admission and recipient keys | Typed sealed operations and immutable recipient/generation binding | Cipher and serialization tests, both coordination stores |
| Tool composition | Primary agent | Azents Tool/Runtime admission and file write integration | Phase 1 storage and typed Runner operations | Explicit command, browser and file input | Existing Runtime and Browser tests plus synthetic non-echo consumption |

- Integration order: management boundaries → Runner typed transport and key registration → Tool admission → integrated tests and Spec Wiki.
- Independent review: `vault-reviewer` reviews the stable integrated diff; the primary agent owns corrections and affected test reruns.
- Final validation: scoped Python/TypeScript validation, regenerated contracts, isolated E2E with a compatible Runner, and deterministic serialization, deadline and stale-generation tests.
- Scope-drift check: review new interfaces against approved Design; preserve the existing environment and ordinary Runtime paths.
- Context checkpoint: Phase 1 PR #2647 is open; Phase 2 is based on `7c9263acd`. The settings API, UI, Browser reference, and CLI/file transport implementation are in the working tree. Related application tests (246), Runner regression tests (111), Web tests (855), and focused new Runner and Control tests passed. The required CLI E2E collected but failed during Runner image setup before its assertions: Pixi download timed out under the default Docker build network. A host-network rebuild passed that download but failed extracting an image layer when the Docker daemon disconnected. Full E2E, integrated independent review, and the Phase 2 PR remain outstanding. Do not start Phase 3 before opening that PR.
