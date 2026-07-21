---
title: "Legacy DocID Migration Historical Ambiguity Manifest"
created: 2026-07-21
tags: [documentation, migration, historical-reconstruction]
document_role: supporting
document_type: ambiguity-manifest
historical_reconstruction: true
---

# Legacy DocID Migration Historical Ambiguity Manifest

> This supporting manifest records legacy numeric references whose source ADR cannot be inferred safely.
> It is not a product decision record. Each row preserves the exact source location and candidate files.

- Historical cutoff: Tuesday, July 21, 2026 (KST)
- Total ambiguous occurrences: 118
- Resolution policy: no lexical or numeric guessing; retain this precise anchor until a source owner resolves it.

## Entries

<a id="ambiguity-ref-45"></a>
### ambiguity-ref-45

- Source file: `docs/azents/adr/0087-filesystem-skill-projection-revisions.md`
- Source line: `16`
- Legacy token: `ADR-0086`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `ADR-0086 reserves the chat input/action-message shape for a future Skill Turn Action:`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-46"></a>
### ambiguity-ref-46

- Source file: `docs/azents/adr/0087-filesystem-skill-projection-revisions.md`
- Source line: `104`
- Legacy token: `ADR-0086`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `- \`ActionMessagePayload\` and a reserved \`SkillAction\` variant from ADR-0086.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-47"></a>
### ambiguity-ref-47

- Source file: `docs/azents/adr/0087-filesystem-skill-projection-revisions.md`
- Source line: `337`
- Legacy token: `ADR-0086`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Skill actions should be exposed through the session-scoped action listing introduced by ADR-0086.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-58"></a>
### ambiguity-ref-58

- Source file: `docs/azents/adr/0089-workspace-project-browser-surface.md`
- Source line: `13`
- Legacy token: `ADR-0086`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `ADR-0076 made Project registrations session-owned. ADR-0086 made new-session Project selection explicit: the selected Project chips are the exact \`project_paths\` used to create the new \`AgentSession\`, and session creation no longer copies hidden Projects from the team-primary session.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-59"></a>
### ambiguity-ref-59

- Source file: `docs/azents/adr/0093-new-session-mixed-workspace-selection.md`
- Source line: `11`
- Legacy token: `ADR-0086`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `ADR-0086 established explicit new-session Project selection: the selected Project UI equals the`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-73"></a>
### ambiguity-ref-73

- Source file: `docs/azents/adr/0142-persist-turn-usage-inference-provenance.md`
- Source line: `13`
- Legacy token: `ADR-0124`
- Candidate ADR files: `0124-keep-inference-provenance-run-owned.md`, `0124-subagent-spawn-inference-profile-overrides.md`
- Source text: `ADR-0124 keeps resolved inference provenance owned by AgentRun and rejects mutating or republishing user-message history events as Run state changes. That decision correctly protects append-only transcript ordering, but it leaves immutable per-turn usage facts without the inference snapshot needed to interpret them later.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-74"></a>
### ambiguity-ref-74

- Source file: `docs/azents/adr/0142-persist-turn-usage-inference-provenance.md`
- Source line: `31`
- Legacy token: `ADR-0124`
- Candidate ADR files: `0124-keep-inference-provenance-run-owned.md`, `0124-subagent-spawn-inference-profile-overrides.md`
- Source text: `This decision narrows ADR-0124 only for immutable per-turn usage facts. AgentRun remains the owner of mutable run lifecycle and full internal resolved provenance. User-message events remain free of mutable Run summaries and are not republished.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-75"></a>
### ambiguity-ref-75

- Source file: `docs/azents/adr/0142-persist-turn-usage-inference-provenance.md`
- Source line: `49`
- Legacy token: `ADR-0124`
- Candidate ADR files: `0124-keep-inference-provenance-run-owned.md`, `0124-subagent-spawn-inference-profile-overrides.md`
- Source text: `Rejected. Usage belongs to a model turn, and reintroducing event-to-Run mutation would repeat the ordering and duplication problems superseded by ADR-0124.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-103"></a>
### ambiguity-ref-103

- Source file: `docs/azents/adr/0148-define-openai-http-migration-by-semantic-parity.md`
- Source line: `15`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `ADR-0147 establishes an OpenAI-native Responses transport family and requires migrating OpenAI HTTP calls to the official SDK before introducing WebSocket transport. A migration completion contract is needed because the current LiteLLM and future OpenAI SDK paths do not produce byte-identical wire requests or response objects.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-104"></a>
### ambiguity-ref-104

- Source file: `docs/azents/adr/0149-use-litellm-only-as-openai-cost-calculator.md`
- Source line: `15`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `ADR-0147 replaces LiteLLM with the official OpenAI SDK as the request and transport owner for \`LLMProvider.OPENAI\`. ADR-0148 requires semantic parity for usage provenance and \`cost_usd\`, but direct OpenAI SDK responses do not contain LiteLLM's private \`_hidden_params.response_cost\` value used by the current adapter.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-105"></a>
### ambiguity-ref-105

- Source file: `docs/azents/adr/0150-openai-responses-websocket-lifecycle.md`
- Source line: `16`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `ADR-0147 established an OpenAI-native Responses transport family in which HTTP and WebSocket consume the same complete logical request and SDK HTTP is the physical fallback. The HTTP phase is now implemented for OpenAI API-key and ChatGPT OAuth sampling, compaction, and automatic Session title generation. ADR-0162 also removed the Responses Lite dialect and standardized ChatGPT OAuth on the normal Responses request contract.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-106"></a>
### ambiguity-ref-106

