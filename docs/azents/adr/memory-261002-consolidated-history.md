---
title: "Agentic Historical Memory and Shared Run Loop Decisions"
created: 2026-10-02
updated: 2026-10-02
tags: [memory, engine, architecture, security]
document_role: primary
document_type: adr
snapshot_id: memory-261002
---

# Agentic Historical Memory and Shared Run Loop Decisions

## Effective Decision Index

This is an append-only decision history. The current complete contract is [Design revision 2](../design/memory-261002-consolidated-history.md). Earlier pending states, unselected recommendations and the later-corrected interviewee assignment are historical, not current authority. Final requester Design approval remains pending.

| Decision ID | Effective choice | Decision ownership |
|---|---|---|
| `memory-261002/ADR-D1` | One generalized execution loop with preserved foreground semantics | Requester |
| `memory-261002/ADR-D2` | Ephemeral internal conversation, separate durable work products | Requester |
| `memory-261002/ADR-D3` | Independent Team/personal units and mutually isolated generation contexts | Requester |
| `memory-261002/ADR-D4` | Separate optional VFS mutation interfaces, private drafts, host-owned validation/publication | Requester |
| `memory-261002/ADR-D5` | Lightweight for both stages, existing quota-only candidate advancement | Requester |
| `memory-261002/ADR-D6` | Whole affected aggregate denial and clean regeneration | Requester |
| `memory-261002/ADR-D7` | Durable drafts/progress, finite passes, per-unit lease and approved operational profile | Requester |
| `memory-261002/ADR-D8` | Whole authored documents, independent 10,000-byte scopes and read-only live lookup | Requester |
| `memory-261002/ADR-D9` | Coordinated data-preserving cutover and explicit rollback | Primary Agent direct technical completion |
| `memory-261002/ADR-D10` | Current-source generation/hash identity and purge-safe manifests | Primary Agent direct technical completion |
| `memory-261002/ADR-D11` | Execution-local observed revisions and atomic mutation receipts | Primary Agent direct technical completion |
| `memory-261002/ADR-D12` | Metadata-only source-work enrollment and exact publication acknowledgements | Primary Agent direct technical completion |
| `memory-261002/ADR-D13` | Availability/grant continuity across restore and rollback | Primary Agent direct technical completion |

The ownership correction near the end of this record governs D9–D12; no subagent approval supplies final Design authority. Primary-Agent technical completion choices are included for the requester's final review, not represented as individually requester-selected options.

- Snapshot: `memory-261002`
- Requirements authority: [memory-261002/REQ](../requirements/memory-261002-consolidated-history.md), accepted as the technical-design basis on 2026-10-02 at 19:52:59 KST.
- Mode: Collaborative. The requester owns unresolved material decisions.
- Current implementation baseline: `f42dc1f262239bf04fdc741125cc37968f5101e6`.
- Supporting exploration: [complete redesign proposal](../notes/consolidated-historical-memory-redesign-2026-10-02.md). Its numerical defaults and unselected mechanisms are proposals, not independent authority.
- No implementation or final primary Design approval is recorded here.

## System framing

Current Historical Memory stores one source-specific summary per eligible root Session and packs whole source blocks into a bounded automatic snapshot. There is no semantic cross-Session consolidation step. Existing Run-start preparation and successful same-Run compaction reconstruction already provide the required refresh opportunities.

The existing execution loop supports injected model preparation, streaming adapter, output normalization and tool execution. The refreshed baseline includes `e5b6ed552`, which moved execution transaction compositions into explicitly injected repository operations. The loop still uses foreground Session/Run identities, Run statuses, input preparation and terminal semantics. Generalization must preserve these newly established atomic groups rather than undoing the repository split or cloning another loop.

The source corpus and foreground consumer already have current Agent/Workspace, Team/associated-User, Memory-enabled and lifecycle authorization. Consolidating content introduces a new stored artifact whose prose can depend on several sources; stored availability and source references cannot be used as a replacement for current authorization.

Job Runtime provides handler dispatch, deadlines and process-local coalescing/capacity, not cross-process exclusive publication or an Agent model/tool loop. Source preparation uses the Lightweight chain and is not itself a tool-capable consolidation runtime.

## Fixed or retained outcomes

- Actual Agent-controlled second-stage integration with optional evidence search/read and iterative draft revision; a one-shot fixed-input operation is excluded by REQ-1.
- Shared execution-loop generalization with foreground behavior preservation, REQ-8.
- Prepared detailed source summaries and their independently authorized lookup remain, REQ-2/REQ-7.
- Root Run preparation and successful compaction within the continuing Run are independent refresh boundaries, REQ-5.
- Ordinary model/tool iterations do not silently refresh historical content; current access loss still applies before new use.
- One Memory capability, current privacy boundaries, independent Saved semantics and best-effort source freshness remain, REQ-3/REQ-4/REQ-6/REQ-7.
- Model generation and external I/O occur outside database transaction scopes. Existing foreground atomic admission/finalization boundaries remain intact.
- Implemented prior Requirements/ADR/Design snapshots are immutable. In particular, the former no-model-integration decisions are historical, not rewritten to pretend they included the new behavior.

## Complete material-decision map

| ID | Decision | State | Owner |
|---|---|---|---|
| ADR-D1 | Generalize the existing loop rather than build a separate memory-only loop | Accepted requester direction | Requester |
| ADR-D2 | Ephemeral internal execution history, distinct from durable memory work products | Accepted direction | Requester |
| ADR-D3 | Consolidation unit ownership: separate Team/User versus combined per-consumer views | Accepted: separate units | Requester |
| ADR-D4 | Internal tool/workspace and validated publication contract | Current proposal | Requester |
| ADR-D5 | Tool-capable consolidation model route and quota/failure policy | Pending | Requester |
| ADR-D6 | Source removal and invalidation granularity | Pending | Requester |
| ADR-D7 | Durable progress, source coverage, job ownership/recovery and bounded resource policy | Pending | Requester |
| ADR-D8 | Aggregate presentation, foreground byte allocation and authorized aggregate lookup | Pending | Requester |
| ADR-D9 | Existing source/snapshot migration, coordinated cutover and rollback | Pending | Requester |

The exact shared-core interface layout, class/function names, test helper names, stable IDs and equivalent source file organization are implementation-owned details within accepted behavioral boundaries. They are not additional requester choices. A materially different execution authority, atomicity, recovery contract or public interface must return to this decision map.

## memory-261002/ADR-D1 — Accepted: generalize the existing Run loop

- **Acceptance:** requester explicitly directed inclusion at 2026-10-02 19:47:11 KST; reaffirmed as the technical-design basis at 19:52:59 KST.
- **Authority:** REQ-1 and REQ-8.
- **Choice:** extract/generalize one existing model/tool iteration core for foreground conversation and internal consolidation. Both consumers must use it. Provide purpose-specific input/state admission, lifecycle/ownership, reporting and terminal behavior around that common core.
- **Preserve:** provider transports/auth, response normalization, tool-call matching/cancellation, foreground streaming, mailbox/TurnAction behavior, user interruption, compaction, existing repository-owned atomic groups and canonical terminal delivery.
- **Exclude:** a second copied inference/tool loop, fake foreground Session records for internal execution, bypassed ownership checks, broad runtime mode flags that scatter purpose branches through the loop, or reversal of the recent transaction-ownership work.
- **Alternative not selected:** an independent memory-specific coordinator sharing only SDK helpers. It reduces initial foreground coupling but leaves two loops whose cancellation, provider behavior and tool-result semantics can diverge.
- **Trade-off:** the common-core refactor touches critical foreground control flow and needs parity evidence before the consolidation consumer is attached.
- **Delivery constraint:** first run ordinary conversation through the generalized implementation with unchanged behavior; then add the internal consolidation consumer. Do not keep an obsolete independent production foreground loop indefinitely.
- **Still undecided here:** exact storage of memory work products, model routing, tool APIs, resource constants and scope layout. Those choices are not implied by sharing a loop.

## memory-261002/ADR-D2 — Accepted direction: ephemeral internal conversation

- **Acceptance:** following a question about Codex/internal Session persistence and an explicit explanation of RAM-only conversation plus separately durable work products, the requester approved that basis at 2026-10-02 19:52:59 KST.
- **Authority:** REQ-6/REQ-7/REQ-8 and the accepted follow-up direction.
- **Choice:** the internal Agent's model messages and tool-call/result conversation live in process memory. It does not create a persisted user-visible Session/Run/transcript or a second private saved conversation corpus merely to operate the generalized loop.
- **Separate lifetimes:** source summaries and successfully published memory are durable domain data. Job ownership/retry, validated draft and source-coverage progress may also be durable work products; their exact minimal contract belongs to ADR-D7, not to transcript persistence.
- **Recovery meaning:** after process loss, a new ephemeral execution rehydrates task/scope from current authority and permitted domain progress and reads needed evidence again. It does not restore an identical old conversation, hidden reasoning or provider response handle.
- **Trade-off:** some model work and source reads can repeat after a crash. Operational metadata can record usage/status without recording personal prompt/result bodies.
- **Alternative not selected:** persisting the entire tool/model conversation for exact continuation. It adds privacy, retention and stale-evidence-replay obligations not needed for the stated background integration outcome.
- **Reference evidence:** at Codex `14a477ea89712071944244022e8a10142845456e`, `memories/write/src/phase2.rs` sets `ephemeral = true`; `runtime.rs` starts/shuts down an internal consolidation thread; `core/src/session/session.rs` skips thread persistence and session state-DB setup in the ephemeral path. Generated artifacts and global job bookkeeping are separate. This reference does not imply atomic file publication, no operational logging, or an Azents-specific database-draft implementation.
- **Security invariant:** process-local conversation is still sensitive. Recheck consumed-source authorization before each subsequent model call. On revocation, abandon contaminated working state instead of merely removing a visible source link.

## memory-261002/ADR-D3 — Initial proposal: consolidation ownership unit

### Question

Should shared Team history and personal history have independently maintained aggregates, or should each personal consumer have a combined Team-plus-personal aggregate?

### Option A — Separate Team and personal units (recommended)

- Team key: Agent/Workspace shared scope.
- Personal key: Agent/Workspace/durable associated User.
- Team consumers receive only Team output; personal consumers compose permitted Team output and their own personal output at a foreground boundary.
- A Team update does not require rebuilding every personal aggregate. A personal source never enters a Team model input.
- Scope labels remain visible. Cross-scope discrepancies are not silently resolved by a third model call.
- Trade-off: shared and private context is not semantically reconciled into one personalized narrative; foreground rendering must fairly budget both units.

### Option B — Combined per-consumer aggregate

- Keep a Team-only aggregate for Team consumers; generate each User aggregate from that User's permitted Team plus personal source summaries.
- A model can integrate relationships between shared and personal history directly.
- Team changes fan out to every relevant personal aggregate; shared work is repeatedly integrated, and source removal invalidates more combined outputs.
- Input capture/publication must reauthorize the combined manifest for the consumer. Simply feeding a globally shared prebuilt result into every personal aggregate is not an alternative to dependency tracking.

### Recommendation and evidence

Recommend A. Existing `HistoricalMemoryRepository.list_available_snapshot_candidates_in_session` already models Team access plus optional associated-User sources, while privacy is tied to root Session authority. Separate model-input corpora preserve that boundary without relying on generated-output redaction. Exact table keys and byte allocation are downstream mechanisms, not part of this decision's acceptance until the choice is made.

**Initial proposal state:** neither option was accepted when this comparison was presented. The subsequent acceptance is recorded below.

### ADR-D3 acceptance — 2026-10-02 at 19:59:49 KST

- **Owner:** requester.
- **Authority:** REQ-2/REQ-3/REQ-5/REQ-7 and the explicit selection following the A/B briefing.
- **Choice:** Option A, independently maintained Team and personal consolidation units.
- **Scope keys:** shared Agent/Workspace Team scope and Agent/Workspace/associated-User personal scope. Equivalent table layout and identifiers remain implementation details.
- **Consumer behavior:** Team roots use only the Team aggregate. Personal roots may compose the currently permitted Team aggregate and their own personal aggregate; they never use another User's aggregate. Children inherit root context.
- **Preserved authority:** generation and use both reauthorize current scope; generation never mixes personal evidence into Team output.
- **Benefit:** Team changes do not require regenerating every User aggregate, and private content is excluded from shared model input rather than redacted afterward.
- **Accepted trade-off:** no extra cross-scope model call reconciles both aggregates into one personalized narrative. Keep scope labels visible; entry selection and budget allocation remain ADR-D8.
- **Rejected alternative:** Option B, combined per-consumer Team-plus-personal aggregates, because of duplicated shared processing and wider update/invalidation fan-out.
- **Not selected by this decision:** exact model route, tool/edit interface, output shape, byte split, source-removal granularity or persistence/retry limits.

