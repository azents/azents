---
title: "Model Capability Support Validation"
created: 2026-10-04
tags: [backend, engine, frontend, model-catalog, reliability, testing]
document_role: supporting
document_type: supporting-validation
---

# Model Capability Support Validation

This report validates [capabilities-261004](capabilities-261004-complete-support-contract.md). It separates deterministic code checks, source/producer evidence, exact local stored-choice adoption and scoped provider acceptance. It does not claim universal provider/account conformance.

## Contract and Replacement Coverage

- Final schema-3 boolean/list fields are the only supported-feature authority. Membership is supported; absence is unsupported. Original declaration absence/null and source coverage remain diagnostic evidence.
- Provider declarations, exact source facts, route representability and physical request settings have separate owners.
- Current authorized exact local metadata supplies active reads and NEW operation captures. Agent/Workspace settings and exact model identities/order remain unchanged by reads.
- New foreground, compaction, title and historical-memory operations use the same compiler. Existing operations, retries, quota progression and historical provenance remain frozen.
- Web and private Slack/Discord model controls use compiled option views. Existing external mutation replay/already-applied drafts return before current metadata capture.
- New public input, Team/User root creation, message edit and web profile replacement validate the same exact current support before admission. Capture and pure compilation finish outside the write transaction; the final phase repeats authorization and replay checks and fences raw configuration, intent and local metadata before mutation.
- Actual request admission includes custom client tools, synthetic output tools, strict schemas, native response format, sampling and provider-specific reasoning overrides. Only genuine omission can use a captured known default.
- Google effort domains are lossless codec intersections. Budget-only models do not acquire invented scalar levels; explicit budgets/adaptive/disabled settings retain their form.
- Kimi coding function support and exact Grok 4.7 web support have reviewed route/model contracts. Kimi scalar effort controls remain excluded until their Chat encoder is implemented. Their raw reasoning facts remain retained.

## Deterministic Validation

Executed from the backend Python application:

```console
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run ty check --error-on-warning
```

The pre-synchronization backend run passed **9,974 tests**, with **3 skips** and **7 existing warning categories**, in 336.43 seconds. It includes disposable PostgreSQL and Redis fixtures rather than production databases. The skips are not counted as successful provider acceptance. Ruff, formatting and whole-backend typing passed.