- Source file: `docs/azents/adr/0151-use-generic-native-adapter-request-types.md`
- Source line: `24`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `ADR-0147 introduces an OpenAI-native Responses transport family, and ADR-0148 requires semantic request parity across primary sampling, compaction, and automatic Session title generation. Reusing the untyped request bag would make the OpenAI HTTP and later WebSocket transports depend on implicit dictionary conventions rather than one enforceable request contract.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-107"></a>
### ambiguity-ref-107

- Source file: `docs/azents/adr/0152-include-chatgpt-oauth-in-openai-native-http-migration.md`
- Source line: `15`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `ADR-0147 and ADR-0148 scoped the first OpenAI-native HTTP migration to \`LLMProvider.OPENAI\` and retained \`LLMProvider.CHATGPT_OAUTH\` on LiteLLM HTTP. That scope does not match the intended migration boundary.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-108"></a>
### ambiguity-ref-108

- Source file: `docs/azents/adr/0152-include-chatgpt-oauth-in-openai-native-http-migration.md`
- Source line: `32`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `This decision supersedes only the ChatGPT OAuth exclusions in ADR-0147 and ADR-0148. Their HTTP-first sequencing, semantic-parity contract, and later WebSocket deferral remain unchanged.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-109"></a>
### ambiguity-ref-109

- Source file: `docs/azents/adr/0165-make-model-provider-failures-transparent.md`
- Source line: `125`
- Legacy token: `ADR-0145`
- Candidate ADR files: `0145-model-scoped-selectable-model-settings.md`, `0145-require-explicit-responses-stream-completion.md`, `0145-scope-failed-run-retry-to-model-turn.md`
- Source text: `ADR-0145 remains authoritative for explicit Responses terminal completion and model-turn-scoped durable retry state. This ADR extends that retry lifecycle to preserve typed provider failures consistently across supported adapters and automatic context preparation.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-139"></a>
### ambiguity-ref-139

- Source file: `docs/azents/adr/0170-project-subscription-usage-from-selected-model.md`
- Source line: `15`
- Legacy token: `ADR-0169`
- Candidate ADR files: `0169-add-openrouter-as-an-integration-scoped-llm-provider.md`, `0169-integration-scoped-subscription-usage.md`
- Source text: `ADR-0169 established integration-scoped live subscription usage and made each Workspace LLM Settings integration card the canonical management surface. That placement keeps credentials, enabled state, aliases, financial details, and provider usage together, but it requires users to leave an active Agent session to inspect the quota that can affect their next request.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-140"></a>
### ambiguity-ref-140

- Source file: `docs/azents/adr/0170-project-subscription-usage-from-selected-model.md`
- Source line: `114`
- Legacy token: `ADR-0169`
- Candidate ADR files: `0169-add-openrouter-as-an-integration-scoped-llm-provider.md`, `0169-integration-scoped-subscription-usage.md`
- Source text: `- ADR-0169 remains authoritative for integration-scoped usage, provider adapters, permissions, and the canonical LLM Settings surface. This ADR extends ADR-0169-D6 with a contextual session projection.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-141"></a>
### ambiguity-ref-141

- Source file: `docs/azents/adr/0170-project-subscription-usage-from-selected-model.md`
- Source line: `114`
- Legacy token: `ADR-0169-D6`
- Candidate ADR files: `0169-add-openrouter-as-an-integration-scoped-llm-provider.md`, `0169-integration-scoped-subscription-usage.md`
- Source text: `- ADR-0169 remains authoritative for integration-scoped usage, provider adapters, permissions, and the canonical LLM Settings surface. This ADR extends ADR-0169-D6 with a contextual session projection.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-152"></a>
### ambiguity-ref-152

- Source file: `docs/azents/adr/0171-add-kimi-subscription-as-an-integration-scoped-provider.md`
- Source line: `119`
- Legacy token: `ADR-0169`
- Candidate ADR files: `0169-add-openrouter-as-an-integration-scoped-llm-provider.md`, `0169-integration-scoped-subscription-usage.md`
- Source text: `- ADR-0169 remains authoritative for integration-scoped subscription usage.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-155"></a>
### ambiguity-ref-155

- Source file: `docs/azents/adr/0171-archived-session-retention-and-purge.md`
- Source line: `23`
- Legacy token: `ADR-0168-D1`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `### ADR-0168-D1. Archived sessions use an admin-managed retention deadline`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-156"></a>
### ambiguity-ref-156

- Source file: `docs/azents/adr/0171-archived-session-retention-and-purge.md`
- Source line: `29`
- Legacy token: `ADR-0168-D2`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `### ADR-0168-D2. Archive snapshots the deadline and administrators choose change scope`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-157"></a>
### ambiguity-ref-157

- Source file: `docs/azents/adr/0171-archived-session-retention-and-purge.md`
- Source line: `44`
- Legacy token: `ADR-0168-D3`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `### ADR-0168-D3. Archive remains reversible until purge starts`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-158"></a>
### ambiguity-ref-158