## Pending lanes — complete briefing, not accepted decisions

### ADR-D4: internal tools and publication

Compare a server-owned typed draft/tool workspace with a constrained file-like workspace. Either must support real Agent-controlled inspection/edit/repair, identity-based authority and explicit validated submission. The recommendation is server-owned drafts with scoped tools and atomic database publication; the model is not given shell, raw SQL, public channel or Saved mutation privileges. Final tool surface and draft-edit semantics are pending.

### ADR-D5: model route

The complete proposal recommends Stage 1 Lightweight and Stage 2 Main with verified tool support, background quota attribution and no silent cross-chain fallback. Using a tool-capable Lightweight chain or a distinct selector remains a material alternative with quality/cost/configuration consequences. Main routing is not accepted simply because the foreground loop is reused.

### ADR-D6: invalidation

The proposal recommends conservative aggregate-wide suppression and a clean rebuild when a consumed source is revoked, versus finer-grained item/claim dependency handling. Current source denial is fixed; how much unaffected context becomes temporarily unavailable is a real decision, not an implementation detail. A pointer-only deletion is not a viable privacy guarantee.

### ADR-D7: work persistence and recovery

Choose the minimal domain draft/coverage/checkpoint contract independently of ephemeral conversation. Bound work, source coverage, job ownership and retry so no foreground Run waits for model generation. The proposal includes bounded paginated passes, durable per-unit lease/CAS and coalesced scheduling; process-local runtime behavior alone is not cross-process publication fencing. Durable processed-source lists, draft retention, numerical caps and rollback/retry semantics require acceptance or delegated engineering authority.

### ADR-D8: aggregate read contract

Choose the compact output structure, total Historical budget, Team/personal allocation and live read shape. Existing source summary inventory and Saved mutation are retained. The proposal recommends a 10,000-byte total view and canonical aggregate routes; its 4,000/6,000 split, entry caps and new aggregate VFS filenames are not yet accepted.

### ADR-D9: cutover

Choose source backfill and automatic snapshot migration, old/new writer handover, temporary missing-aggregate behavior and explicit rollback. The recommendation preserves all source/Saved records and performs a coordinated schema/snapshot cutover without a hidden whole-source packing fallback. Mixed-version safety and acceptable transition effects require validation and approval, not assumptions.

## Design readiness

Requirements are recorded; ADR-D1 through ADR-D3 are accepted and six decision lanes remain unresolved. ADR-D4 is the current question. A primary Design can be finalized only after a coherent set of decisions exists and every material mechanism has authority. Current supporting proposal content remains available as the full candidate design, not as a substitute for these decisions.

No code changes, deployment actions or live data writes are part of this ADR creation.

## memory-261002/ADR-D4 — Current proposal: Agent editing surface and publication

### Context and fixed boundaries

The shared loop and ephemeral model/tool conversation are already selected. The next question is the Agent's work product, not whether the Agent has tools: what it edits and how an edited result becomes published memory.

Both alternatives keep draft changes private, use only permitted summaries, forbid Saved/source mutation, and validate current authority before atomic result publication. Neither requires arbitrary Runtime or shell access. Plain final assistant text is not a valid submission. Existing public Memory VFS is a read-only source/lookup surface and must not become a general mutable memory mount.

### Option A — Structured private draft through domain tools (recommended)

- The Agent lists/searches/reads permitted source summaries and reads/edits sections and retrieval routes through scoped draft tools.
- Draft entries and source references are structured; server-owned identifiers and version checks protect edits. The model may choose what to investigate and revise repeatedly.
- Validation errors identify invalid references, malformed entries, conflicting draft revisions or size problems and return as tool feedback.
- Explicit submission of an exact draft revision triggers final validation and atomic publication. Rendering into compact Markdown happens after structural validation.
- Source dependencies are tracked by the service from inspected/inherited inputs, independently of visible route selection.
- Benefit: no extra writable filesystem contract, reliable reference validation, and private draft/publication separation align with existing database authority.
- Cost: a small dedicated draft-tool schema is new, and the model edits structured semantic units rather than arbitrary Markdown.

### Option B — Restricted Markdown draft workspace with file-like tools

- The Agent reads/searches permitted summary files and edits a private Markdown draft using scoped file-like read/edit operations.
- The workspace may be virtual and server-backed; this option does not require a full Runtime or unrestricted shell.
- Submission parses the draft and validates section format, canonical references, size, permission and current ownership before atomic publication.
- Benefit: editing mechanics more closely resemble Codex's document workspace and permit flexible Markdown rearrangement.
- Cost: an isolated writable workspace contract, parser and draft persistence boundary are needed; arbitrary prose/link edits must be reconciled with canonical source references and deterministic foreground rendering.

### Recommendation and approval boundary

Recommend A for the multi-user server implementation. It retains genuine Agent-controlled lookup/edit/repair while keeping authoritative identities and publication in domain operations. This is not the withdrawn fixed-input single-model-response design.

The choice covers editing representation and explicit submission, not exact tool names, recovery retention, job lease parameters or model selection. Those remain local details or their separately listed ADR lanes. **Awaiting requester choice.**

### D4 decision hold — 2026-10-02 at 20:54:39 KST

The requester withdrew the tentative Option A acknowledgement of 20:54:00 KST and asked to hear the actual Codex implementation before deciding. D4 remains unresolved; no Option A acceptance is in force. Do not advance to model routing as though the editing decision were closed.

Reference clarification at Codex `14a477ea89712071944244022e8a10142845456e`:

- The V2 consolidation prompt asks an ephemeral internal Agent to read the workspace diff, inspect the existing Markdown aggregate and source-summary files as needed, and create/update `memory_summary.md`.
- The Agent edits the document itself, rather than invoking semantic draft-section CRUD and a dedicated `submit_draft` protocol.
- The outer worker waits for Agent completion, shuts it down, validates artifacts and current lease ownership, resets the workspace baseline and records job success.
- The V2 artifact validator checks the format marker, required headings, size and filesystem/symlink constraints. This is not exhaustive semantic truth/source-link verification.
- The prompt read path independently reads `memory_summary.md`; the observed code does not establish the separately staged, atomic database publication boundary described in either Azents draft alternative.
- Consequently Option B is closer in editing representation, but its server-owned isolated staging/submission remains an Azents proposal, not an exact description of Codex.

The next user-facing step is factual explanation, then a fresh D4 choice. Accepted D1–D3 remain unchanged.

### D4 follow-up — optional VFS mutation research, 2026-10-02

At 21:05:41 KST the requester proposed permitting writes on VFS backends that support them. At 21:08:43 KST the requester asked for research into the additional concrete VFS design needed. This establishes the direction to investigate, not acceptance of every mutation, transaction or publication contract below. The earlier structured-domain-tool recommendation is superseded by this candidate; D4 remains open.

Requirements impact: REQ-1, REQ-3, REQ-6, REQ-7 and REQ-8 already authorize constrained draft editing, isolation and validated completion without Runtime startup. No new product outcome is required for an internal draft backend. Do not insert implementation interfaces into Requirements or infer that all foreground users gain writable Memory, Skills or arbitrary VFS mounts.

#### Repository evidence

Inspected at `f42dc1f262239bf04fdc741125cc37968f5101e6`; the inspected core VFS, VFS read/Memory services and engine tool directory have no diff against fetched `origin/main` at `dfd441aef8b84cc22135d0e772a2c1edcc8d0ceb`.

- The implemented [VFS Design](../design/azents-260719-azents-vfs.md) explicitly excluded writes and used immutable Run projections for Skills. Preserve this historical record and those immutable projections.
- The current [Memory Spec](../spec/domain/memory.md) and `services/memory_vfs.py` already supply a live database-backed mount. VFS is therefore not inherently an immutable filesystem; immutability belongs to the backend contract.
- `services/vfs_read.py` declares `read_text`, `grep`, `glob` and `transfer_read` capabilities. Its router validates ownership before supported backend I/O; the context and owner validator still require foreground Session/Run identity.
- `engine/tools/readable_storage.py` already routes canonical VFS reads without starting Runtime. `engine/tools/builtin.py` still constructs mutation tools under the Runtime provider. Moving routing alone does not make those tools available to an internal job.
- `engine/tools/write.py` checks existence before `put`; this composition is not a backend atomic create-only operation. `edit.py` delegates exact replacement to a native Runner operation; replacing it with generic read-then-write would lose that atomic operation boundary.
- `engine/tools/apply_patch.py` requires a Runtime base path and warns about partial commit failure. Its parser, transport variants and guidance cannot be reused unchanged as a promise of database batch atomicity.
- `services/vfs_read_test.py` covers unsupported operations, ownership-before-dispatch, bounded reads/search and content-free metrics. `engine/tools/readable_storage_test.py` covers VFS without Runtime and rejected relative paths. `services/memory_vfs_test.py` covers authorized discovery and non-enumerating denial. None establishes the new mutation contract.

#### Options

1. **Extend shared VFS contracts and add a job-private draft backend — recommended.** Reuse canonical routing and file-tool names, while preserving read-only Memory/Skills. Add only explicitly supported mutation operations and separate execution grants. This introduces reusable storage contracts without exposing Runtime or publication as arbitrary file mutation.
2. **Memory-only file-shaped tools outside shared VFS.** A smaller immediate abstraction change, but duplicates routing, mutation errors and access policy; later writable backends would need another integration. This remains viable but does not deliver the proposed common backend capability model.
3. **Runtime filesystem sandbox.** Familiar file tooling, but adds process/filesystem lifecycle and extraction boundaries. Starting Runtime solely for consolidation conflicts with the current Non-Goals and is not a viable choice without a Requirements change.

A separate draft backend and a common VFS extension are complementary, not competing options.

#### Proposed minimum contract

These are reviewable material semantics, not accepted implementation authority:

1. **Capability versus permission.** A backend declares supported operations independently: text write, exact edit, file delete and atomic batch patch. A server-created execution grant bounds mount, namespace, ownership unit and operations. Both checks must pass. A writable backend never grants every Agent write access. Read-only backends implement no mutation protocol; unsupported operations fail explicitly.
2. **Execution identity.** Preserve foreground Session owner fencing and add an explicit internal-job principal bound to Agent/Workspace, Team or associated User, job identity and current ownership epoch. Do not fabricate Run/Session IDs or turn the existing context into a set of unchecked nullable identifiers. Router admission is necessary but insufficient: the database backend rechecks current ownership and scope within each mutation transaction.
3. **Closed namespace.** The first writable backend stores only private consolidation drafts, not published aggregates. Its URI is a locator, never authorization. Consolidation may read its authorized prepared summaries and prior aggregate and edit its own draft; it cannot read original transcripts/tool results or Saved Memory through the broader existing Memory mount. Skills, source records, other jobs/units and published Memory remain read-only or unavailable. No shell, transfer or Runtime fallback is granted.
4. **Canonical dispatch.** Reuse exact canonical `azents://` parsing and reject ambiguous/traversing forms, unsupported schemes and unsupported operations before any storage mutation. Absolute Runtime paths continue through their separate capability-gated adapter. Dispatch VFS before Runtime resolution and register each shared tool name once. Tool registration, schemas and model guidance reflect the actually supported execution surface.
5. **Single-file semantics.** Write defaults to atomic create-if-absent; replacement requires explicit overwrite intent. Exact edit performs matching and replacement in one backend transaction, retains single-match/replace-all semantics and rejects an empty search string. Delete is exact-file only, not recursive namespace deletion. Mutations produce a new revision and never silently retry against newer bytes. Existing-file mutations require an observed revision; an execution-local read ledger can supply it without new model parameters, but missing/stale evidence yields a conflict and requires reread. Delete/recreate must not reuse the old revision.
6. **Patch boundary.** Atomic patch is a separate optional backend capability, not a loop over single-file operations. For a supported draft backend, resolve every target inside one backend and draft transaction domain, validate all operations and revisions, then commit all or none. Reject mixed Runtime/VFS, cross-mount and cross-draft patches before writing anything. Do not promise distributed transactions across arbitrary backends. Backends without this capability reject patch; Runtime keeps its existing separately documented failure semantics.
7. **Draft versus publication.** File mutations only revise staging content. Domain validation checks format, byte bounds, exact source identities, tracked dependencies, current authorization and ownership. Successful submission must freeze an exact revision, revalidate, and atomically publish content, dependency manifest and source-coverage state. VFS itself does not infer publication from a filename, file deletion or final assistant prose. A validation/submission operation may remain domain-specific without recreating semantic section-edit tools.
8. **Dependencies and failure.** Track sources from supplied/read evidence and inherited aggregate dependencies, not only model-written links. Any authorization loss affecting working state invalidates that state before another model call. Failed validation allows repair but leaves the prior published version intact. Cancellation, ownership loss and uncertain commit outcomes must never be reported as publication success; inspect authoritative state before retrying. No implicit fallback writes to Runtime.

