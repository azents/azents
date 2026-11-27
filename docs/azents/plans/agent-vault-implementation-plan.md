---
title: "Agent Vault Implementation Plan"
created: 2026-11-28
tags: [vault, agent, security]
---

# Agent Vault Implementation Plan

- Snapshot: [Requirements](../requirements/vault-261127-agent-vault.md), [ADR](../adr/vault-261127-agent-vault.md), and [approved Design](../design/vault-261127-agent-vault.md).
- Approved Design revision: `1`; mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`, `M9`, `M10`, `M11`, `M12`.
- Design delta: `None`.
- Primary owner: primary agent, including integration and validation.
- Independent reviewer: `vault-reviewer`, the same read-only reviewer for every integrated phase. Request a review only after the phase diff and validation are stable.

| Stack | Branch and base | Mechanisms and authorities | Review boundary and phase validation |
| --- | --- | --- | --- |
| Agent Vault [1/3]: Store Agent-owned encrypted entries | `feat/agent-vault-storage` → `main` | M1, M2, M11, M12 in part; REQ-1, REQ-5, ADR-D1/D2; Agent deletion | No exposed writers. Schema, Agent deletion catalog, repository and manager permission slice. Verify migrated PostgreSQL and repository tests. |
| Agent Vault [2/3]: Expose settings and confidential Runtime operations | `feat/agent-vault-runtime` → `feat/agent-vault-storage` | M1–M6, M11, M12; REQ-1–REQ-3, REQ-5, ADR-D1–D3/D6–D8 | Manager routes, generated clients and settings UI; current Runner binding, typed transports, tool integration. Verify management/Runtime/Browser E2E and wire-level secret absence. |
| Agent Vault [3/3]: Collect and settle Session requests | `feat/agent-vault-requests` → `feat/agent-vault-runtime` | M7–M12 and M1/M2 batch composition; REQ-1, REQ-4–REQ-5, ADR-D1/D2/D4/D5/D9 | Request schema before writers, history, dialog, exact provider projection, expiry and wake. Verify web and provider E2E, race and authorization gates, integrated spec promotion and plan cleanup. |

Dependencies: one Agent-scoped entry repository is shared by settings, resolved use, and request-batch writes; request-side writes compose an entry operation within the mailbox transaction, not via settings API. Runtime compatibility fails closed. No migrations of existing values, provider retry system, legacy Vault modes, or feature removals.

Use synthetic values, local migrated PostgreSQL, both Coordination Store implementations, a compatible Runner, separated actors, and isolated Discord/Slack fixtures. Live provider smoke is optional, per the approved Test Strategy. Post no real request or secret, and do not merge or deploy without authority. Record exact diff, tests, risks and remaining scope at each checkpoint. Update the owning Spec Wiki pages when schema or verified behavior changes; after full validation set matching implementation dates and remove the temporary phase plans in the final phase.