- Source file: `docs/azents/adr/0171-archived-session-retention-and-purge.md`
- Source line: `52`
- Legacy token: `ADR-0168-D4`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `### ADR-0168-D4. The root SessionAgent tree is one retention unit`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-159"></a>
### ambiguity-ref-159

- Source file: `docs/azents/adr/0171-archived-session-retention-and-purge.md`
- Source line: `60`
- Legacy token: `ADR-0168-D5`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `### ADR-0168-D5. Purge is a durable scheduled workflow`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-160"></a>
### ambiguity-ref-160

- Source file: `docs/azents/adr/0171-archived-session-retention-and-purge.md`
- Source line: `68`
- Legacy token: `ADR-0168-D6`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `### ADR-0168-D6. ModelFiles are deleted during purge`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-161"></a>
### ambiguity-ref-161

- Source file: `docs/azents/adr/0171-archived-session-retention-and-purge.md`
- Source line: `74`
- Legacy token: `ADR-0168-D7`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `### ADR-0168-D7. Artifacts are deleted during purge`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-162"></a>
### ambiguity-ref-162

- Source file: `docs/azents/adr/0171-archived-session-retention-and-purge.md`
- Source line: `80`
- Legacy token: `ADR-0168-D8`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `### ADR-0168-D8. ExchangeFiles gain a root-session retention owner`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-163"></a>
### ambiguity-ref-163

- Source file: `docs/azents/adr/0171-archived-session-retention-and-purge.md`
- Source line: `86`
- Legacy token: `ADR-0168-D9`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `### ADR-0168-D9. Worktree cleanup moves from archive to purge`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-164"></a>
### ambiguity-ref-164

- Source file: `docs/azents/adr/0171-archived-session-retention-and-purge.md`
- Source line: `92`
- Legacy token: `ADR-0168-D10`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `### ADR-0168-D10. Archived sessions cannot resume execution`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-185"></a>
### ambiguity-ref-185

- Source file: `docs/azents/adr/0172-reset-tool-search-working-set-on-compaction.md`
- Source line: `10`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `ADR-0147 established a session-scoped Tool Search working set that survives context compaction. That policy preserves capability recency across the entire AgentSession, but compaction is also the explicit boundary where Azents replaces the model-visible conversation history with a new durable checkpoint.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-186"></a>
### ambiguity-ref-186

- Source file: `docs/azents/adr/0172-reset-tool-search-working-set-on-compaction.md`
- Source line: `61`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `This ADR supersedes only the ADR-0147 statement that Tool Search working-set recency survives compaction. All other ADR-0147 decisions remain in effect.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-187"></a>
### ambiguity-ref-187

- Source file: `docs/azents/adr/0172-reset-tool-search-working-set-on-compaction.md`
- Source line: `61`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `This ADR supersedes only the ADR-0147 statement that Tool Search working-set recency survives compaction. All other ADR-0147 decisions remain in effect.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-192"></a>
### ambiguity-ref-192

- Source file: `docs/azents/adr/0175-retire-legacy-platform-github-bindings.md`
- Source line: `7`
- Legacy token: `ADR-0174`
- Candidate ADR files: `0174-present-chat-activity-as-an-ordered-event-stream.md`, `0174-session-shared-unread-run-result-state.md`
- Source text: `# ADR-0174: Retire Legacy Platform GitHub App Bindings`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-193"></a>
### ambiguity-ref-193

- Source file: `docs/azents/adr/0175-retire-legacy-platform-github-bindings.md`
- Source line: `11`
- Legacy token: `ADR-0172`
- Candidate ADR files: `0172-generalize-admin-managed-system-configuration.md`, `0172-gpt-apply-patch-alongside-existing-edit.md`, `0172-reset-tool-search-working-set-on-compaction.md`
- Source text: `ADR-0172 introduced nullable Platform GitHub App identity bindings so an installation that existed before identity binding could be claimed or reconnected safely. That transition state added nullable installation rows, nullable encrypted Toolkit credential fields, Admin claim-or-leave decisions, Public reconnect reasons, and Main Web guidance.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-194"></a>
### ambiguity-ref-194

- Source file: `docs/azents/adr/0176-render-known-tools-through-validated-frontend-adapters.md`
- Source line: `11`
- Legacy token: `ADR-0174`
- Candidate ADR files: `0174-present-chat-activity-as-an-ordered-event-stream.md`, `0174-session-shared-unread-run-result-state.md`
- Source text: `ADR-0173 established Generic tool rendering as the permanent compatibility boundary and allowed specialized presentation only for registered tool identities whose payloads validate. ADR-0174 retained that boundary while deferring individual tool detail designs.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-195"></a>
### ambiguity-ref-195

- Source file: `docs/azents/adr/0178-enable-tool-search-by-default.md`
- Source line: `10`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `ADR-0147 introduced Tool Search as an Agent-level opt-in capability with a default-disabled setting. The initial default prioritized compatibility while Azents validated deferred capability discovery, provider declaration budgets, prepared-call execution boundaries, and product-path behavior.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-196"></a>
### ambiguity-ref-196

- Source file: `docs/azents/adr/0178-enable-tool-search-by-default.md`
- Source line: `41`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `- ADR-0147's default-disabled decision is superseded; its direct/deferred classification, budget, search, and execution-boundary decisions remain in effect.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-197"></a>
### ambiguity-ref-197