Exact protocol/type names, mount spelling, helper extraction and equivalent local layout are agent-owned. Publication trigger (explicit submit versus a host-owned validated completion step), draft retention, ownership/retry policy and numerical limits remain visible choices: publication belongs to D4; retention and recovery parameters remain D7. Aggregate invalidation and rendering remain D6/D8.

#### Verification and feasibility

Assessment: **conditionally feasible**, not implemented or runtime-proven. Current routing is reusable; backend mutation protocols, job authority, tool registration, revision propagation and publication transactions are missing.

- E2E primary: a deterministic internal model fixture reads authorized summaries, creates/edits its draft without Runtime, receives validation feedback, repairs and submits; foreground context changes only after successful publication at an eligible refresh boundary.
- Negative integration matrix: disabled/read-only backend; stale job owner; wrong Agent/Workspace/User/job; read of raw source or Saved content; unauthorized path; Memory disabled; revoked source between read/model/write/publish; malformed URI; mixed-backend patch. Assert zero unauthorized backend mutation and zero Runtime startup.
- Deterministic concurrency matrix: two create-only calls, competing replacements, edit conflict, delete/recreate ABA, lease takeover during commit, cancellation around publication and result loss after commit. Assert revision fencing, truthful outcomes and unchanged prior publication on failed admission/validation.
- Patch matrix: add/update/delete in one draft, applicability failure, stale revision and transaction failure leave all files unchanged; cross-domain requests are rejected before the first write.
- Regression matrix: immutable Skills projection and import rules; live read-only Memory authorization; Runtime file tools and patch wire variants; foreground tool registration without duplicate names; read/search byte limits and content-free operational logs.
- Inspect and extend the listed tests; existing tests were read during this research, not rerun as evidence of functionality that does not exist yet.

#### Current decision question

Proceed with a common opt-in VFS mutation contract and a private database draft backend, retaining the existing file-tool interaction while keeping publication a validated domain operation? Recommend yes, with same-draft atomic mutations and no cross-backend transaction promise. Record requester acceptance before promoting this candidate into the primary Design. D1–D3 stay accepted; D5–D9 remain pending.

### D4 direction acceptance — 2026-10-02 at 21:23:00 KST

- **Owner:** requester.
- **Authority:** REQ-1/REQ-3/REQ-6/REQ-7/REQ-8 and explicit approval of the VFS follow-up briefing.
- **Accepted direction:** common opt-in VFS mutation support, a job-private database draft backend, ordinary file-tool editing, and validated atomic publication separate from draft mutation.
- **Accepted mutation boundaries:** backend support is distinct from per-execution permission; existing-file writes are revision-conflict checked; supported multi-file patches are atomic within one draft and reject cross-backend transactions; tool dispatch does not require or fall back to Runtime for VFS operations.
- **Explicit interface constraint:** write-capable backends implement a separate mutation interface. The existing read interface must not acquire required write/edit/delete/patch members. Read-only implementations remain complete without mutation stubs, default throwing methods, `NotImplementedError`, or an inherited abstract mutation obligation.
- **Unsupported operations:** the routing/capability layer rejects the request before backend mutation dispatch. Declared support must agree with an implemented operation interface; a capability flag backed by a placeholder method is invalid. Optional atomic patch support must likewise not force single-file mutation backends to supply a throwing patch implementation.
- **Scope preservation:** source summaries and published Memory stay read-only to consolidation; Saved Memory, original transcripts, Skills and other jobs' drafts remain inaccessible. Foreground access is not broadened.
- **Verification obligation:** a minimal read-only test backend must instantiate/register and serve reads without any mutation members. Mutation requests to it fail at routing with no backend invocation. Type/registration checks reject inconsistent support declarations. A single-file mutation backend without atomic patch support must remain valid without a patch stub.
- **Not blanket-approved:** every detailed mechanism in the research appendix. Exact revision propagation, operation schema and recovery design still need authority/feasibility review. Explicit submission versus host-owned validated completion remains the unresolved D4 publication-trigger choice; retention/retry belongs to D7.
- **Implementation status:** documentation only; no primary Design approval or implementation authorization.

### Current decision map after D4 direction acceptance

- D1 shared loop, D2 ephemeral internal conversation, D3 separate Team/personal units: accepted and unchanged.
- D4 VFS editing/publication architecture and separate optional mutation interface: accepted direction; publication trigger remains current.
- D5 model route, D6 invalidation, D7 recovery/resource policy, D8 aggregate presentation, D9 cutover: pending.

### D4 remaining question — publication trigger

Both choices require an exact frozen draft revision, current authorization/ownership checks and atomic domain publication; final prose alone is never success.

- **Explicit submission — recommended:** the Agent invokes a domain submission operation after file edits. Validation errors return into the same ephemeral loop for repair; successful publication produces an unambiguous completion result. This adds one domain operation but does not add semantic section-edit tools.
- **Host-owned finalization:** Agent completion asks the host to validate/freeze/publish the draft. This keeps publication out of the tool surface, but validation failure requires an explicit re-entry/repair lifecycle or a failed attempt; ordinary final text still cannot bypass validation.

The requester has not selected the trigger. Recommendation is not acceptance.

### D4 Codex completion evidence and snapshot discussion rule

For this design snapshot only, present the actual Codex behavior and source evidence before each remaining material choice. Separate observed behavior from Azents proposals and explain differences in authority, storage and lifecycle. Codex is a comparison baseline, not acceptance authority. This discussion rule does not apply automatically to other designs.

The brief acknowledgement of explicit submission at 2026-10-02 21:36:32 KST was withdrawn at 21:36:53 KST before any acceptance entry was written. The publication trigger remains unselected.

Rechecked the previously inspected Codex source snapshot `14a477ea89712071944244022e8a10142845456e`, not claimed as the latest upstream revision:

- `codex-rs/memories/write/templates/memories/consolidation_v2.md` asks the Agent to create/update `memory_summary.md`; this workflow does not require a dedicated memory-publication submission tool.
- `codex-rs/memories/write/src/phase2.rs`, `agent::handle`, waits for terminal Agent status, checks `AgentStatus::Completed`, and shuts down the Agent before validating artifacts. This is the host-owned completion alternative.
- `workspace.rs`, `validate_consolidation_artifacts_for_version` and `is_valid_v2_summary`, check symlinks, the summary marker, required headings and the UTF-8 byte bound. These are structural checks, not exhaustive semantic/source-authorization proof.
- On invalid artifacts, the host records `failed_invalid_artifacts` through `job::failed`, which supplies the configured retry delay. This completion path does not feed validation errors back into the same Agent execution for repair.
- For valid artifacts, the host reconfirms lease ownership, resets the workspace baseline, then records job success and source-selection progress. Agent completion alone does not make the job successful.
- This sequence does not establish a separate atomic database publication boundary for file contents. Azents must retain its accepted isolated draft and validated publication boundary even if it chooses the same host-owned trigger.

The prior explicit-submission recommendation was based on same-execution repair ergonomics, not on Codex equivalence. Host-owned finalization is a viable alternative; selecting it would still require an explicit invalid-artifact recovery policy. No new selection is recorded by this evidence update.

### D4 completion acceptance — 2026-10-02 at 21:42:31 KST

- **Owner:** requester, after the Codex completion comparison.
- **Choice:** host-owned finalization (Option B). The Agent edits its private VFS draft and finishes without a dedicated publication-submission tool. The host terminates/quiesces the internal execution, freezes the exact draft revision, validates current ownership, authorization, dependencies and artifact constraints, then atomically publishes the permitted result.
- **Completion rule:** a normal Agent terminal outcome is necessary but insufficient. Final prose is not the payload or evidence of successful publication; only successful host validation and publication complete the job.
- **Failure rule:** invalid artifacts fail the attempt without replacing the previous published result. Host validation errors do not re-enter the same Agent execution as submission-tool feedback. Cancellation and ownership loss cannot trigger successful publication. Retry timing, draft retention and restart policy remain D7.
- **Retained boundaries:** optional separate mutation interfaces, read-only backend completeness, job-private drafts, revision-conflict handling and same-draft patch atomicity remain as accepted above.
- **Rejected alternative:** explicit submission, despite its same-execution repair advantage. The chosen trigger follows the inspected Codex host lifecycle while retaining Azents' stronger isolated-draft/atomic-publication boundary.
- **Authority interpretation:** REQ-1's ability to use validation feedback does not require a submission tool or same-execution host-validation retry. Any pre-completion validation support or feedback retained for later attempts must be specified separately; none is silently introduced here. REQ-8's validated completion rule is host-owned.
- **Current decision map:** D1–D4 accepted; D5 model route is current; D6 invalidation, D7 recovery/resource policy, D8 presentation and D9 cutover remain pending.
- **Status:** design decision only. Final primary Design approval and implementation authorization remain pending.

### D5 model-route briefing — Codex comparison before selection

At the same inspected Codex revision `14a477ea89712071944244022e8a10142845456e`:

- `memories/write/src/phase1.rs::build_request_context` uses `memories.extract_model` when configured, otherwise the provider's extraction preference.
- `memories/write/src/phase2.rs` explicitly sets the internal Agent model from `memories.consolidation_model`, otherwise the provider's consolidation preference. It does not simply preserve the foreground conversation model.
- `model-provider/src/provider.rs` defines distinct default IDs (`gpt-5.6-luna` for extraction and `gpt-5.6-terra` for consolidation); providers may override the preferences. These are observed source constants, not claims about current public model availability or measured quality.
- `memories/write/src/lib.rs` selects Low reasoning for extraction and Medium for consolidation at this revision.
- `memories/write/src/startup_tests.rs::memories_startup_phase2_explicit_model_override_drives_request_model` asserts the requested consolidation model reaches the model request. The test was inspected, not executed in this research.

Azents currently prepares individual source summaries with its Agent Lightweight candidate chain (`services/historical_memory/preparation.py`, `repos/historical_memory/preparation.py`, and the Memory Spec). Consolidation is new; sharing the Run loop does not itself authorize a model route.

The immediate question is the Stage 2 model selector:

- **A — Reuse the Agent Main chain (prior proposal; recommended for minimum configuration scope).** Keep Stage 1 on Lightweight and use the Agent's existing Main choice for the tool-capable consolidation loop. This avoids another model selector, but background cost and behavior change with the Main selection. Tool capability must be verified; the Main label alone is not evidence of support. This deliberately differs from Codex's independent consolidation selector.
- **B — Add a separate consolidation selector (closest to Codex).** Permit independent consolidation quality/cost configuration and keep foreground model changes from automatically changing the consolidation selection. This adds persisted configuration, defaulting and configuration-surface work that must be explicitly scoped; no new Memory enable/disable toggle is implied.
- **C — Reuse Lightweight for both stages.** Avoid another selector and use the existing lightweight selection, but its name does not guarantee lower cost or sufficient multi-step tool behavior. Every selected candidate still needs verified tool support; a one-shot fallback would violate REQ-1.

Only the model-route choice is asked here. Background usage attribution, same-chain candidate progression and quota/provider failure semantics remain visible D5 follow-ups; precise resource and retry limits remain D7. No route is accepted by this briefing.

### D5 model-route acceptance — 2026-10-02 at 21:47:33 KST

- **Owner:** requester.
- **Choice:** Option C. Both source-summary preparation and agentic consolidation use the Agent's existing Lightweight candidate chain.
- **Rationale:** maintain a consistent model-selection policy for background Memory work instead of adding a special Main route or a dedicated consolidation selector.
- **Scope:** Stage 1 retains its current Lightweight selection. Stage 2 resolves through that same configured chain and still performs the accepted multi-step model/tool loop. Reusing a selector does not collapse the two stages into one operation or require concurrent jobs to use the same candidate regardless of current chain state.
- **Excluded alternatives:** Main-chain consolidation and a separately configured consolidation model. Tool incompatibility does not authorize an implicit Main fallback, a new selector or one-shot replacement of agentic consolidation.
- **Feasibility obligation:** verify that selected candidates can execute the closed consolidation tool surface. Exact admission/failure and same-chain progression behavior remain the D5 failure-policy follow-up; do not invent a silent skip or cross-chain recovery rule.
- **Codex comparison:** the inspected Codex revision selects extraction and consolidation independently. The requester deliberately selected Azents' existing Lightweight convention instead; Codex comparison informs the decision but does not override it.
- **Authority boundary:** this selection does not adopt Codex's Low/Medium reasoning constants, define a new usage/billing contract, or settle retry/resource limits.
- **Current map:** D1–D4 accepted; D5 model route accepted, usage/quota/failure policy still pending; D6–D9 pending. Final Design approval and implementation authorization remain pending.

