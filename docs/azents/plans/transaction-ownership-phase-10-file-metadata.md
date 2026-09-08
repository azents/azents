---
title: "Transaction Ownership Phase 10: File Metadata"
created: 2026-09-08
tags: [backend, architecture, database, files]
---

# Phase Execution Plan

- Phase: 10, Artifact, ExchangeFile, and ModelFile metadata ownership.
- Branch/base: `refactor/file-metadata-transactions-260908` →
  `refactor/title-repository-transactions-260908`.
- PR boundary: one reviewable file-metadata transaction ownership correction with
  typed operation repositories, deterministic boundary tests, and current Spec
  synchronization.
- Inputs: requester transaction rules and implementation instruction; research
  inventory `transaction-research-model-integrations.md` and its per-context
  entries; [transaction-260908/DESIGN](../design/transaction-260908-repository-ownership.md).
- Deliverables: all 41 service-owned SessionManager lifetimes in Artifact (13),
  ExchangeFile (21), and ModelFile (7) become repository-owned completed database
  operations; S3 and Runtime work stays between completed operations; final writes
  retain current authority revalidation and atomic groups.
- Non-goals: changing file lifecycle policy, provider-output canonical-key
  compensation, public API or schema, migrations, lock/retry/fallback policy, or
  caller-owned input-admission transactions.
- Mechanisms: M1, M2, M3, M4, M5.
- Authorities: `transaction-260908/REQ-1` through `REQ-5`;
  `transaction-260908/ADR-D1` through `ADR-D3`.
- Design delta: None.

| Mechanism | Phase application | Validation |
| --- | --- | --- |
| M1 | Add domain-specific operation repositories that own complete Artifact, ExchangeFile, and ModelFile metadata/auth/read/write transaction lifetimes and compose narrow repositories for atomic groups. | No service-owned SessionManager import or context remains in the three service areas; operation tests prove completed results and rollback. |
| M2 | Keep S3 upload, copy, download, preview, thumbnail, deletion, and Runtime-facing transfer work outside completed database operations. | External collaborator fakes assert that no database transaction is active at each I/O boundary. |
| M3 | Preserve preflight checks and repeat the existing final authority/access predicates within final mutation operations after external work. | Stale Session, Run, root-retention, workspace-access, and identity tests reject finalization without partial metadata. |
| M4 | Update direct callers and tests, preserve caller-owned `claim_input_attachments` composition, synchronize File Exchange and Conversation Specs, and report exact residual boundaries. | Symbol/caller searches, focused and broad affected tests, Ruff, format, full ty, and staged pre-commit. |
| M5 | Preserve existing lock order and avoid any lock spanning S3/Runtime work; introduce no distributed lock, retry, or fallback. | Concurrency tests use deterministic barriers and the exception ledger remains empty. |

## Ownership and Interfaces

The initial implementation covered `services/artifact.py`,
`services/exchange_file/**`, `services/model_file.py`, their lower repositories and
new operation repositories/data/tests, required direct callers, and applicable
Specs. Final corrections, source review, and validation are performed directly by
`/root`; no further delegated implementation or review is used.

Operation repositories accept typed inputs and return detached repository data or
typed domain results only after their transaction context has completed. Atomic
multi-repository authorization plus mutation shares one repository-owned session.
Repositories do not import services and do not accept application callbacks or live
session aliases.

`ExchangeFileService.claim_input_attachments` remains a caller-session operation
because it is intentionally composed atomically with input admission. Any shared
validation it needs remains pure database metadata logic and does not authorize a
new service-owned transaction.

## Removal and Absence Verification

Remove all `SessionManager` and `get_session_manager` dependencies and all
service-owned session contexts from the three owned service areas, except for the
temporary dependency tunnel described below. Replace service operations with
explicit domain operation methods. Verify that S3/Runtime calls occur only after
repository operations return and that final metadata admission revalidates current
authority.

Do not edit `engine/events/provider_output.py` or decide its canonical-key
compensation behavior. That blocked lane currently reaches through
`ModelFileService` and `ExchangeFileService` for a session factory and lower
repositories. The exposed handles therefore remain temporarily for that exact
consumer only; they are an unresolved ownership violation, do not count as a
Phase 10 migration, and are not an approved service boundary or reusable alias.
The Engine builtin authority recheck no longer participates in this tunnel; it
uses a completed ModelFile authority operation without an Engine-owned session.
Do not edit `services/file_lifecycle_cleanup.py` unless a strictly shared pure
metadata interface becomes necessary. Record both residuals rather than hiding
them behind compatibility aliases.

## Integration and Review

Run focused repository and service tests after each domain extraction, then broad
affected tests. Run changed-path Ruff and format checks, full
`uv run ty check --error-on-warning`, and staged pre-commit. The final source
review compares the stable diff against Requirements, ADR, Design, this plan,
current Specs, and tests. Earlier review findings remain inputs, not a substitute
for verifying the final corrections directly. No automatic PR merge, migration,
or public API change is authorized by this phase.

## Context Checkpoint

Starting inventory: 41 service-owned lexical contexts in scope. Residual declared
boundaries are 16 `file_lifecycle_cleanup.py` service contexts, the intentionally
caller-owned ExchangeFile input-admission session, and the provider-output
canonical-key/dependency-tunnel ownership violation. The service-facing session
and lower-repository attributes retained for provider output cannot count as
remediated ownership. Completion evidence must report the exact migrated count,
remaining symbol search results, validation commands, failures or skips, and any
newly discovered boundary without claiming complete service-boundary or
repository-wide migration.

Verified Exchange recovery uses an authority-independent, publication-ID-only
database read after failed final admission. Confirmed metadata absence cleans the
random derived previews while retaining the deterministic product object for
stable retry, preserving the existing publication contract. A database read
failure retains all prepared objects because commit state is genuinely uncertain.