- Source file: `docs/azents/adr/0179-apply-patch-provider-tool-dialects.md`
- Source line: `11`
- Legacy token: `ADR-0172`
- Candidate ADR files: `0172-generalize-admin-managed-system-configuration.md`, `0172-gpt-apply-patch-alongside-existing-edit.md`, `0172-reset-tool-search-working-set-on-compaction.md`
- Source text: `ADR-0172 introduced the model-visible \`apply_patch\` client tool as an ordinary JSON-schema function tool for OpenAI-developed GPT-family models. Its input carries an absolute Runtime \`base_path\` and one complete V4A document in the \`patch\` string. The Runtime Runner owns strict V4A parsing, path confinement, preflight, staging, optimistic revalidation, deterministic commit ordering, typed terminal results, and exact no-rollback partial-failure reporting.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-198"></a>
### ambiguity-ref-198

- Source file: `docs/azents/adr/0179-apply-patch-provider-tool-dialects.md`
- Source line: `31`
- Legacy token: `ADR-0172`
- Candidate ADR files: `0172-generalize-admin-managed-system-configuration.md`, `0172-gpt-apply-patch-alongside-existing-edit.md`, `0172-reset-tool-search-working-set-on-compaction.md`
- Source text: `This ADR does not reopen ADR-0172 decisions about:`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-199"></a>
### ambiguity-ref-199

- Source file: `docs/azents/adr/0179-apply-patch-provider-tool-dialects.md`
- Source line: `45`
- Legacy token: `ADR-0172-D1`
- Candidate ADR files: `0172-generalize-admin-managed-system-configuration.md`, `0172-gpt-apply-patch-alongside-existing-edit.md`, `0172-reset-tool-search-working-set-on-compaction.md`
- Source text: `This ADR may supersede only ADR-0172-D1 and the model/tool-transport portions of ADR-0172-D14. Existing durable function-tool calls and results remain valid history.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-200"></a>
### ambiguity-ref-200

- Source file: `docs/azents/adr/0179-apply-patch-provider-tool-dialects.md`
- Source line: `45`
- Legacy token: `ADR-0172-D14`
- Candidate ADR files: `0172-generalize-admin-managed-system-configuration.md`, `0172-gpt-apply-patch-alongside-existing-edit.md`, `0172-reset-tool-search-working-set-on-compaction.md`
- Source text: `This ADR may supersede only ADR-0172-D1 and the model/tool-transport portions of ADR-0172-D14. Existing durable function-tool calls and results remain valid history.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-201"></a>
### ambiguity-ref-201

- Source file: `docs/azents/adr/0179-apply-patch-provider-tool-dialects.md`
- Source line: `107`
- Legacy token: `ADR-0172`
- Candidate ADR files: `0172-generalize-admin-managed-system-configuration.md`, `0172-gpt-apply-patch-alongside-existing-edit.md`, `0172-reset-tool-search-working-set-on-compaction.md`
- Source text: `preserves the implemented ADR-0172 GPT-family compatibility behavior without widening it`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-202"></a>
### ambiguity-ref-202

- Source file: `docs/azents/adr/0181-suppress-unread-indicators-while-sessions-run.md`
- Source line: `11`
- Legacy token: `ADR-0174`
- Candidate ADR files: `0174-present-chat-activity-as-an-ordered-event-stream.md`, `0174-session-shared-unread-run-result-state.md`
- Source text: `ADR-0174 established a durable Session-shared unread boundary for terminal Run results. A Session can begin a newer Run before an older terminal result is reviewed, so the durable unread boundary and \`run_state = running\` can coexist.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-203"></a>
### ambiguity-ref-203

- Source file: `docs/azents/adr/0181-suppress-unread-indicators-while-sessions-run.md`
- Source line: `25`
- Legacy token: `ADR-0174`
- Candidate ADR files: `0174-present-chat-activity-as-an-ordered-event-stream.md`, `0174-session-shared-unread-run-result-state.md`
- Source text: `This supersedes only the Agent rail presentation aspect of ADR-0174. ADR-0174 remains the source of truth for durable shared unread-boundary semantics.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-204"></a>
### ambiguity-ref-204