### D5 remaining policy briefing — usage and candidate failure

This is a proposal following the accepted Lightweight route, not a new acceptance.

#### Codex evidence

At the already inspected `14a477ea89712071944244022e8a10142845456e`, `memories/write/src/phase2.rs::agent::handle` reads total token usage from the internal thread when its terminal status is `Completed`, before artifact validation, and emits the dedicated phase-two token metrics. Those metrics do not by themselves prove successful artifact publication and are not a multi-user billing ledger.

The same host records Agent/artifact failures and uses `job::failed` with `stage_two::JOB_RETRY_DELAY_SECONDS` (3,600 seconds at this revision). No ordered alternative-model chain is implemented in this inspected phase-two host. This is a bounded statement about the Memory host; it does not claim that the underlying provider transport performs no retries.

#### Existing Azents evidence

- `services/historical_memory/preparation.py::prepare_agent` distinguishes `QUOTA_OR_BILLING` from other provider failures. The former calls `advance_after_quota`; ordinary provider, stream-timeout and output errors record retryable work failure.
- `repos/historical_memory/preparation.py::advance_after_quota` checks the failing provider/integration/model against the active candidate, records shared quota health under Workspace/provider-integration/model identity, and selects the next candidate within the persisted operation chain. Exhaustion records `candidate_chain_exhausted`.
- Repository failure persistence applies bounded exponential retry; the current source-preparation delay ranges from one minute to six hours. These numbers describe Stage 1, not an accepted Stage 2 scheduling policy.
- `_log_historical_memory_usage` records a content-free `historical_memory` call kind, provider/integration/model, source Session identity, usage presence and available token/cost quantities. Consolidation covers multiple sources and has no foreground Session, so attaching it to an arbitrary source Session would be misleading.
- The current execution-loop Spec treats unavailable usage/cost evidence as unknown rather than fabricated zero. Reusing established provider/cost semantics does not authorize a new billing product, cost UI or fabricated Session/Run.

#### Proposed policy and alternatives

**Recommended: preserve existing Lightweight candidate-failure semantics.** Reuse shared quota-health handling and progress to another configured Lightweight candidate only for recognized quota/billing exhaustion. Persist ordinary provider/timeouts as failed work for later retry rather than treating every error as permission to change model. Chain exhaustion leaves the existing authorized published aggregate intact and does not invoke Main. An unsupported tool surface is a configuration/capability failure, not quota; fail the affected attempt explicitly without silent candidate skipping or one-shot degradation. Exact worker retry/checkpoint mechanics remain D7.

**Alternative: pin the selected candidate for the attempt and defer on every terminal provider failure, including quota.** This is closer to the inspected Codex Memory host's model-selection shape, but would leave otherwise usable configured Lightweight candidates idle and introduce a Memory-specific exception to Azents' current candidate-health policy.

Usage should remain operational attribution: distinguish Stage 2 from source preparation and identify the owning Agent/Workspace and internal job, together with the actual provider/model and available usage evidence. Reuse existing estimator/provenance rules; do not invent missing usage or charge an arbitrary source Session. Exact event/type names are local details, while any new durable accounting or end-user billing behavior would require separate authority.

The current requester question is whether Stage 2 should retain the existing quota-only same-chain advancement rule rather than use pinned-candidate failure handling. No approval of this policy is recorded yet.

### D5 policy acceptance — 2026-10-02 at 22:13:52 KST

- **Owner:** requester, after the Codex/Azents usage and failure-policy comparison.
- **Choice:** preserve the existing Lightweight candidate-failure semantics for Stage 2. Recognized quota/billing exhaustion updates shared candidate health and advances within the configured Lightweight chain. Ordinary provider errors and timeouts fail the work for later retry rather than authorizing another model route.
- **Exhaustion and capability:** no Main fallback, independent selector or one-shot degradation. Unsupported required tools are explicit capability failures, not synthetic quota failures or silent candidate-skipping permission.
- **Publication:** failed work does not replace the prior authorized published aggregate; current access checks still apply.
- **Usage scope:** retain content-free operational usage attribution and existing provider/cost-evidence semantics, with Stage 2 distinguished and attributed to its owning Agent/Workspace/internal job instead of an arbitrary source Session. This adds no end-user billing product or fabricated foreground Run.
- **Rejected alternative:** pinning the candidate and deferring even when another configured Lightweight candidate is usable after a quota failure, because it would introduce a Memory-specific exception to the current chain policy.
- **Remaining scope:** precise retry timing, execution restart, draft retention, progress checkpoints and resource limits belong to D7. These are not fixed by this acceptance.
- **Current decision map:** D1–D5 accepted; D6 invalidation is current; D7 recovery/resources, D8 presentation and D9 cutover pending. Primary Design approval and implementation authorization remain pending.

### D6 briefing — removal, revocation and invalidation granularity

#### Codex comparison

Evidence remains pinned to `14a477ea89712071944244022e8a10142845456e`:

- `memories/write/src/storage.rs::sync_rollout_summaries_from_memories` synchronizes the retained source-summary set and prunes summary files outside that set.
- `memories/write/src/phase2.rs` synchronizes inputs before computing the workspace diff; `workspace.rs::write_workspace_diff` supplies that diff to the Agent.
- `memories/write/templates/memories/consolidation_v2.md` instructs the Agent to remove claims supported only by deleted sources, preserve claims with remaining support, and avoid restoring corrected/deleted claims from older summaries. This is Agent-mediated semantic cleanup during consolidation.
- `memories/write/src/workspace.rs::reset_memory_workspace_baseline` removes the generated diff and resets the Git baseline; its documented purpose includes avoiding retention of deleted memory content in that artifact or unreachable Git objects.
- `ext/memories/src/prompts.rs::build_memory_tool_developer_instructions` reads/trims/truncates the summary file and renders it into the prompt. This inspected function does not reauthorize a per-source dependency manifest or await consolidation. It is not evidence of an Azents-style immediate multi-user revocation guarantee.

Do not equate Codex's retained-source pruning with Azents archive/purge/membership semantics. The useful comparison is diff-driven semantic cleanup, not permission authority.

#### Existing Azents and fixed outcomes

REQ-4 and the current Memory Spec already require exclusion before the next model operation/live read when a source is archived, purged or no longer authorized. This is fixed and must not be reopened as permission to keep serving a denied source until regeneration succeeds. Ordinary still-authorized content changes retain relaxed freshness.

`services/historical_memory/snapshot.py::filter_memory_context_snapshot` and its snapshot/context tests currently remove unavailable source-specific entries without reselecting/replacing the frozen boundary. This is straightforward for one-summary-per-source blocks; a new cross-source aggregate can contain mixed prose that cannot safely be filtered by deleting one route.

The service must track all supplied/read/inherited evidence dependencies, not just citations that the model elects to display. Revocation of any evidence that may have influenced an aggregate cannot be solved by claiming that the output does not visibly cite it.

#### Material choice

**A — Suppress the affected aggregate and rebuild from clean authorized inputs (recommended).**

- A denied dependency makes that aggregate unavailable at its next use. Do not inject or serve it while rebuilding.
- Apply this per accepted D3 ownership unit: Team aggregate or one User's personal aggregate. Do not disable unrelated independent aggregates or Saved Memory.
- Rebuild from current authorized source summaries without supplying the contaminated prior aggregate, draft or ephemeral conversation. Previously consumed content cannot be made safe merely by hiding its route.
- A changed but still-authorized summary can trigger ordinary incremental consolidation while the prior version remains usable. Unavailable evidence and stale-but-authorized evidence are distinct.
- Trade-off: unrelated useful content inside the affected aggregate is temporarily absent. If regeneration fails, that aggregate stays unavailable; independent authorized context and conversation remain usable.

**B — Independently dependency-bounded output fragments.**

- Publish and filter fragments whose complete evidence dependencies are independently bounded, preserving fragments unaffected by a revoked source.
- A model-generated citation list alone is insufficient. Fragment generation and any later merge must enforce or conservatively preserve those dependency boundaries; feeding every source to one model and asking it to label claims does not prove isolation.
- Trade-off: more generation/storage/validation boundaries and potentially weaker cross-source synthesis. Broad dependencies can still invalidate many or all fragments. This is a different output and processing contract, not a small rendering optimization.

**Not viable under confirmed Requirements:** continue using a denied-source aggregate until the Agent edits it, or remove only a source hyperlink and retain the prose.

The question concerns suppression granularity and rebuild inputs, not physical retention/garbage collection (D7/D9), read layout (D8), or a new strict-freshness policy. Restore and retry must reauthorize current evidence; they must not resurrect removed claims from an invalid draft. Exact lifecycle/race mechanisms belong in the primary Design after selection.

#### Verification implications

Test denial between source read and next internal model call, between draft completion and publication, and between boundary selection and foreground use. Assert that affected aggregate bytes are absent from subsequent model input and VFS reads, that independent Team/User units remain usable where authorized, and that clean rebuilding receives no invalid prior aggregate. Test ordinary authorized source edits separately to preserve the existing relaxed freshness contract.

This is a proposal; D6 is not accepted yet. Research inspected the cited code and tests; no new behavior or live revocation experiment was executed.

### D6 acceptance — 2026-10-02 at 22:52:17 KST

- **Owner:** requester.
- **Choice:** Option A, suppress the affected aggregate and rebuild from clean authorized inputs.
- **Scope:** a denied/archived/purged dependency invalidates use of the entire dependent Team or personal aggregate before its next model input or live read. Independent authorized aggregates and Saved Memory remain available; this is not a global Memory shutdown.
- **Rebuild boundary:** use currently authorized source summaries, without the contaminated prior aggregate, draft or ephemeral conversation. Track dependencies from all supplied/read/inherited evidence rather than only visible citations.
- **Freshness distinction:** ordinary content changes with continuing authorization may retain the previous result during incremental refresh. They do not trigger denial-style suppression merely because a newer source version exists.
- **Accepted trade-off:** unaffected information inside the invalidated aggregate is temporarily unavailable until a permitted replacement is published. Failed rebuilding does not make the invalidated result usable again.
- **Rejected alternative:** independently generated dependency-bounded fragments, due to the additional processing/storage boundaries and impact on cross-source synthesis. Removing only a hyperlink while retaining influenced prose is not a valid substitute.
- **Codex comparison:** retain the useful principle of source-change-driven semantic cleanup, but enforce Azents' fixed next-use authorization exclusion independently of model regeneration.
- **Not decided here:** physical data retention/cleanup, retry timing, coverage/checkpoint policy or display allocation.
- **Current decision map:** D1–D6 accepted; D7 recovery/resources is current; D8 presentation and D9 cutover pending. Primary Design approval and implementation authorization remain pending.

### D7 recovery briefing — work products after interruption

#### Codex comparison

Rechecked at `14a477ea89712071944244022e8a10142845456e`:

- `memories/write/src/phase2.rs` marks the internal Agent ephemeral and disables recursive memory generation/use. Recovery does not depend on a persisted consolidation conversation.
- `memories/write/src/workspace.rs::prepare_memory_workspace` preserves the existing usable workspace baseline and removes a previous generated diff, not the summary/artifact files. `phase2.rs::agent::handle` records invalid-artifact or Agent failure without rolling ordinary edited artifacts back to the previous successful contents; the failed-Agent path separately removes symlinks. Thus edited files can survive an unsuccessful attempt. This is workspace persistence, not a guarantee that a particular failed edit is safe or semantically complete.
- A subsequent attempt synchronizes sources, computes the workspace diff and can read the existing summary. This is a fresh Agent execution over retained work products, not resumption of the old model/tool conversation.
- `state/src/runtime/memories.rs::try_claim_global_phase2_job` persists job ownership, lease and retry state in the state database. `mark_global_phase2_job_succeeded` updates success/watermark and the exact selected source-version markers in one database transaction. That transaction does not include the filesystem summary write.
- If Agent shutdown cannot be confirmed, the Memory host leaves the existing lease to expire rather than immediately making the job available to another worker. Lease/heartbeat constants describe Codex only and are not adopted here.

