---
title: "Catalog Capability Correction Audit and Verification"
created: 2026-10-03
tags: [model-catalog, backend, engine, testing, pricing]
document_role: supporting
document_type: supporting-verification
---

# Catalog Capability Correction Audit and Verification

## Scope and authority

The requester instructed a ChatGPT web-search hotfix followed by a comprehensive
omission investigation and corrective stacked PRs. This repairs the approved
[capability-261002 Requirements](../requirements/capability-261002-evidence-backed-model-support.md),
[ADR D1–D3](../adr/capability-261002-evidence-backed-model-support.md) and
[Design revision 2](capability-261002-evidence-backed-model-support.md), without
rewriting the implemented snapshot. Design delta: None.

- Initial correction baseline: `a500f759427da66c1795e1c160d63783bf6dd0ec`.
- Historical comparison: `5710489a4^` = `602b1720e4cc707d4326113273fa7349b7bbbd0b`.
- Phase 1: [PR #2072](https://github.com/azents/azents/pull/2072), `5a9195352`.
- Phase 2: grounded producer/consumer/accounting omissions and current Specs.
- Phase 3: separately identified existing top-k carrier and SDK sampling-policy
  losses. This preserves an existing API setting, not new UI/model facts.

Root owns all repository edits and integrated verification. Three read-only audit
lanes provide independent evidence, not final approval of a moving implementation.
The single correction-stack reviewer is `/root/catalog-metadata-reviewer`.

## Complete bounded coverage

Coverage means inspected ownership, field and call propagation plus targeted
synthetic tests. It does not mean every live account/model combination was called.

### Provider and field matrix

All ten providers were enumerated: OpenAI, Anthropic, Google Gemini, AWS Bedrock,
Google Vertex AI, ChatGPT OAuth, xAI API key, xAI OAuth, Kimi OAuth and OpenRouter.
Vertex Google/Anthropic and Bedrock family/opaque-resource branches were separately
checked. The inventory compares literal source identity, account/region/project
visibility, and each final replacement producer against approved intent.

Each route was checked for default/input/output limits; reasoning support, effort
sets/completeness/defaults/summaries; function, parallel and strict tool support;
structured responses; all five normalized parameter flags; input/output modalities;
provider-hosted/client built-ins; execution options; presence/null/false/empty
precedence; candidate serialization and final publication-facing entry JSON.

The provider audit identified five grounded gaps listed below. Deliberate unknown
ChatGPT/Kimi generic function facts remain unknown. Stock enum/profile defaults do
not create efforts or model facts. Unadopted source `supports_image_generation`
remains an opaque extension: the Google repair uses the already adopted explicit
output-modality receipt and implemented GenerateContent boundary. ChatGPT strict
SDK serialization alone does not establish Codex endpoint support. An xAI preset
id/value conflict is a qualified watchpoint, not a proven live regression.

### Consumer matrix

The consumer audit inspected 30 Python declaration/consumer paths, 10 frontend
consumer/schema paths, and 67 context/pricing references across 17 capture roots.
It covered semantic validation, all native/Pydantic dialects, codec assembly,
Agent/Workspace saves and public serialization, Session/default/fallback profiles,
candidate chains, subagent guidance/inheritance, external model editors and
frontend effective-support helpers. No additional saved/API object loss or exact
context-capture defect was established. Existing source captures remain operation-
local and do not reinterpret saved authorization.

### Source, pricing and persistence matrix

M1/M7–M13 were checked across active collection, bounded typed ingress, last-good
retention, tariff normalization/evaluation, quantity accounting, operation capture,
refresh ownership, atomic publication, writer guards, migration and historical
reads. The saved public document decoded to 4,451 records and 134 namespaces.
Consumed price fields were retained as supported or explicit unsupported evidence:
50 unsupported field kinds, zero invalid consumed price kinds. This is evidence
about that saved input, not a promise of live provider/dataset completeness.

No additional concrete defect was established in source retention, supported
price-rule interpretation, capture, generation/attempt publication, SQL pointer
fences or saved/historical read preservation. Unsupported tiers/quantities/aliases
and historical fallback prices were classified as intentional exclusions.

## Findings and corrective boundaries

| ID | Grounded omission | Correction |
| --- | --- | --- |
| G0 | ChatGPT route web support disappears between listing and final v2 entry | Preserve reviewed route-derived support on absent account evidence; retain typed denial/null and exact provider isolation. Phase 1. |
| G1 | Responses source mode disables reviewed client image policy | Admit the existing conversation mode in the existing executor policy; keep explicit denial, registry and nonconversation bounds. |
| G2 | Sparse Google scalar codec domain incorrectly becomes an empty effort set | Use its documented representable levels/floor only to bound supplied exact model facts; no source evidence still means no advertised levels. |
| G3 | Unknown function support erases explicit parallel/strict positives | Capture refinements conditionally on actual functions; do not invent generic function support or weaken a known denial. |
| G4 | Adopted Google IMAGE output is disconnected from tool/codec authorization | Carry the same implemented native output/tool fact and explicit false/null through saved codec flags and actual generation config; no model-name fallback. |
| G5 | xAI disabled effort controls lose to contradictory presets/defaults | Preserve the control denial, complete empty efforts and no selected default; retain bounded conflict diagnostics. |
| C1 | Compatible SDK reasoning policy strips accepted temperature/top-p | Preserve validated v2 values through the public SDK body seam on xAI/xAI OAuth/OpenRouter/Kimi only, retaining actual reasoning and body precedence. |
| C2 | Native omitted parallel option does not carry saved denial | Emit false only when the saved actual context denies it; supported/unknown omission and explicit accepted options remain unchanged. |
| C3 | Effective SDK body scalar/format overrides escape or contradict support validation | Decode the effective typed envelope with body presence/null precedence and preserve existing explicit-effort conflict rejection. |
| C4 | Conditional effort semantics disappear at flat-list preparation guards | Use known effort configuration potential across preparation/membership/views, preserve flat snapshots and historical guards, enforce actual predicates at dispatch. No current production conditional-reasoning producer was identified. |
| S1 | Google native modality receipts are retained but billed as ordinary tokens | Decode bounded directed partitions, preserve inclusive reasoning/cache accounting, and leave uncertain/unadopted whole totals unavailable. |
| S2 | Native SDK version omitted and ChatGPT provenance mislabels its codec | Include applicable installed dependencies in fingerprints/diagnostics; native Pydantic version remains null. No dependency supplies model facts. |
| T1 | Existing top-k API intent disappears before lowerers | Separate phase 3 carries existing intent to verified SDK mappings; missing actual mapping fails rather than guessing. Related stock sampling-policy loss is addressed at the same saved-codec boundary. |

No accepted source/identity/estimator authority is restored from old code wholesale.
No new provider, permission, source, public unknown-state control, schema migration,
model substitution, request-time metadata fetch or automatic saved-selection repair
is introduced.

## Root verification checkpoints

### Phase 1

- Actual account listing -> candidate JSON -> final replacement entry reproduced
  web loss in all four source scenarios before the correction.
- 408 focused adapter/projection/configuration/profile/EngineAdapter/native tests
  passed; whole backend 8,247 passed, 3 skipped.
- Actual official SDK MockTransport sends search for named GPT and opaque account
  IDs from a final serialized entry. This proves encoding/authorization, not live
  Codex acceptance.
- Whole backend Ruff/format/ty, docs validation and diff check passed.
- Independent phase reviewer cleared material findings; separate independent
  275-suite cases and 16 conflict/JSON/configuration/runtime combinations passed.

### Phase 2 validation

- Final pre-rebase whole backend: 8,362 passed, 3 skipped. The 29 warnings include
  existing dependency/security-fixture warnings and JUnit `record_property`
  compatibility warnings. This rerun includes summary-envelope, scalar-wire,
  conflict diagnostics and the three independent-review boundary corrections.
- Fresh branch-content-matched deployed required-suite per-prompt and
  model-selection E2E: 29 passed, four existing warnings, 133.41 seconds.
  The representative system projection
  test covers real picker, Workspace -> Agent selection, refresh, exact dispatch,
  current captured price and saved-selection non-mutation.
- Directed Google normalizer probe reproduces baseline 1.1 USD versus complete
  3.5 USD; a connection test also partitions inclusive thoughts separately.
- Focused suites cover presence/null/false/empty, exact scope, positive/negative
  image and function facts, all compatible SDK sampling variants, actual Google
  image/scalar SDK JSON, body controls, conditional efforts, directed media/cache
  receipts and valid native-charge precedence.
- Google cache review regressions check raw/normalized disagreement, normalized
  cache without a media partition, missing raw cache totals with a complete typed
  receipt, and valid native snake-case detail lists. Package metadata collection
  occurs before the candidate database transaction.
- Whole backend Ruff/format/ty, docs validation and diff checks passed. The same
  independent reviewer cleared all three material boundary findings with 77
  independent tests and an actual candidate-preparation transaction probe.
  The conflict-free main rebase preserved both phase-2 commits exactly in
  `git range-diff`. Post-rebase whole backend passed 8,678 tests with 3 skips
  (94 existing/JUnit fixture warnings), and fresh required deployed E2E passed
  29 tests in 134.52 seconds. Whole Ruff/format/ty and docs/diff checks passed
  again. Full-stack CI is checked after all correction PRs exist.

Commands use `uv run --frozen pytest` and whole Ruff/format/ty under
`python/apps/azents`. Deployed tests use `AZENTS_E2E_IMAGE_BUILD_PROFILE=required`
under `testenv/azents/e2e`; synthetic local provider fixtures require no live
credentials. Root command output, JUnit and build evidence are preserved in the
Session under `catalog-hotfix-*`, `catalog-omissions-*` and
`catalog-corrections-e2e*`.

## Evidence and limitations

Independent Session reports: `catalog-provider-omissions-audit.md`,
`catalog-consumer-omissions-audit.md`, `catalog-source-pricing-persistence-audit.md`
and `catalog-top-k-execution-discovery.md`. They include exact baseline anchors,
full field/path ledgers and synthetic proof artifacts. Audit test counts are not
reclassified as root reruns or independent review of the final diff.

Live provider acceptance, account-specific availability and every dynamic
condition combination are not certified. Static coverage and targeted SDK packets
are explicit evidence boundaries. Any remaining review finding or failed final CI
must be resolved before completion is reported.

## Release boundary

No merge, production catalog refresh, database migration, producer drain, deployment
or rollback has been performed. Corrections become available through ordinary
catalog refresh after an authorized release. Existing saved Agent/Workspace
capabilities and recorded costs are not silently rewritten; changed capabilities
are adopted through explicit reselection. The original source fence/backup/rollback
procedure remains unchanged. Final phase 3 removes temporary execution plans after
validated implementation and Spec promotion.