- Source file: `docs/azents/adr/0181-suppress-unread-indicators-while-sessions-run.md`
- Source line: `25`
- Legacy token: `ADR-0174`
- Candidate ADR files: `0174-present-chat-activity-as-an-ordered-event-stream.md`, `0174-session-shared-unread-run-result-state.md`
- Source text: `This supersedes only the Agent rail presentation aspect of ADR-0174. ADR-0174 remains the source of truth for durable shared unread-boundary semantics.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-206"></a>
### ambiguity-ref-206

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `28`
- Legacy token: `ADR-0088-D1`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `Related decisions: ADR-0088-D1`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-207"></a>
### ambiguity-ref-207

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `41`
- Legacy token: `ADR-0088-D2`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `Related decisions: ADR-0088-D2`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-208"></a>
### ambiguity-ref-208

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `53`
- Legacy token: `ADR-0088-D3`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `Related decisions: ADR-0088-D3`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-209"></a>
### ambiguity-ref-209

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `66`
- Legacy token: `ADR-0088-D4`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `Related decisions: ADR-0088-D4`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-210"></a>
### ambiguity-ref-210

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `79`
- Legacy token: `ADR-0088-D5`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `Related decisions: ADR-0088-D5`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-211"></a>
### ambiguity-ref-211

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `91`
- Legacy token: `ADR-0088-D6`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `Related decisions: ADR-0088-D6`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-212"></a>
### ambiguity-ref-212

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `103`
- Legacy token: `ADR-0088-D1`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `| ADR-0088-D1 | REQ-1 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-213"></a>
### ambiguity-ref-213

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `104`
- Legacy token: `ADR-0088-D2`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `| ADR-0088-D2 | REQ-2 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-214"></a>
### ambiguity-ref-214

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `105`
- Legacy token: `ADR-0088-D3`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `| ADR-0088-D3 | REQ-3 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-215"></a>
### ambiguity-ref-215

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `106`
- Legacy token: `ADR-0088-D4`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `| ADR-0088-D4 | REQ-4 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-216"></a>
### ambiguity-ref-216

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `107`
- Legacy token: `ADR-0088-D5`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `| ADR-0088-D5 | REQ-5 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-217"></a>
### ambiguity-ref-217

- Source file: `docs/azents/design/agent-settings-pages-and-memory-ui.md`
- Source line: `108`
- Legacy token: `ADR-0088-D6`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `| ADR-0088-D6 | REQ-6 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-218"></a>
### ambiguity-ref-218

- Source file: `docs/azents/design/apply-patch-provider-tool-dialects.md`
- Source line: `22`
- Legacy token: `ADR-0172`
- Candidate ADR files: `0172-generalize-admin-managed-system-configuration.md`, `0172-gpt-apply-patch-alongside-existing-edit.md`, `0172-reset-tool-search-working-set-on-compaction.md`
- Source text: `The decisions are recorded in \[ADR-0179\](../adr/0179-apply-patch-provider-tool-dialects.md). ADR-0172 remains authoritative for V4A grammar, Runtime safety, commit, cancellation, and typed result semantics.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-219"></a>
### ambiguity-ref-219

- Source file: `docs/azents/design/apply-patch-provider-tool-dialects.md`
- Source line: `223`
- Legacy token: `ADR-0172`
- Candidate ADR files: `0172-generalize-admin-managed-system-configuration.md`, `0172-gpt-apply-patch-alongside-existing-edit.md`, `0172-reset-tool-search-working-set-on-compaction.md`
- Source text: `The initial semantic rule preserves current ADR-0172 behavior without widening it. The implementation may rename the profile from GPT-specific terminology to \`v4a_apply_patch\`, while retaining the same reviewed developer/family matching result. New model developers or families require explicit conformance evidence.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-220"></a>
### ambiguity-ref-220

- Source file: `docs/azents/design/apply-patch-provider-tool-dialects.md`
- Source line: `440`
- Legacy token: `ADR-0172`
- Candidate ADR files: `0172-generalize-admin-managed-system-configuration.md`, `0172-gpt-apply-patch-alongside-existing-edit.md`, `0172-reset-tool-search-working-set-on-compaction.md`
- Source text: `One custom \`apply_patch\` call invokes Runner at most once. Envelope parse failure invokes Runner zero times. Runner cancellation and typed terminal settlement retain ADR-0172 behavior.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-223"></a>
### ambiguity-ref-223

- Source file: `docs/azents/design/chat-known-tool-specialized-renderers.md`
- Source line: `21`
- Legacy token: `ADR-0174`
- Candidate ADR files: `0174-present-chat-activity-as-an-ordered-event-stream.md`, `0174-session-shared-unread-run-result-state.md`
- Source text: `Known tools should communicate those facts directly without weakening the permanent Generic compatibility boundary established by ADR-0173 and retained by ADR-0174.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-224"></a>
### ambiguity-ref-224

- Source file: `docs/azents/design/claude-rules-loader-validation-2026-07-02.md`
- Source line: `87`
- Legacy token: `ADR-0088`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `## Implementation vs. ADR-0088 Comparison`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-225"></a>
### ambiguity-ref-225

- Source file: `docs/azents/design/claude-rules-loader-validation-2026-07-02.md`
- Source line: `89`
- Legacy token: `ADR-0088`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `| ADR-0088 decision | Implementation status | Evidence |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-226"></a>
### ambiguity-ref-226

- Source file: `docs/azents/design/claude-rules-loader-validation-2026-07-02.md`
- Source line: `110`
- Legacy token: `ADR-0088`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `No ADR-0088 decision drift was found.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-227"></a>
### ambiguity-ref-227

- Source file: `docs/azents/design/codex-first-subagent-prerequisites-validation-2026-07-08.md`
- Source line: `36`
- Legacy token: `ADR-0086`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `| ADR-0086 / ADR-0094 | Process TurnActions at turn boundaries, not only at run-entry/run-complete boundaries. | \`python/apps/azents/src/azents/worker/run/executor.py\`, \`python/apps/azents/src/azents/engine/events/execution.py\`, \`python/apps/azents/src/azents/worker/session/runner.py\` | Model-call boundary polling now includes action-message promotion and operation-action execution. Context-invalidating actions cancel the current run without a completed run marker and enqueue a fresh wake-up; failed operation actions are marked failed and FIFO processing continues. | Implemented | #245 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-228"></a>
### ambiguity-ref-228

- Source file: `docs/azents/design/concurrent-read-latency-hardening.md`
- Source line: `199`
- Legacy token: `ADR-0088`
- Candidate ADR files: `0088-agent-settings-pages-and-memory-ui.md`, `0088-claude-rules-loader.md`
- Source text: `No ADR change is required because the design implements and hardens existing ADR-0085, ADR-0088, and ADR-0102 contracts rather than replacing them.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-230"></a>
### ambiguity-ref-230