This supports separating ephemeral execution from surviving files and operational progress. It does not establish Azents' draft revision/dependency atomicity or source-authorization rules.

#### Azents baseline and already accepted boundaries

`job_runtime/local.py::LocalJobRuntime` supervises process-local tasks and coalesces by an in-memory execution key; it is not a durable checkpoint or cross-process publication fence. Existing source preparation has database-owned failure/candidate progress, but no cross-source consolidation draft recovery implementation.

D2 fixes ephemeral conversation; D4 fixes private DB-backed drafts and host-owned validated atomic publication; D5 fixes Lightweight candidate progression; D6 forbids reuse of contaminated drafts/aggregates on source denial. These are not new choices.

D7 still needs decisions on cross-attempt work reuse, source coverage, distributed ownership/retry and resource/retention bounds. Resolve work reuse first; selecting it does not silently accept numerical caps or coverage guarantees.

#### Material choice

**A — Preserve bounded private draft work across attempts (recommended).**

- Retain committed draft revisions, their complete evidence dependencies/source-version metadata, minimal work-progress metadata and a bounded safe last-failure category separately from the conversation.
- After a worker crash, timeout or ordinary failed attempt, a new internal execution reacquires ownership, reauthorizes the complete dependency set and may read/revise the retained draft. Validation failure can be repaired in a later execution; it does not reopen the finished one.
- Retained text is unvalidated work, not published context. A read source or saved file does not by itself prove completed semantic integration; coverage semantics remain a separate D7 question.
- On dependency denial, apply D6: exclude the contaminated work and restart from currently authorized evidence, rather than passing that draft to the new model. Authorized source changes must be reflected in the new change inventory rather than hidden by an old progress cursor.
- Draft contents, revisions and dependency records need a coherent durable boundary. A draft without complete dependency evidence is unusable for recovery. No transcript, hidden reasoning or old provider continuation handle is retained.
- Benefit: interrupted large integrations can reuse completed edits instead of repeatedly rebuilding them. Cost: additional private work-state lifecycle, cleanup and consistency obligations.

**B — Discard attempt drafts and restart from the latest authorized published result.**

- Retain durable operational ownership, candidate/failure state and published data, but do not carry an unpublished draft into another attempt.
- Each new execution starts from the latest still-authorized aggregate and current source inventory; if D6 invalidates that aggregate, rebuild without it.
- Benefit: simpler cross-attempt content lifecycle. Cost: more repeated model work; a task that repeatedly exceeds an attempt budget may fail to advance unless coverage/chunking is designed accordingly.

Both choices preserve nonblocking conversation and host validation before publication. The current question is whether completed draft edits survive for authorized reuse by a fresh attempt, not whether to persist or resume the conversation.

#### Verification implications

Use deterministic interruption/takeover tests around draft commit, dependency recording, host validation and publication acknowledgement. Assert that replayed work never becomes published merely because it survived, old-owner writes cannot modify an adopted draft, denied dependencies prevent draft reuse, source-version changes remain visible, and no ephemeral transcript is required to recover.

This is a proposal; D7 work reuse and subsequent D7 choices are not accepted yet. Source code was inspected; no crash/recovery experiment or implementation was performed.

### D7 work-reuse acceptance — 2026-10-02 at 22:57:02 KST

- **Owner:** requester.
- **Choice:** Option A, retain committed private draft edits and minimal work progress across attempts, independently of the ephemeral conversation.
- **Retained products:** draft revision, complete evidence dependencies and source-version metadata, minimal work-progress metadata and a bounded safe failure category. A saved draft or source-read marker is not proof of successful semantic integration or publication.
- **Recovery:** a fresh internal Agent execution reacquires ownership and reauthorizes dependencies before reading/revising retained work. It does not resume the old transcript, hidden reasoning or provider continuation handle. Incomplete dependency evidence makes a draft unusable.
- **Failure boundary:** validation failure may be repaired by a later execution; it does not reopen the completed execution. Draft bytes remain private until host validation and atomic publication succeed.
- **Revocation:** D6 takes precedence. Contaminated drafts/aggregates are excluded from recovery input; restart from currently authorized summaries. Authorized source changes remain visible in the new change inventory rather than being hidden by a stale progress cursor.
- **Accepted trade-off:** retain additional bounded domain state and implement its consistency/cleanup lifecycle to reduce repeated model work after interruption.
- **Rejected alternative:** discard all unpublished work after every attempt and restart from the latest authorized published aggregate.
- **Codex comparison:** preserve the separation between fresh ephemeral execution and surviving work products, while adding Azents' database revision/dependency and authorization boundaries.
- **Still pending within D7:** source coverage semantics, ownership/retry mechanisms, numerical work limits and physical draft retention/cleanup. None is accepted merely by choosing work reuse.
- **Current map:** D1–D6 accepted; D7 work reuse accepted with the remaining D7 choices open; D8 presentation and D9 cutover pending. No implementation authorization or final Design approval.

### D7 coverage briefing — bounded passes versus a capped working set

#### Codex comparison

At `14a477ea89712071944244022e8a10142845456e`, `memories/write/src/phase2.rs` calls `get_phase2_input_selection(max_raw_memories_for_consolidation, max_unused_days)`.

`state/src/runtime/memories.rs::get_phase2_input_selection`:

- admits nonempty stage-one outputs inside a last-use window, using source-update time for never-used memories;
- ranks eligible candidates by usage count, then recent usage/source update, then source update and thread ID;
- selects up to the configured N, checking enabled-thread eligibility, and returns that selected set in stable thread-ID order;
- uses database paging to fill the selected top-N set, not to guarantee eventual consideration of the entire corpus across Agent passes.

The inspected ranking test `get_phase2_input_selection_prioritizes_usage_count_then_recent_usage` checks the winning candidate under that policy. Success bookkeeping records exact selected source snapshots, not proof that the model read or semantically integrated every supplied file.

The selected set becomes the complete synchronized filesystem input; files falling outside it are pruned. Therefore this is a bounded, ranked working set, not simply newest-N and not an exhaustive sweep. Its usage tracking, expiry and source-pruning policy are not automatically authorized for Azents.

#### Existing scope

Current Azents automatic presentation ranks and packs whole source summaries into a byte budget (`services/historical_memory/snapshot.py`). That is the behavior being replaced, not an existing consolidation coverage protocol. REQ-1 keeps the Agent in control of evidence inspection and revision; the Non-Goals exclude lossless inclusion of every Session or statement. Neither implies silently adding Codex's usage-age expiry or deleting existing source inventory.

The remaining choice is how an oversized set of currently eligible prepared summaries gets considered, while retaining bounded work per execution.

**A — Finite, resumable passes over the eligible inventory (recommended).**

- Establish a finite inventory/version boundary for a pass and expose bounded pages or slices. Keep progress so older pending items can advance instead of restarting from the top on every attempt.
- The Agent can inspect needed summary content and explicitly omit low-value material; every source need not appear in the aggregate. Selection for a page, reading a file, incorporating a claim and publishing a result are distinct facts.
- Resource exhaustion leaves unfinished work pending and does not count it as covered. An explicit considered/omitted disposition must not stand in for a source that was never presented.
- A normally completed, validated slice may publish useful partial consolidation while remaining coverage stays pending. A timeout, quota failure or hard budget exhaustion is not a successful slice and cannot publish merely because a draft exists, preserving D4/REQ-6.
- Later additions/updates remain visible as subsequent work. Live authorization still overrides the pass boundary, and D6 governs any contaminated state.
- Benefit: an arbitrary top-N cut does not permanently exclude eligible older work. Cost: potentially more background work and a durable coverage protocol. This is a scheduling/consideration contract, not a guarantee of perfect recall or eventual success under perpetual failure.

**B — Repeatedly consolidate a bounded priority-selected working set (closest to the inspected Codex shape).**

- Each attempt selects up to a configured number of eligible summaries and integrates that set; items outside it can remain unconsidered indefinitely.
- Benefit: simpler bounded work and predictable input-set size. Cost: systematic omission of low-ranked sources unless their priority changes.
- Azents would still retain its original source inventory and access rules. Ranking signals, treatment of prior-aggregate dependencies and any source-expiry policy would need explicit design; importing Codex's usage tracking or deletion behavior is not implied.

For both options, original transcripts remain outside consolidation input, output size is bounded separately by D8, and source availability does not imply current authorization. Numerical slice size, execution/time limits and cleanup remain later D7 work.

#### Verification implications

For A, test a corpus larger than several slices, interruption after a draft write, input updates during a pass, new arrivals, omission dispositions and revoked sources. Assert that work progress is tied to source versions, pending items do not disappear at a budget boundary, newer arrivals cannot repeatedly reset the same pass, and partial publication does not claim full coverage. Do not treat an inventory response or model-authored citation list as proof of semantic integration.

This coverage proposal is not accepted yet. The inspected Codex code/test is reference evidence, not an executed benchmark or an Azents implementation.

### D7 coverage acceptance — 2026-10-02 at 23:01:52 KST

- **Owner:** requester.
- **Choice:** Option A, finite resumable passes over currently eligible prepared summaries, with bounded work per execution and durable unfinished-work progress.
- **Coverage meaning:** the Agent may inspect relevant summaries and omit low-value material. Presenting an inventory entry, reading it, incorporating its content and publishing an aggregate remain separate facts. Exhausted budgets do not mark unseen work as covered.
- **Progress:** establish a finite inventory/version boundary per pass; preserve pending items across attempts instead of repeatedly selecting the same top-N. New or changed sources remain visible as subsequent work, while current authorization always overrides any captured boundary.
- **Publication:** normally completed and validated slices may publish useful partial consolidation without claiming complete corpus coverage. Interrupted, failed or hard-budget-exhausted execution cannot publish merely because it saved a draft.
- **Retained constraints:** no original-transcript reprocessing, no lossless recall promise, and no implicit adoption of Codex usage tracking, age expiry or source deletion. D6 invalidation and D7 reauthorization before draft reuse still apply.
- **Accepted trade-off:** more background work and durable progress management in exchange for avoiding a permanent top-N exclusion of eligible older work.
- **Rejected alternative:** repeatedly consolidate only a capped priority-ranked working set, as in the inspected Codex selection shape.
- **Still pending:** distributed ownership/retry, concrete work/resource limits and draft cleanup; D8 output/presentation and D9 cutover. This acceptance does not set numerical limits or approve implementation.

### D7 ownership briefing — one active writer per consolidation unit

#### Codex comparison

At `14a477ea89712071944244022e8a10142845456e`, `state/src/runtime/memories.rs::try_claim_global_phase2_job` claims a singleton consolidation job in its state database. An active lease causes another claimant to skip; retry/cooldown state is checked during admission. Claiming assigns a fresh ownership token.

`heartbeat_global_phase2_job` extends the lease for the matching running job/token. The phase-two host's heartbeat loop treats lost ownership or heartbeat errors as an Agent error and proceeds to shutdown. Final success is owner-token checked; the host also reconfirms ownership before updating the workspace baseline.

The inspected constants are a 3,600-second lease and 90-second heartbeat. These are reference values, not accepted Azents settings. The singleton belongs to that Codex memory store, not an Azents-wide lock across every Agent and User.

#### Azents baseline and fixed constraints

`job_runtime/local.py::LocalJobRuntime.submit` coalesces work in one process using an in-memory task dictionary. It cannot establish exclusive ownership across worker processes. D4/D7 already require current-owner authorization for private drafts and publication; this decision selects the execution-admission policy, not whether stale writers may commit.

No model call, provider I/O or wait for Agent completion may hold a database transaction open. Redis remains optional and cannot be the sole correctness authority.

#### Material choice

**A — A durable lease with fencing per D3 consolidation unit (recommended).**

- Key admission by the Team or personal ownership unit, not one global lock for all memory work. Only one current attempt owns that unit's draft/progress.
- Use PostgreSQL-owned lease/ownership-generation state and short claim/renew/commit operations. Independent units may run concurrently within the separately bounded worker capacity.
- Duplicate triggers coalesce pending work rather than spawn a second model execution for the same unit. Durable discovery/pending state must preserve work that arrives during execution or while the local worker is unavailable.
- Validate current ownership/lease in the same transaction as draft, progress and publication mutations. An old worker's delayed provider/tool response cannot commit after takeover; router-only admission and a publication-only lock are insufficient.
- On ownership loss or failure to confirm a renewal, stop admitting model/tool work and cancel the internal execution. Physical cancellation is best effort; database fencing, not the assumption that the old process has stopped, protects state.
- After expired ownership is reclaimed, a new execution reauthorizes the retained draft and follows accepted D7 recovery. Expiry does not itself confer success or make invalid work reusable.
- Benefit: avoid routine duplicate model cost and concurrent draft divergence. Cost: lease/heartbeat management and a takeover delay after an unobserved worker failure.

