---
title: "Workspace Environment Opt-In Decisions"
created: 2026-10-15
document_role: primary
document_type: adr
snapshot_id: workspaceenv-261015
tags: [workspace, runtime, security, architecture]
---

# Workspace Environment Opt-In Decisions

References: [workspaceenv-261015/REQ](../requirements/workspaceenv-261015-key-opt-in.md). Decisions are made under the requester's autonomous implementation delegation. An independent read-only technical opinion checked the alternatives and risks; it did not substitute for requester intent or claim complete Design approval.

## D1. Immutable catalog identities and explicit selection relations

REQ-1/REQ-2/REQ-4 require identity-safe opt-in. Store each shared variable with an opaque ID, Workspace owner, unique Workspace/name, and encrypted value. Store selected `(agent_id, variable_id)` pairs, initially absent, with cascading deletion. Same-name value edits retain identity; rename deletes the old identity and inserts a new one. Retention requests carry exact identity and original name. Selection writes reject missing/foreign/duplicate IDs.

Reject name-only mappings: an old browser selecting a deleted then recreated name would delegate new credentials without fresh consent. A mapping with IDs can work but requires application-maintained cross-Agent cleanup instead of FK guarantees. Do not introduce a general secret vault, versions, tombstones or history.

## D2. Serialize shared mutations before Agent selection

REQ-4 requires no dangling/revived opt-in. Catalog replacement locks the Workspace. Selection replacement locks Workspace then Agent, authorizes current Agent management and validates every variable in that Workspace. Database-only transactions complete before command I/O. Whole-list replacement follows existing settings semantics; no versioning contract is added. Stale full-list editors can overwrite concurrent desired-list edits; missing identities fail rather than silently resurrecting data.

## D3. Resolve shared and local configuration in one snapshot

REQ-3 extends the existing Runtime owner read. A single outer-join query reads managed active Agent-local data and selected same-Workspace rows. Resolve Toolkit → selected Workspace → Agent-local. Defaults contribute no shared values. Each source retains existing independent limits; combining sources does not retroactively invalidate existing local configuration. Fail closed on read/decryption/validation failure. No cache, Runner protocol or lifecycle change.

## D4. Reuse bounded role boundaries and UI

REQ-1/REQ-2: Owner/Manager can mutate the common catalog, including removing variables. This deliberately uses the shared settings write-role matrix, not Runtime Profile's Owner-only permanent-deletion rule. Agent selection remains Owner or exact Agent admin, so Manager alone does not grant Agent-management authority. Members see metadata only and private Agents preserve not-found boundaries.

Workspace settings adds Environment variables, reusing the current redacted editor. Agent Runtime settings adds a separate checkbox list with saved/draft state, default-none copy and local-override annotation. A selected key delegates future value updates by Workspace managers; copy makes this consequence explicit. No Session editor or auto-select-all option is introduced.

## Risks

A process whose environment was already resolved may launch with that snapshot; deletion is not retroactive credential revocation. Deselecting or deleting shared configuration may reveal existing Toolkit contributions, and removing a local override may reveal the selected shared value. These are source composition rules, not hidden migration fallback. Migration creates only empty new tables and does not touch Agent/Workspace ORM columns or existing credentials.