- Source file: `docs/azents/design/gpt-apply-patch-testenv-report-2026-07-20.md`
- Source line: `69`
- Legacy token: `ADR-0172`
- Candidate ADR files: `0172-generalize-admin-managed-system-configuration.md`, `0172-gpt-apply-patch-alongside-existing-edit.md`, `0172-reset-tool-search-working-set-on-compaction.md`
- Source text: `ADR-0172 remains unchanged.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-231"></a>
### ambiguity-ref-231

- Source file: `docs/azents/design/new-session-mixed-workspace-selection.md`
- Source line: `22`
- Legacy token: `ADR-0086`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `- ADR-0086: new-session Project selection is explicit and exact;`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-232"></a>
### ambiguity-ref-232

- Source file: `docs/azents/design/new-session-mixed-workspace-selection.md`
- Source line: `358`
- Legacy token: `ADR-0086`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `- ADR-0086 already requires explicit new-session Project selection and path presets.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-233"></a>
### ambiguity-ref-233

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `23`
- Legacy token: `ADR-0086-D1`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D1, ADR-0086-D2`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-234"></a>
### ambiguity-ref-234

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `23`
- Legacy token: `ADR-0086-D2`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D1, ADR-0086-D2`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-235"></a>
### ambiguity-ref-235

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `35`
- Legacy token: `ADR-0086-D2`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D2`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-236"></a>
### ambiguity-ref-236

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `47`
- Legacy token: `ADR-0086-D3`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D3`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-237"></a>
### ambiguity-ref-237

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `59`
- Legacy token: `ADR-0086-D4`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D4, ADR-0086-D5`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-238"></a>
### ambiguity-ref-238

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `59`
- Legacy token: `ADR-0086-D5`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D4, ADR-0086-D5`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-239"></a>
### ambiguity-ref-239

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `73`
- Legacy token: `ADR-0086-D4`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D4, ADR-0086-D6`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-240"></a>
### ambiguity-ref-240

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `73`
- Legacy token: `ADR-0086-D6`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D4, ADR-0086-D6`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-241"></a>
### ambiguity-ref-241

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `85`
- Legacy token: `ADR-0086-D7`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D7`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-242"></a>
### ambiguity-ref-242

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `98`
- Legacy token: `ADR-0086-D1`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D1, ADR-0086-D3, ADR-0086-D4`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-243"></a>
### ambiguity-ref-243

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `98`
- Legacy token: `ADR-0086-D3`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D1, ADR-0086-D3, ADR-0086-D4`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-244"></a>
### ambiguity-ref-244

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `98`
- Legacy token: `ADR-0086-D4`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D1, ADR-0086-D3, ADR-0086-D4`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-245"></a>
### ambiguity-ref-245

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `112`
- Legacy token: `ADR-0086-D8`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D8`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-246"></a>
### ambiguity-ref-246

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `127`
- Legacy token: `ADR-0086-D9`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Related decisions: ADR-0086-D9`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-247"></a>
### ambiguity-ref-247

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `139`
- Legacy token: `ADR-0086-D1`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `| ADR-0086-D1 | REQ-1, REQ-7 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-248"></a>
### ambiguity-ref-248

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `140`
- Legacy token: `ADR-0086-D2`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `| ADR-0086-D2 | REQ-1, REQ-2 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-249"></a>
### ambiguity-ref-249

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `141`
- Legacy token: `ADR-0086-D3`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `| ADR-0086-D3 | REQ-3, REQ-7 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-250"></a>
### ambiguity-ref-250

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `142`
- Legacy token: `ADR-0086-D4`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `| ADR-0086-D4 | REQ-4, REQ-5, REQ-7 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-251"></a>
### ambiguity-ref-251

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `143`
- Legacy token: `ADR-0086-D5`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `| ADR-0086-D5 | REQ-4 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-252"></a>
### ambiguity-ref-252

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `144`
- Legacy token: `ADR-0086-D6`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `| ADR-0086-D6 | REQ-5 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-253"></a>
### ambiguity-ref-253

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `145`
- Legacy token: `ADR-0086-D7`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `| ADR-0086-D7 | REQ-6 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-254"></a>
### ambiguity-ref-254

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `146`
- Legacy token: `ADR-0086-D8`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `| ADR-0086-D8 | REQ-8 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-255"></a>
### ambiguity-ref-255

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `147`
- Legacy token: `ADR-0086-D9`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `| ADR-0086-D9 | REQ-9 |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-256"></a>
### ambiguity-ref-256

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `860`
- Legacy token: `ADR-0086-D1`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Rejected by ADR-0086-D1. It makes the new Project selector misleading and keeps primary session as implicit source of truth.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-257"></a>
### ambiguity-ref-257

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `864`
- Legacy token: `ADR-0086-D2`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Rejected by ADR-0086-D2. Required exact-set semantics are clearer even though this is a breaking public API change.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-258"></a>
### ambiguity-ref-258

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `868`
- Legacy token: `ADR-0086-D4`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Rejected by ADR-0086-D4/D5. A minimal Agent-owned preset store gives a simple query path and future extension point without turning into a logical Project model.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-259"></a>
### ambiguity-ref-259

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `872`
- Legacy token: `ADR-0086-D6`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Rejected by ADR-0086-D6. Catalog is preset-only; session Project rows remain path-only bindings.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-260"></a>
### ambiguity-ref-260

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `876`
- Legacy token: `ADR-0086-D7`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Rejected by ADR-0086-D7. Nested directories must be valid Project working scopes.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-261"></a>
### ambiguity-ref-261

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `880`
- Legacy token: `ADR-0086-D8`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Rejected by ADR-0086-D8. WorkspacePanel is a file management panel with destructive actions; Project selection needs a dedicated directory picker.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-262"></a>
### ambiguity-ref-262

- Source file: `docs/azents/design/new-session-project-selection.md`
- Source line: `884`
- Legacy token: `ADR-0086-D9`
- Candidate ADR files: `0086-chat-action-messages.md`, `0086-new-session-project-selection.md`
- Source text: `Rejected by ADR-0086-D9. Session creation should not depend on runtime readiness, especially when selecting catalog presets.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-268"></a>
### ambiguity-ref-268