**B — Permit speculative duplicate attempts with isolated drafts and compare-and-swap publication.**

- Several independently owned attempts may process the same unit, but never share a mutable draft. Publication compares the expected aggregate revision and only an authorized non-conflicting result commits.
- Every attempt still needs ownership fencing and dependency authorization; conflicts require discarding/rebasing work rather than blindly replacing a winner.
- Benefit: no unit-wide admission lease is needed to begin speculative work. Cost: duplicated model calls, multiple drafts, more recovery/cleanup state and rejected completed work. Compare-and-swap protects the final state, not the budget.

The recommendation extends the Codex lease principle to independent Azents units and fences every database work mutation, rather than copying its filesystem write boundary. Exact lease duration, heartbeat interval, retry delays, concurrency caps and cleanup thresholds remain the next D7 resource-policy discussion.

Verification must deterministically order concurrent claims, renewal loss, lease expiry, takeover and delayed old-worker mutation. Assert that only the current owner commits, independent units remain concurrent, duplicate triggers are not lost, database unavailability fails closed and Redis loss cannot authorize duplicate writers.

This ownership policy is proposed, not accepted. No distributed execution experiment or implementation was performed.

### D7 ownership acceptance — 2026-10-02 at 23:08:29 KST

- **Owner:** requester.
- **Choice:** Option A, PostgreSQL-backed lease and ownership fencing per accepted Team/personal consolidation unit, with one current attempt owning that unit's draft/progress.
- **Admission:** coalesce duplicate requests into pending work rather than routinely launch duplicate model executions. Independent units may run concurrently within bounded capacity. Durable pending/discovery state prevents requests arriving during execution from being lost.
- **Mutation boundary:** current ownership/lease must be checked within each draft/progress/publication transaction. Delayed responses from an old worker cannot commit after takeover. Model calls and other external I/O remain outside database transactions.
- **Loss and recovery:** stop admitting new model/tool work and cancel the internal execution when ownership is lost or renewal cannot be confirmed. Physical cancellation is best effort; the database fence remains authoritative. A new owner may recover after expiry and must reauthorize retained work before use.
- **Dependency:** Redis is not required for exclusive ownership or safe publication.
- **Accepted trade-off:** lease/heartbeat management and bounded takeover delay in exchange for avoiding duplicate model cost and divergent concurrent drafts.
- **Rejected alternative:** speculative duplicate attempts with isolated drafts and compare-and-swap-only final arbitration.
- **Codex comparison:** adopt its durable lease principle per Azents ownership unit; do not copy a single global lock or assume filesystem shutdown alone fences writes.
- **Still pending:** concrete execution/resource limits, lease/heartbeat timing, retry cadence and draft cleanup; D8 presentation and D9 cutover. No final Design approval or implementation authorization.

### D7 operational envelope — proposed initial defaults

#### Reference evidence and qualification

At Codex `14a477ea89712071944244022e8a10142845456e`, `memories/write/src/lib.rs` sets the Stage 2 lease and retry delay to 3,600 seconds and heartbeat to 90 seconds. `state/src/runtime/memories.rs` applies a six-hour success cooldown to the global job. Its configurable ranked-source cap and unused-source retention are distinct from Azents' accepted resumable coverage and source-retention constraints; do not import them as a package.

Azents currently has 16 local Job Runtime slots (`job_runtime/deps.py`), source-preparation concurrency defaulting to 15 with at least one slot reserved (`services/historical_memory/job.py`), a 30-minute preparation request deadline (`discovery.py`), and failure backoff from 60 seconds to six hours (`repos/historical_memory/preparation.py`). The supporting proposal's Section 12.1 already listed candidate consolidation limits, but those are not measured or accepted production values.

The following is a coherent starting envelope for validation, not a benchmark result, guaranteed currency ceiling or automatically approved tuning range. It supersedes conflicting recommendations in the supporting proposal only if selected. Output format and foreground budgets remain D8.

#### Recommended short-slice, bounded-retention profile

| Area | Proposed initial contract |
|---|---|
| Attempt | Ten-minute absolute execution deadline; at most 32 model requests and 96 dispatched tool calls, counting failures/retries that actually dispatch. |
| Token work budget | 250,000 cumulative input and 16,000 cumulative output tokens across model requests in an attempt, including repeated context. Use preflight estimates/reservations and available actual usage; do not start another request after budget exhaustion. Missing provider usage is unknown, not zero, and estimation error means this is not an exact billed-token/currency guarantee. |
| Context admission | Stop/checkpoint before another model request would exceed 70% of the resolved input window. Do not replace the accepted ephemeral recovery model with persisted conversations. |
| Bounded tool I/O | At most 50 inventory rows per page and 12,000 UTF-8 bytes of text per tool-result body, with explicit continuation/truncation. These are operation bounds, not whole-pass source caps. |
| Draft content | At most 16 files and 256 KiB total UTF-8 file content per current unit draft. Keep one current draft rather than an unbounded private file-version history. Dependency/coverage metadata is separate, versioned domain state, not hidden transcript storage. |
| Ownership timing | 120-second lease, renewed every 30 seconds, with current ownership and lease checked at commit. Database time governs validity. |
| Process capacity | Source preparation default 12 and consolidation default 2; enforce a combined Memory cap of 14 within the existing 16-slot runtime, leaving at least two slots available to non-Memory work. Validate configured caps together rather than merely adding independent limits. |
| Discovery | Recover due work on the existing five-minute discovery cadence, with coalesced event-driven requests able to start earlier. The cadence is not a promise that a one-minute retry runs exactly one minute later. |
| Failure retry | Preserve the existing one-minute exponential backoff capped at six hours. Apply accepted D5 quota-only candidate progression; do not add fixed one-hour retries or a six-hour success cooldown from Codex. |
| Productive continuation | Normally completed slices with remaining work yield and requeue through bounded capacity without failure backoff. Failed or hard-budget-exhausted attempts retain permitted work but do not publish. Three consecutive slices/attempts with no new source-version disposition or distinct valid-draft progress trigger backoff and an operational warning, not invented completion. |
| Ineligible work | Memory-disabled/permission-denied work waits for current eligibility instead of repeatedly calling a model. Source denial also applies D6 and queues contaminated-payload cleanup. |
| Draft cleanup | A recoverable draft becomes cleanup-eligible after 24 hours without meaningful progress. Superseded/terminal private payloads become cleanup-eligible immediately and are swept periodically. Active current-owner work is protected by fenced cleanup. Denied content is unusable immediately, independently of physical cleanup scheduling. |

These per-process limits are not a cluster-wide model-spend ceiling. With several worker processes, aggregate capacity grows accordingly; per-unit ownership still prevents concurrent authorized writers to the same unit. No new user-facing setting or billing product is proposed. Changing deployment-wide capacity or introducing a system-settings surface is not silently authorized.

Cleanup removes private payloads, not published memory or source inventory. When an unpublished draft expires, invalidate draft-dependent unpublished progress so the next attempt starts from the latest authorized published checkpoint and still-pending source inventory. Do not retain a false processed marker after deleting the only work product that justified it. Cleanup downtime can delay physical deletion; 24 hours is an eligibility threshold, not an unconditional wall-clock deletion guarantee.

Numerical context/token/file bounds need implementation feasibility tests before final Design approval. If accurate token admission is unavailable for a provider, retain explicit estimates and hard request/tool/time bounds; do not claim an exact token charge limit. Limits must produce truthful pending/failed outcomes and preserve accepted recovery semantics.

#### Alternative and approval boundary

A longer-attempt/longer-retention profile (for example, 30-minute attempts and seven-day inactive-draft retention) reduces repeated context reconstruction after interruptions but holds capacity longer and retains private work payloads longer. The recommendation is the ten-minute/24-hour profile above, with the stated initial quotas, because resumable drafts and finite slices already provide progress without long uninterrupted execution.

This is one disclosed operational-profile choice. Exact numerical defaults have not been approved. Material changes after approval return to ADR/Design review rather than being justified as invisible tuning.

#### Validation obligations

Use deterministic deadline/budget/lease clocks and controlled provider/tool fixtures. Verify every cutoff, unknown usage, repeated context accounting, no publication after hard exhaustion, shared capacity across both handlers, unrelated-job capacity, productive requeue fairness, stalled-work backoff, and fenced cleanup/expiry without lost pending sources. Measure representative source counts and model/context shapes; no current latency/cost or large-corpus performance claim is made by this research.

### D7 operational-envelope acceptance — 2026-10-02 at 23:16:21 KST

- **Owner:** requester, after the complete numerical-profile briefing and Codex comparison.
- **Choice:** the recommended short-slice, bounded-retention profile in the preceding operational-envelope table, including its estimation, per-process-capacity and cleanup-timing qualifications.
- **Accepted initial bounds:** ten minutes, 32 model requests, 96 dispatched tools; cumulative input/output token budgets of 250,000/16,000 with explicit estimation limitations; next-request admission within 70% of the resolved input window; 50 inventory rows per page; 12,000 UTF-8 bytes per tool-result body; 16 files/256 KiB per current draft.
- **Ownership/capacity:** 120-second lease with 30-second renewal; default per-process source-preparation/consolidation concurrency 12/2 with enforced combined cap 14 inside the existing 16-slot runtime. This explicitly changes the prior preparation default of 15 and does not claim cluster-wide spend control.
- **Continuation/retry:** productive completed slices yield/requeue; failure backoff starts at one minute and caps at six hours; three no-progress slices/attempts trigger backoff and an operational warning; five-minute discovery recovers due work, with earlier event-driven admission permitted. Ineligible work does not repeatedly invoke models.
- **Retention:** 24 hours without meaningful progress makes a recoverable draft cleanup-eligible; superseded/terminal private payloads become eligible immediately. Fenced periodic cleanup protects active work, resets deleted-draft-dependent unpublished progress, and preserves published memory and source inventory. Denied bytes are unusable immediately; physical cleanup is not guaranteed during downtime.
- **Rejected alternative:** longer uninterrupted attempts and seven-day inactive-draft retention as the initial profile.
- **Qualification:** these are approved initial design values, not measured performance results. Feasibility and deterministic boundary/capacity tests remain required before final Design approval. Material changes require renewed authority rather than silent tuning.
- **Current map:** D1–D7 accepted; D8 aggregate presentation/read contract is current; D9 cutover pending. Primary Design approval and implementation authorization remain pending.

### D8 briefing — authored compact document versus foreground entry selection

#### Codex comparison

At `14a477ea89712071944244022e8a10142845456e`, `memories/write/templates/memories/consolidation_v2.md` requests a Markdown `memory_summary.md` with a `v1` marker and User Profile, User preferences, General Tips and What's in Memory sections. It asks for fewer than 10,000 UTF-8 bytes, recent project/date groupings, concise older topics and meaningful exact routes to rollout summaries.

`ext/memories/src/prompts.rs::build_memory_tool_developer_instructions` reads the summary file, trims it, applies token-based truncation and inserts it into a fixed read-path template. The constant in `ext/memories/src/lib.rs` is 2,500 tokens. This is distinct from the writer's byte bound; neither guarantees that every character from a valid writer artifact reaches the model under every language/tokenization shape.

`ext/memories/templates/memories/read_path_v2.md` wraps the summary as historical context, advises targeted source lookup only when useful and gives current instructions/evidence precedence. The inspected injection function does not parse claims into an independently ranked, current-conversation-specific entry store or invoke another summary model.

Thus Codex primarily lets the consolidation Agent author the compact view; the read path loads that document with a separate length safeguard. Its particular preference headings and token truncation are reference behavior, not automatic Azents authority.

#### Fixed Azents outcomes and existing baseline

REQ-2 already requires concise historical context plus meaningful routes to permitted detailed summaries. D3 keeps Team/personal aggregates separate; REQ-5 fixes Run/compaction refresh boundaries and child inheritance. Saved Memory retains separate semantics and budgeting. The Memory Spec's current source-summary packing ranks bounded candidates and fits whole groups inside a 10,000-byte budget; this is existing presentation behavior being replaced, not a mandate for the new aggregate to retain per-entry ranking.

This decision concerns model-facing automatic context, not a new user settings screen.

#### Material choice