After main synchronization and the public-admission corrections, [CI run 37188124993](https://github.com/azents/azents/actions/runs/37188124993) passed **10,159 backend tests**, with **3 skips**, in 460.21 seconds. Backend lint, formatting, typing and OpenAPI drift checks also passed. The public-admission focused set passed **51 tests** and the deterministic-fixture set passed **21 tests**; these overlap the full suite and are not added to its total.

Actual product E2E exposed two gaps that unit-only validation had not covered: synthetic catalogs published final flags without replayable raw declarations, and public ingress validated raw saved support instead of active metadata. Both were corrected without changing the binary gate, saved configuration or pricing. Deterministic fixtures now publish explicit typed declarations through the ordinary compiler. The representative source-refresh E2E verifies new-request rejection after support disappears and unchanged captured prices until explicit reselection. A remaining title-retry mock response was aligned with its plain-text request envelope. Complete E2E delivery results are recorded on [PR #2113](https://github.com/azents/azents/pull/2113), separately from provider/account acceptance.

The repository tests cover actual legacy v2 Agent/Workspace JSON, safe orphan-refinement decoding, exact scope/source matching, prewrite drift, compile-before-normalization, metadata-only drift without reprepare loops, immutable operation reuse, quota progression, unrelated configuration PATCH preservation and private-control replay/authorization boundaries.

Executed from the TypeScript workspace:

```console
pnpm run typecheck --filter=@azents/web --filter=@azents/admin-web
pnpm run lint --filter=@azents/web --filter=@azents/admin-web
pnpm run build --filter=@azents/web --filter=@azents/admin-web
pnpm --filter @azents/web test
```

Both application type checks, lint checks and builds passed. The web unit suite passed **356 tests**, with no failures or skips. OpenAPI and public/admin Python/TypeScript clients were regenerated; generated files were not hand-edited.

Documentation frontmatter validation and the documentation catalog's **18 unit tests** passed. Living Specs were synchronized with the final authority and lifecycle boundaries.

## Independent Review

Independent read-only review closed the material findings found during integration:

- Custom client tools bypassing function admission.
- Vertex lowering using a different protocol from its physical model factory.
- Explicit null/conflicting Grok defaults being replaced with high.
- Valid historical v2 orphan refinements failing before active recompilation.
- Shared SDK strict switches losing native strict schemas or inventing strict functions.
- Bedrock synthetic output translation bypassing JSON text reconstruction.
- Google unsupported/snap-only canonical levels being advertised.
- Missing documented Kimi function and exact Grok web support.
- Public admission using raw saved support, including write-free two-phase capture, repeated authorization, prewrite source/configuration fences and idempotent replay before metadata validation.

The reviewer independently exercised declaration/source precedence, exact provider/model boundaries, seven dispatch encodings rejecting ultra, SDK wire serialization and stored operation/capture boundaries. Focused review counts overlap the full suite and are deliberately not added to the full-suite total.

## Exact Account Declarations

A read-only query of the configured ChatGPT OAuth account's existing Codex model-list route returned HTTP 200 and ten entries. Four selected models were compared independently before final output comparison:

| Exact model | Raw efforts | Final selectable efforts | Captured default | Default / maximum input |
| --- | --- | --- | --- | --- |
| `gpt-6-astra` | low, medium, high, xhigh, max, ultra | low, medium, high, xhigh, max | medium | 272,000 / 872,000 |
| `gpt-6.1-sol` | low, medium, high, xhigh, max, ultra | low, medium, high, xhigh, max | low | 272,000 / 872,000 |
| `gpt-5.6-terra` | low, medium, high, xhigh, max, ultra | low, medium, high, xhigh, max | medium | 272,000 / 872,000 |
| `gpt-5.6-luna` | low, medium, high, xhigh, max | low, medium, high, xhigh, max | medium | 272,000 / 872,000 |

Text/image input, parallel function calls and reasoning summary declarations agree with the compiled results. The current summary-parameter declaration is distinguished from namespace tool discovery and hosted web search. Numeric account defaults are not replaced with standalone public API model defaults.

Ultra handling follows the requested pre-Pydantic behavior. The parent of inference cutover commit `f4c696449` retained the original preset array but excluded ultra from its seven-value canonical enum; its listing fixture explicitly expected five normalized values from the six-value provider array. No alias to max or literal ultra dispatch is added.

Official Codex source also separates the local ultra selection from ordinary inference effort and proactive multi-agent policy. Producer reference: [model-owned effort normalization](https://github.com/openai/codex/blob/530383e36de9c74cd79177a0c31d35609019134f/codex-rs/protocol/src/openai_models/reasoning_effort.rs).

## Scoped Provider Acceptance

Using the configured credentials without refreshing or printing them, bounded synthetic requests on the existing ChatGPT OAuth inference route verified:

- `gpt-6-astra`: strict function call and native strict JSON-schema output.
- `gpt-6.1-sol`: strict function call and native strict JSON-schema output.

Each schema contained a fresh synthetic nonce. Structured-output requests asked for plain text, while the result conformed to the schema nonce JSON. The four completed requests used 99, 79, 95 and 94 total tokens respectively. A separate Sol request accepted `max_output_tokens=32`.

Some Codex completion envelopes have an empty output array after earlier typed `response.output_item.done` events supplied the result. The corrected diagnostic collected those events alongside terminal completion proof, matching the product's normal stream boundary. Earlier completion-array-only observations were not treated as unsupported features or successful conformance.

Previously recorded scoped Grok 4.7 OAuth diagnostics verified an image in a function result, forced strict function emission, strict JSON-schema output and reasoning-summary output on the actual API inference endpoint. These are exact-route acceptance receipts, not proof for every xAI model/account.

All probes used synthetic inputs, performed no application database writes or catalog refresh, and used `store=false` where applicable. They do not constitute deployment or verification of a newly deployed Agent UI.

## Stored-Choice Adoption

A separate coherent, read-only database capture retained the current exact catalog/source inputs of five configured choices. Offline compilation and detached read projection passed **134 comparisons and 6 preservation controls**:

- Astra/Sol/Grok previously stored function=false becomes supported from the same identity's current declarations and reviewed route contracts.
- Terra/Luna previously stored function=true remains true.
- Exact local ChatGPT source rows legitimately supplement Terra/Luna's 128,000 output ceiling and native structured-response support; their strict-function support is not inferred from response schemas.
- The account's 872,000 maximum input wins over a larger source-registry maximum.
- Original captured input bytes, exact model order and captured settings hashes remain unchanged.

The capture did not retain actual user setting bytes. Representative typed option settings were separately checked for equality; this is not reported as a live UI call or production settings write.

## Evidence Scope and Remaining Live Gaps

All ten provider routes and all 24 canonical declaration fields have a recorded disposition. Current-account inventory/source captures for the other eight routes were unavailable in this round. Official exact references and codec serialization were reviewed where available, but their live/account-specific acceptance is not counted as passed.

Model/auth-route support potential is distinct from dynamic entitlement and account visibility. The scoped ChatGPT schema receipts are combined with the official Codex producer's common output-schema contract, not generalized as live acceptance for every account or schema subset:

- [CLI output schema option](https://github.com/openai/codex/blob/530383e36de9c74cd79177a0c31d35609019134f/codex-rs/exec/src/cli.rs)
- [Common Responses request construction](https://github.com/openai/codex/blob/530383e36de9c74cd79177a0c31d35609019134f/codex-rs/core/src/client.rs)
- [Strict output schema controls](https://github.com/openai/codex/blob/530383e36de9c74cd79177a0c31d35609019134f/codex-rs/codex-api/src/common.rs)

Kimi's managed coding function contract is grounded in [current coding model documentation](https://www.kimi.com/code/docs/en/kimi-code/models.html#third-party-tools), the [official Codex integration guide](https://www.kimi.com/code/docs/en/third-party-tools/codex.html#using-kimi-in-codex), and the pinned official CLI's [common Chat tool request path](https://github.com/MoonshotAI/kimi-cli/blob/9ab1286b8fe4e6bcd116949a27ce5e0ac3389c82/packages/kosong/src/kosong/chat_provider/kimi.py). This round did not live-test Kimi credentials or canonical efforts.

The exact Grok 4.7 hosted web contract is grounded in its [model reference](https://docs.x.ai/developers/grok-4-7.md) and [Responses web-search example](https://docs.x.ai/developers/tools/web-search.md). Hosted web dispatch, simultaneous multi-call generation, other accounts and all schema subsets are not claimed as live-tested here.

## Operational Boundary

This change includes no production mutation, catalog refresh, credential rotation, relational migration or deployment. The new application publication guard rejects obsolete raw capability/compiler payloads; it does not fence an already running old binary at the database layer. Any separately authorized rollout must drain incompatible old active work and avoid mixed-binary continuation rather than rewriting frozen operations.