- Source file: `docs/azents/design/session-scoped-toolkit-lifecycle.md`
- Source line: `64`
- Legacy token: `ADR-0029`
- Candidate ADR files: `0029-drop-dormant-stdio-mcp-sidecar.md`, `0029-testenv-qa-fixtures.md`
- Source text: `- Revive stdio MCP sidecar. Keep ADR-0029 decision removing dormant per-agent stdio.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-269"></a>
### ambiguity-ref-269

- Source file: `docs/azents/design/session-scoped-toolkit-lifecycle.md`
- Source line: `278`
- Legacy token: `ADR-0029`
- Candidate ADR files: `0029-drop-dormant-stdio-mcp-sidecar.md`, `0029-testenv-qa-fixtures.md`
- Source text: `The same spec glossary still references stdio + mcp-proxy sidecar support, while ADR-0029 removed dormant per-agent stdio MCP sidecar. Spec promotion must align this with the current remote HTTP/Streamable HTTP direction.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-270"></a>
### ambiguity-ref-270

- Source file: `docs/azents/design/session-shared-unread-run-state.md`
- Source line: `15`
- Legacy token: `ADR-0174`
- Candidate ADR files: `0174-present-chat-activity-as-an-ordered-event-stream.md`, `0174-session-shared-unread-run-result-state.md`
- Source text: `This design implements ADR-0174. It does not introduce user-specific notifications, change Session ordering, or add unread behavior to subagent or archived Session surfaces.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-271"></a>
### ambiguity-ref-271

- Source file: `docs/azents/design/session-shared-unread-run-state.md`
- Source line: `371`
- Legacy token: `ADR-0174`
- Candidate ADR files: `0174-present-chat-activity-as-an-ordered-event-stream.md`, `0174-session-shared-unread-run-result-state.md`
- Source text: `None. Product decisions are recorded in ADR-0174, and implementation details are defined by this design.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-275"></a>
### ambiguity-ref-275

- Source file: `docs/azents/design/subagent-spawn-inference-profile-validation-2026-07-11.md`
- Source line: `13`
- Legacy token: `ADR-0124`
- Candidate ADR files: `0124-keep-inference-provenance-run-owned.md`, `0124-subagent-spawn-inference-profile-overrides.md`
- Source text: `against ADR-0124, the delivery plan, deterministic E2E fixtures, and current living specs.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-276"></a>
### ambiguity-ref-276

- Source file: `docs/azents/design/subagent-spawn-inference-profile.md`
- Source line: `248`
- Legacy token: `ADR-0124`
- Candidate ADR files: `0124-keep-inference-provenance-run-owned.md`, `0124-subagent-spawn-inference-profile-overrides.md`
- Source text: `The rejected alternatives and long-term consequences are recorded in ADR-0124.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-277"></a>
### ambiguity-ref-277

- Source file: `docs/azents/design/subscription-provider-usage-validation-2026-07-19.md`
- Source line: `12`
- Legacy token: `ADR-0168`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `\[\`subscription-provider-usage.md\`\](./subscription-provider-usage.md), ADR-0168, and the phased`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-278"></a>
### ambiguity-ref-278

- Source file: `docs/azents/design/subscription-provider-usage-validation-2026-07-19.md`
- Source line: `24`
- Legacy token: `ADR-0168`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `- implementation drift against ADR-0168, the approved design, implementation plan, and current living specs.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-279"></a>
### ambiguity-ref-279

- Source file: `docs/azents/design/subscription-provider-usage-validation-2026-07-19.md`
- Source line: `270`
- Legacy token: `ADR-0168`
- Candidate ADR files: `0168-release-bundled-and-provider-backed-skill-sources.md`, `0168-unify-subagent-communication-through-mailbox-activity.md`, `0168-use-single-provider-tool-events.md`
- Source text: `## ADR-0168 and Approved Design Comparison`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-280"></a>
### ambiguity-ref-280