**A — Publish a compact Markdown view authored by the consolidation Agent (recommended).**

- Each unit's result contains concise historical context (supported decisions/corrections, progress, uncertainty and reusable context) and useful source routes with short descriptions. Exact headings/file names are local details; a separate generated user-profile/preferences subsystem is not introduced.
- At a refresh boundary, the foreground host selects currently authorized aggregate revisions and wraps their authored compact text with server-owned scope/provenance. It does not re-rank or summarize individual claims based on the current topic.
- Validate canonical source routes and the eventual per-unit/combined display bounds before publication. Do not copy Codex's arbitrary text truncation as a way to silently cut a route or qualifying sentence.
- Preserve normal read-only VFS access to authorized published aggregates and detailed summaries; private drafts are not exposed through the foreground mount. Source routes and paths are not publication or access capabilities.
- Benefit: the final compact account is controlled by the consolidation Agent, with one simple readable work product rather than another foreground selection layer.
- Trade-off: consumers of the same unit get the same compact account at the same selected revision; it is not dynamically tailored to each current topic. Whole-document inclusion requires coherent per-unit budgets and scope composition, which remain the next D8 choice.

**B — Publish typed small entries and select them again at the foreground boundary.**

- The Agent still uses file tools, but the work product follows a parseable entry schema. Server-owned validation/rendering ranks and packs whole entries under the consumer's current topic and budget.
- Benefit: more topic-specific context and flexible Team/personal byte allocation.
- Cost: another authoritative item schema, ranking/selection contract and state surface. An independently phrased qualifier or related source route can be omitted unless entry boundaries explicitly preserve their relationship.
- This is not the rejected semantic section-edit tool API; it is an alternative published representation and read-time selection mechanism.

The earlier supporting proposal recommended ranked typed entries and a 4,000/6,000 split with budget lending. Those remain unaccepted. Choosing A would replace that entry-selection recommendation; its exact total/per-unit bytes and live-read routes must then be resolved consistently rather than silently retaining incompatible packing rules.

#### Validation implications and remaining scope

Verify no unexpected model call or entry re-ranking during foreground preparation for A; preserve stable revision/text between authorized refresh boundaries, complete meaningful source routes, Team/User isolation and D6 denial. Include multilingual byte/token boundary fixtures, empty results, long routes and simultaneous presence of both scopes.

Only the authored-document versus foreground-selected-entry mechanism is proposed here. Numerical aggregate budgets, scope allocation and final read-path details remain D8 follow-ups; D9 cutover and complete Design approval remain pending.

### D8 document-presentation acceptance — 2026-10-02 at 23:23:56 KST

- **Owner:** requester.
- **Choice:** Option A, a compact Markdown account authored by the consolidation Agent, with historical context and meaningful routes to authorized detailed summaries.
- **Foreground behavior:** select authorized published revisions at the accepted Run/compaction boundaries and add server-owned scope/provenance; do not re-rank individual claims by current topic, invoke another summarizer or arbitrarily truncate the authored document.
- **Publication validation:** enforce canonical permitted source routes and coherent eventual display bounds before publication. Empty useful content does not authorize a fabricated account. Exact headings and equivalent renderer layout remain implementation details.
- **Access:** preserve read-only authorized VFS lookup of published aggregate content and detailed summaries; drafts stay private. Saved Memory remains independent.
- **Accepted trade-off:** consumers of the same unit/revision receive the same compact account rather than a topic-specific subset.
- **Rejected alternative:** typed entry publication with an additional foreground ranking/packing layer. This supersedes the supporting proposal's entry-ranking, per-entry cap and dynamic packing recommendation; it does not select its old 4,000/6,000 allocation or budget lending.
- **Codex comparison:** follow the authored-document read pattern without adopting its independent arbitrary token truncation or its particular profile/preferences sections as another subsystem.
- **Remaining D8 scope:** total/per-unit byte allocation and explicit published-read contract. D9 cutover and complete Design approval remain pending; no implementation authorization.

### D8 budget and read-contract briefing

#### Evidence and constraint

At the same Codex commit, `memories/write/src/workspace.rs::is_valid_v2_summary` enforces fewer than 10,000 UTF-8 bytes for the single summary artifact, while `ext/memories/src/prompts.rs` independently applies the 2,500-token read-path limit defined in `ext/memories/src/lib.rs`. This does not specify how to compose two independently owned Team/personal documents without truncation. The GitHub page returned HTTP 503 during this check; the exact commit's local Git objects were used to verify these functions, without claiming an upstream freshness update.

Azents' current Memory Spec already caps the complete Historical automatic view at 10,000 UTF-8 bytes. D3 now requires independent Team/personal units and the accepted D8 mechanism includes whole authored documents. Consequently, arbitrary budget lending cannot coexist with one potentially full-size document per unit, unchanged total budget and no truncation/re-ranking. Do not silently keep the supporting proposal's entry-packing/lending policy.

#### Recommended allocation — equal fixed scope budgets

- Keep the complete automatic Historical view at no more than 10,000 UTF-8 bytes; Saved Memory budgeting remains separate.
- Give each Team or personal aggregate at most 5,000 bytes of fully rendered automatic-context footprint, including its allocated scope/provenance/instruction-boundary overhead and separators. Account for all common framing inside these allocations; the body itself must be smaller when the server envelope consumes bytes.
- Use the same unit render and cap for Team-only and personal consumers so one shared artifact can be included unchanged in either context. Compose up to two independently authorized complete units without additional model calls or entry selection.
- If only one unit is available, its fixed cap remains 5,000 bytes; do not enlarge or regenerate it merely because the other slot is empty. Unused bytes remain unused.
- Reject oversized publication rather than cut a sentence or route. Under D4, a later attempt may repair an invalid draft; foreground preparation does not repair it by truncation.
- Empty or denied units contribute no fabricated account. The full allowed published overview is still compact; detailed source summaries provide depth beyond that overview.

This is a predictable initial allocation, not a measured optimal language/recall ratio. Byte limits are not token counts and require multilingual fixtures.

#### Alternative — fixed Team 4,000 / personal 6,000

Maintain the same 10,000-byte total and whole-document rule, but prioritize personal context with a 4,000-byte Team cap and a 6,000-byte personal cap, including framing. A Team-only consumer then still gets at most 4,000 bytes. This remains viable but introduces a deliberate weighting without evidence that personal context consistently deserves more budget.

Neither alternative lends unused space, introduces large/small output variants or raises the total budget. Those are different material mechanisms and are not implied by this choice.

#### Published-read contract paired with either allocation

- Expose one canonical read-only current published aggregate locator per authorized Team/personal unit through the existing Memory VFS; candidate spellings are `azents://memory/consolidated/team/summary.md` and `azents://memory/consolidated/user/summary.md`.
- Resolve the personal alias from the server's current associated-User authority, never a model-supplied User ID. Preserve current Agent/Workspace/membership, Memory-enabled, source-lifecycle and non-enumerating denial checks.
- Exact reads return the latest currently authorized published revision with provenance and the authored overview. Such an explicit live read may see a newer revision than the automatic boundary snapshot; it does not silently replace that snapshot.
- Authorized discovery/search may expose the published aggregates; private drafts, operational work products and invalidated aggregate bytes remain unavailable to the foreground mount. No VFS import/transfer capability is added.
- Keep existing source-summary/Saved/original-history routes and their independent authority. Canonical source routes in the overview lead to detailed summaries; this does not authorize consolidation to read original transcripts.
- A missing/denied aggregate uses the existing unavailable/omitted behavior rather than triggering synchronous generation or whole-source-body automatic fallback.

The question is equal fixed scope allocation (recommended) versus weighted fixed allocation, with the read contract above. Exact URI spelling, headings and equivalent local rendering helpers remain implementation details. Validate byte accounting of every envelope/separator, both-scope composition, single/empty scope behavior, full route integrity and live-read/snapshot divergence before final Design approval.

No allocation is accepted yet; D9 and complete Design approval remain pending.

### D8 budget decision and D3 isolation clarification — 2026-10-02 at 23:28:44–23:29:30 KST

- **Owner:** requester.
- **Updated authority:** REQ-2/REQ-3 now explicitly record the independently bounded Team/personal overviews and model-facing work isolation. This requirement update precedes the decision record.
- **Choice:** each unit independently has a 10,000-UTF-8-byte automatic-context footprint allowance, including its own attributable envelope. Reject both the proposed 5,000/5,000 split and the 4,000/6,000 alternative.
- **Foreground consequence:** a personal consumer with both authorized documents can receive up to 20,000 Historical bytes; Team-only or one available document uses up to 10,000. Saved Memory remains separate. Do not keep the former shared 10,000-byte cap or implicitly truncate/re-rank either document to fit it.
- **Independent generation:** a Team consolidator is supplied only its Team summary inventory/evidence and own prior aggregate/draft/progress; a personal consolidator is supplied only the associated User's personal equivalents. The general foreground permission to read both scopes must not be reused as the personal consolidator's input grant.
- **Mutual non-exposure:** prompts, initial task data, tool catalogs/descriptions, inventory/search/read results, validation feedback and continuation work metadata must not expose the other consolidator's existence, identity, job status, source inventory, budget use, draft or result. Reuse shared code and operational infrastructure, not each other's model-visible state.
- **No coordination:** both receive only their own 10,000-byte contract. Neither is instructed to manage a combined 20,000-byte budget, reserve space for a peer or borrow unused capacity. No messages/delegation, cross-read, shared editable document, joint summarization or model-level reconciliation is introduced.
- **Composition boundary:** only the ordinary foreground host combines the independently authorized completed documents, using server-owned framing and accepted Run/compaction refresh semantics. This is deterministic composition, not another Agent operation.
- **Publication/read behavior:** whole authored documents, canonical authorized source routes and per-unit size validation remain in force. The previously described read-only current aggregate access uses ordinary foreground authority; it does not grant either consolidation execution access to the other scope.
- **Codex comparison:** its inspected single-summary byte limit remains useful reference evidence, but it does not supply Azents' two-unit isolation/composition contract. This choice follows the requester's explicit direction, not a claimed Codex Team/User equivalent.
- **Verification:** use distinct Team/personal sentinel evidence and model-request capture to prove each consolidator receives only its own inventory/work state, including on retries and validation errors. Test denied cross-scope lookup without peer metadata disclosure, independent size validation regardless of peer availability/length, 10,000-byte boundary accounting per block and up to 20,000-byte complete foreground composition. Do not treat an output-redaction test as evidence of input isolation.
- **Current map:** D1–D8 accepted with this explicit isolation clarification; D9 cutover remains pending. Full authority/feasibility audit, primary Design approval and implementation authorization are still required.

## Autonomous completion of remaining technical design

At 2026-10-02 23:36:04 KST the requester directed the Agent to stop pausing and finish the design. Remaining technical judgments and complete technical Design review are handled in Autonomous mode, with a dedicated technical interviewee as decision owner. Previously confirmed product outcomes and requester decisions remain fixed. This delegation does not authorize implementation, deployment, live-data changes or new product scope.

The primary Design is the consolidated current contract; earlier proposal/hold entries in this append-only ADR remain decision history. Supporting exploration is not independent authority.

## memory-261002/ADR-D9 — Accepted: coordinated cutover and reversible data-preserving handover