- Source file: `docs/azents/design/subscription-provider-usage.md`
- Source line: `17`
- Legacy token: `ADR-0169`
- Candidate ADR files: `0169-add-openrouter-as-an-integration-scoped-llm-provider.md`, `0169-integration-scoped-subscription-usage.md`
- Source text: `ADR-0169 records the architectural decisions behind this design.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-281"></a>
### ambiguity-ref-281

- Source file: `docs/azents/design/tool-search-bounded-working-set-validation-2026-07-19.md`
- Source line: `11`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `This report validates ADR-0147 after Tool Search became an Agent-level opt-in capability. It covers Agent persistence and API propagation, generated clients, default-disabled compatibility behavior, enabled deferred Tool Search behavior, provider request compatibility budgets, the session-shared working set, frontend settings, and product-path E2E fixtures.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-282"></a>
### ambiguity-ref-282

- Source file: `docs/azents/design/tool-search-bounded-working-set-validation-2026-07-19.md`
- Source line: `244`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `| ADR-0147 decision | Implementation status | Evidence |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-283"></a>
### ambiguity-ref-283

- Source file: `docs/azents/design/tool-search-bounded-working-set-validation-2026-07-19.md`
- Source line: `269`
- Legacy token: `ADR-0147`
- Candidate ADR files: `0147-openai-native-responses-transport-family.md`, `0147-tool-search-bounded-working-set.md`
- Source text: `All deterministic backend, generated-client, frontend, and static E2E validation sets pass. The implementation matches ADR-0147 including D10 and preserves ADR-0085 behavior. Docker-backed product-path execution remains unavailable locally because the Docker socket is absent. The two focused runtime-provider tests run in a dedicated Docker-capable pull-request CI job and gate \`ci-python-e2e\`; that job must pass before the stack is merge-ready.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-284"></a>
### ambiguity-ref-284

- Source file: `docs/azents/design/turn-scoped-failed-run-retry.md`
- Source line: `198`
- Legacy token: `ADR-0145`
- Candidate ADR files: `0145-model-scoped-selectable-model-settings.md`, `0145-require-explicit-responses-stream-completion.md`, `0145-scope-failed-run-retry-to-model-turn.md`
- Source text: `- Add ADR-0145 to supersede ADR-0084 only for retry-budget scope and success lifecycle.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-287"></a>
### ambiguity-ref-287

- Source file: `docs/azents/spec/domain/toolkit.md`
- Source line: `630`
- Legacy token: `ADR-0029`
- Candidate ADR files: `0029-drop-dormant-stdio-mcp-sidecar.md`, `0029-testenv-qa-fixtures.md`
- Source text: `- **MCP** — Model Context Protocol. Current production path uses remote HTTP / Streamable HTTP/SSE based MCP toolkit. Dormant per-agent stdio sidecar path was removed by ADR-0029.`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-288"></a>
### ambiguity-ref-288

- Source file: `docs/azents/spec/flow/chatgpt-oauth.md`
- Source line: `310`
- Legacy token: `ADR-0169`
- Candidate ADR files: `0169-add-openrouter-as-an-integration-scoped-llm-provider.md`, `0169-integration-scoped-subscription-usage.md`
- Source text: `| 2026-07-19 | 17 | Added integration-scoped live subscription usage, permission-projected financial details, one-refresh retry, and card-local presentation | ADR-0169 and validated subscription usage implementation |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-289"></a>
### ambiguity-ref-289

- Source file: `docs/azents/spec/flow/kimi-oauth.md`
- Source line: `277`
- Legacy token: `ADR-0171`
- Candidate ADR files: `0171-add-kimi-subscription-as-an-integration-scoped-provider.md`, `0171-archived-session-retention-and-purge.md`
- Source text: `| 2026-07-19 | 1 | Documented Kimi device authorization, encrypted identity, refresh, catalog, Moonshot runtime routing, usage, and UI behavior | ADR-0171 and validated implementation |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-290"></a>
### ambiguity-ref-290

- Source file: `docs/azents/spec/flow/openrouter-api-key.md`
- Source line: `162`
- Legacy token: `ADR-0169`
- Candidate ADR files: `0169-add-openrouter-as-an-integration-scoped-llm-provider.md`, `0169-integration-scoped-subscription-usage.md`
- Source text: `| 2026-07-19 | 1 | Documented the stable OpenRouter API-key integration, account catalog, runtime, UI, and security behavior | ADR-0169 and the verified OpenRouter implementation |`
- Status: unresolved historical reference; a source decision is required.

<a id="ambiguity-ref-291"></a>
### ambiguity-ref-291

- Source file: `docs/azents/spec/flow/xai-oauth.md`
- Source line: `269`
- Legacy token: `ADR-0169`
- Candidate ADR files: `0169-add-openrouter-as-an-integration-scoped-llm-provider.md`, `0169-integration-scoped-subscription-usage.md`
- Source text: `| 2026-07-19 | 6 | Added integration-scoped CLI-proxy subscription usage, trusted redirects, permission-projected financial details, and card-local presentation | ADR-0169 and validated subscription usage implementation |`
- Status: unresolved historical reference; a source decision is required.