- **Owner:** dedicated technical interviewee under the autonomous-completion delegation, 2026-10-02.
- **Authority:** REQ-5/REQ-6/REQ-7/REQ-8 and D1–D8.
- **Codex evidence:** at `14a477ea`, `memories/write/src/start.rs` optionally runs both V1/V2 pipelines when `memories.dual_write` is enabled. `protocol/src/memory_version.rs` separates `memories` and `memories_v2` roots; `startup_dual_write_tests.rs` verifies independent stores. Codex supports an explicit dual-pipeline alternative; the chosen Azents cutover is not an exact copy.
- **Choice:** a coordinated quiesced cutover rather than an additional activation mode or prolonged dual-read/dual-write compatibility layer.
- **Data:** add consolidation/work storage; preserve current source summaries, source history and Saved records. Initialize units from already prepared, currently authorized summaries in their exact scope without repeating Stage 1 inactivity admission.
- **Handover:** pause admission to affected old execution workers, drain or perform their normal durable handoff, and confirm old readers/writers/owners are no longer able to consume or mutate automatic Memory state before snapshot conversion and new-code activation. Pausing only the Memory scheduler is insufficient while old foreground executors remain active.
- **Interrupted Runs:** retain existing IDs, history, status and normal owner-fenced recovery. Before the next newly lowered model request, perform normal root Run-start Memory preparation; no fabricated foreground Run, terminal event or transcript deletion. Children retain root inheritance.
- **Snapshots:** explicitly reset the old automatic `memory/context_snapshot` kind through a bounded idempotent migration/reset operation. A new schema kind identifies aggregate references/text; never decode old whole-source bodies as new aggregate data. Rebuild the Saved index from unchanged canonical Saved rows at the next preparation boundary.
- **Initial availability:** omit missing Historical aggregates while conversation, Saved Memory and authorized source lookup continue. Do not synthesize the old packed-summary fallback. Initial bounded discovery plus periodic durable discovery fills/retries work without foreground model generation.
- **Rollback:** quiesce and fence new workers, reset new automatic snapshots, restore tested previous application code and reconstruct its ordinary snapshots from retained canonical data at normal preparation. Keep additive tables inert; no destructive down migration or hidden runtime fallback.
- **Rejected alternative:** prebuild/shadow processing plus an explicit activation gate and dual-format compatibility. It can reduce initial recall gaps but adds state, operational modes and mixed-version reader/writer obligations not needed by confirmed Requirements.
- **Evidence gates:** rehearse old interrupted roots/children, provider continuation/cache invalidation when Memory changes, concurrent source revocation, old-worker absence, exact schema decoding, missed discovery and reverse cutover. This is not a zero-downtime guarantee or authorization to interrupt/delete conversations arbitrarily.
- **Status:** accepted technical design contract only. The complete revision-bound primary Design remains subject to authority/feasibility review.

## memory-261002/ADR-D10 — Accepted: current-summary version identity and purge-safe dependencies

- **Owner:** dedicated technical interviewee under delegated design completion, 2026-10-02.
- **Evidence:** current `RDBHistoricalMemorySource` stores a mutable summary. `HistoricalMemoryRepository.publish_completed_in_session` updates it under source/Agent/membership authority locks; no immutable summary-version identity exists. Its source-to-Session foreign key cascades on purge.
- **Choice:** add monotonically advancing server-owned `summary_generation` and a deterministic hash of the supplied summary/rendered-evidence fields to current-source publication. Publish body, generation/hash and relevant evidence metadata atomically. Backfill already prepared rows explicitly; distinguish unprepared/empty from a ready body.
- **Read contract:** captured work uses source identity/generation/hash. If the current row no longer matches before evidence is supplied, mark that captured work superseded/unconsumed and enqueue the current generation. Do not fabricate/retrieve a historical body from a current mutable row.
- **Relaxed freshness:** a change after a legitimate evidence exposure does not itself revoke that evidence or prohibit an older still-authorized aggregate. Preserve the newer generation as pending work. Authorization/lifecycle loss invokes D6; version inequality alone does not.
- **Evidence:** capture receipts for all model-visible source evidence, including initial metadata and search snippets, plus inherited aggregate dependencies. A hash is version/integrity evidence, never an access grant.
- **Purge safety:** retain body-free dependency identity independently of source-row lifetime for the lifetime of the aggregate/draft. Missing source state fails closed. Never cascade away the only record proving dependency on a purged source. Eager reverse invalidation may accelerate cleanup, but absence checking remains authoritative; no immortal body-bearing tombstone or summary archive is introduced.
- **Rollback:** old code does not maintain the new identity fields. On reactivation after rollback, revalidate/backfill identities and invalidate incompatible work before trusting retained generations.
- **Rejected alternative:** immutable historical summary-body revisions, because they add retention and privacy obligations unnecessary for accepted recovery.
- **Authority:** REQ-3/REQ-4/REQ-7, D6, D7 and D9. No new source-history product or stricter content-freshness policy.

## memory-261002/ADR-D11 — Accepted: observed revisions and bounded mutation receipts

- **Owner:** dedicated technical interviewee, 2026-10-02; authority D4/D7.
- **Choice:** execution-local observed-revision ledger plus atomic idempotent mutation receipts, without adding required revision arguments to all generic/Runtime tool schemas.
- **Observations:** only revision-aware draft reads and successful current mutation results establish observed existence/revision. A fresh execution rereads; read-only backends and Runtime are not required to implement these mutation semantics.
- **Admission:** freeze preconditions at tool-call admission. Parallel sibling calls capture the same pre-dispatch ledger, not revisions lazily updated by a previous sibling. A conflict requires rereading.
- **Existence:** create-if-absent is atomic without an existing revision. Existing-file overwrite/edit/delete and existing patch targets require observed versions. A stale overwrite cannot silently become a create, and delete/recreate receives a fresh revision.
- **Idempotency:** identify receipts by attempt/tool-call ID and canonical request digest with exact text bytes significant. Same identity/digest replays its original result; different digest under a reused call ID fails. Validate current scope/ownership before replay as well as mutation.
- **Transaction:** commit files, versions, complete draft dependency state and receipt together. A replay reports the originally committed revision, not current file state, and cannot move the observation ledger backward.
- **Patch:** one authorized draft transaction domain, all preconditions captured, all applicability checked, all-or-none commit with one receipt; reject mixed-domain targets.
- **Retention:** receipts contain digest and safe bounded mutation metadata, not replaced bodies, old file histories or raw tool transcripts. Bound them by admitted work and D7 lifecycle. Source evidence receipts are separate.
- **Rejected alternative:** required `expected_revision` fields throughout generic/Runtime schemas.

## memory-261002/ADR-D12 — Accepted: metadata-only durable source-work enrollment

- **Owner:** dedicated technical interviewee, 2026-10-02; authority D7/D10.
- **Choice:** a metadata-only source-generation work journal/outbox, not an archive of summary bodies. Publish source generation/hash and idempotent scoped work enrollment atomically; bounded backfill seeds existing sources and rollback reactivation.
- **Lock separation:** derive scope from authoritative source metadata and insert enrollment without taking a consolidation-unit ownership lock or an indirect unit-locking FK/trigger. The dispatcher creates/claims units separately.
- **Finite passes:** capture an upper work sequence and page at most 50 pending entries. Acknowledge exact validated disposition IDs associated with successful publication, never every row below a watermark. Each pass/discovery queries still-pending work independently of a global completed cursor; late-committed lower sequence rows remain discoverable.
- **Progress states:** distinguish pending, draft-considered, published disposition and superseded/not-covered. Generation mismatch retires obsolete enrollment only while ensuring the current generation remains pending. Draft expiry returns unpublished dependent progress to pending.
- **Change/removal:** empty-summary and removal signals keep affected units dirty/pending rather than silently disappearing. D6 access denial remains immediate regardless of queue delivery.
- **Bounded retention:** bound operation sizes and live metadata; coalesce obsolete unconsumed generations where safe and sweep terminal rows without dropping pending items, active-pass references or durable published-coverage evidence. D10 dependency identity outlives source/journal rows as needed.
- **Publication:** exact acknowledgements, aggregate revision, dependency manifest and durable progress commit together under current ownership. New concurrent work stays pending.
- **Alternative:** identity high-water plus dirty-epoch repeated scans can be valid with page-time version capture, but require careful coverage/reconciliation for late commits and changes behind the cursor. Reject it as the primary incremental work tracker here; retain bounded scans for seeding/repair.
- **No claim:** a metadata journal cannot reconstruct overwritten bodies or guarantee exactly-once model execution. Deterministic races must cover late commits, empty outputs, crash before/after publication, cleanup and purge.

## Decision ownership correction and direct completion

The requester questioned delegation of design decisions and requested direct ownership by the primary Agent. The earlier Autonomous/interviewee assignment was an over-broad interpretation of the instruction to finish without repeated pauses. The interviewee was stopped; its approval is not authority for this snapshot and will not substitute for requester Design approval.

The primary Agent directly rechecked the current summary publication transaction and purge FK, snapshot model/decoder and refresh code, generic VFS optional-protocol precedent, foreground-bound event types, process-local Job Runtime, and pinned Codex version/dual-write/claim behavior. On that basis, the primary Agent retains D9–D12 as its directly owned technical completion decisions within the existing confirmed requirements, not as subagent-approved or requester-selected choices. Their alternatives, qualifications and tests remain part of the decision record.

The direct review additionally fixes these interpretation boundaries:

- Publication reauthorization uses repository-owned, short database operations, indexed complete-manifest checks and stable authority/source lock ordering. No new epoch-based authority system, summary-body archive, truncated dependency set or long transaction spanning model I/O is introduced. Manifest cardinality is not capped by a 50-row tool page; latency/lock footprint must be measured, and a deadline/conflict fails closed rather than dropping dependencies.
- Source publication/outbox insertion must not acquire the unit-ownership lock after source/Agent locks while finalization acquires the same resources in reverse order. Dispatcher admission and source-change enrollment remain separate transactions; finalization follows a documented consistent authority order.
- Optional V4A patch exposure depends on both backend atomic-patch support and model wire-profile support. Required ordinary file tools remain usable on other tool-capable Lightweight candidates; absence of the optional patch dialect is not itself a configuration failure.
- Only committed work-product receipts are durable. Read observations are execution-local, and provider continuation identity, prompts, tool-result transcript and hidden reasoning are not recovery data.
- The primary Design will distinguish completed document/feasibility review from runtime verification and requester approval. Neither implementation nor final requester approval is recorded by this correction.

Effective mode: direct primary-Agent design completion with requester-owned final approval. No further subagent design delegation is part of this work.

## memory-261002/ADR-D13 — Direct-review decision: preserve revocation continuity across restore

- **Owner:** primary Agent, directly reviewing completion under REQ-3/REQ-4 and accepted D6, on 2026-10-02.
- **Gap found:** `AgentSessionRepository.archive_tree`/`restore_tree` can make a source unavailable and available again; current availability alone does not prove that an old aggregate was rebuilt after the intervening denial. A fast archive/restore before the next read must not silently rehabilitate contaminated aggregate/draft bytes.
- **Choice:** retain a monotonically advancing evidence-availability generation on a prepared source, separate from content `summary_generation`. Increment it transactionally on source-level access/lifecycle loss; restoring availability never resets it. Capture it in complete dependency receipts/manifests. For personal sources also bind the durable Workspace membership identity; removal/recreation of membership cannot validate the old grant.
- **Use:** compare captured availability generation/grant identity as well as current scope/lifecycle. A mismatch invokes D6 clean rebuilding even if access is currently restored. Missing source/membership is denial. Ordinary authorized summary edits change content generation but do not advance the availability generation.
- **Producer coverage:** integrate direct/archive-tree, automatic archive, purge and relevant scope/grant-loss repositories, not only a delayed event subscriber. Use exact current scope and a consistent lock order. Membership-loss paths must invalidate the affected grant even if implementation ever retains/reuses a membership row instead of replacing its ID.
- **Work:** restore/eligibility-gain dispatch enrolls currently authorized evidence again; pending/draft reuse is bound to availability identity as well as content generation. This is small body-free authority metadata, not a new model-visible peer state or historical body archive.
- **Rollback:** old code cannot prove availability continuity during its interval. On new-code reactivation, invalidate retained consolidation revisions/drafts and reset their unpublished progress before rebuilding from canonical currently authorized sources, even when body hashes are unchanged. Preserve source/Saved data.
- **Alternative rejected:** rely only on current access and lazy invalidation on the next read. It can miss a revoke/restore interval and contradict D6's clean-rebuild rule. Eager rewriting of every aggregate body is unnecessary.
- **Verification:** revoke/restore entirely between two reads, membership removal/recreation, ordinary content changes, purge and rollback/reactivation must have distinct outcomes. This refines an existing privacy outcome rather than changing source-retention or foreground permissions.

### Direct-review completion note — 2026-10-02 UTC

The direct review finalized D13 and the corresponding Design revision 2. Work-enrollment identity for restore/eligibility changes includes the current availability/grant identity as well as content generation, so unchanged content cannot be incorrectly deduplicated against work completed before revocation.

Effective current contract: [primary Design revision 2](../design/memory-261002-consolidated-history.md), mechanisms M1–M15. Earlier proposal/hold/Autonomous-owner entries remain chronological history; the ownership correction above governs. The primary Agent completed document, authority and feasibility review directly. Requester approval of the complete Design and implementation authorization remain separate and are not fabricated.

### Implementation approval — 2026-10-02 at 21:25:10 UTC

After receiving the complete Design revision 2 and direct-review report, the requester directed implementation. This approves revision 2 and the exact M1–M15 authority set as the implementation baseline. The primary Agent owns implementation and integrated validation directly; an independent read-only code reviewer supplies review evidence, not design authority. No GitHub merge or live production deployment is authorized. Older pending-approval statements above are chronological history.
