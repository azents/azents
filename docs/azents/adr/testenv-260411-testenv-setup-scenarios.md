---
title: "Split testenv Setup Scenarios and Inject INDEX — Discussion Record"
created: 2026-04-11
tags: [testenv, nointern, harness, scenarios, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: testenv-260411
historical_reconstruction: true
migration_source: "docs/azents/adr/0028-testenv-setup-scenarios.md"
---

# testenv-260411/ADR: Split testenv Setup Scenarios and Inject INDEX — Discussion Record

> 📌 **Related design document**: [testenv-setup-scenarios.md](../design/testenv-setup-scenarios.md)
>
> This document records design-stage discussion.

## Background

After actually running Slack/Discord integrations e2e work, derived from the #2450 stack, several scenarios (`TC-INT-SLACK-005~013`) repeatedly had to describe the same prerequisites:

- Create new user/workspace.
- Register Bedrock LLM model + create integration.
- Create Agent and attach shell tool.
- Clean up `slack_*` tables.
- Complete Slack OAuth installation.

Because each test `.md` duplicated these prerequisites inline, an improved setup method in one scenario, such as storage state cache, did not automatically propagate to other scenarios. The larger problem was that **agents could easily make wrong judgments such as "this is blocked" without knowing that a setup already exists**.

Real example: In Phase 3 PR (#2468), the agent reported that `TC-INT-SLACK-005` could not run because there was no LLM integration setup infrastructure, unaware that `seed/llm.py` and `seed/agent.py` already existed. The correct answer was: call seed.llm + seed.agent and prepare it directly. The judgment was missed because the prompt did not explicitly expose their existence.

## Solution Direction

Solve this along two axes:

1. **Separate setup scenarios from test scenarios** — collect reusable setup recipes under `scenarios/setup/`, and let test scenarios reference them only through `requires_setup` frontmatter.
2. **Inject setup INDEX into agent prompt** — automatically expose which setups exist at the start of each session, so the agent checks the INDEX before stopping with "there is no prerequisite."

A third axis, passing setup output through `runs/<run-id>/state.json`, connects the two axes in practice.

## Discussion Points (5)

### 1. Setup output delivery method

**Options:**

- **A) Context-based** — agent keeps setup result only in conversation memory.
- **B) File-based** — each setup merges its output into `runs/<run-id>/state.json`.
- **C) DB/environment-based lookup** — find identifiers again from DB each time.

**Decision: B — file-based state.json**

Rationale:

- testenv already has precedent with `runs/YYYY-MM-DD/` directories and `runs/_state/{email}.json` storage state cache.
- Even after session compaction or crash, one state.json file enables recovery and is powerful for resume/debugging.
- Setup only needs to call `seed/*` modules and add one line such as `state["user"] = {...}`, so overhead is minimal.

**Trade-off:** state.json schema management. Each setup declares its contract in frontmatter `outputs:`, and lint verifies it, connected to decision 4.

---

### 2. Idempotency representation

**Options:**

- **A) `idempotent: bool`** — one frontmatter field.
- **B) 3-state value**: `always | state-aware | never`.
- **C) `runs_when:` condition expression.
- **D) Natural-language explanation only.

**Initial decision: A**. Later discussion pointed out that **even if state.json records something, reality may be broken**, so the decision was strengthened.

**Final decision: A + `verify:` field**

```yaml
---
id: tailscale-funnel-active
idempotent: true
provides: [funnel.url]
verify: |
  curl -sf --max-time 5 "$TESTENV_FUNNEL_URL/healthz" > /dev/null
---
```

Agent decision rule:

1. `provides` key missing from state.json → run.
2. Key exists and `verify` exits 0 → skip.
3. Key exists, `verify` fails, and `idempotent: true` → rerun.
4. Key exists, `verify` fails, and `idempotent: false` → escalate or search cleanup setup.

`verify` can integrate with the existing `checks/` Runner by reusing Check classes through a thin shell wrapper.

**Trade-off:** define `idempotent` clearly as "the body is written in an ensure pattern and is safe to rerun." There is no static verification for false declarations. Decision 4 lint can later add smoke-test style checks.

---

### 3. Automatic INDEX generation vs manual maintenance

**Options:**

- **A) Fully manual**
- **B) Fully automatic**, through `scripts/gen-setup-index.py`
- **C) Hybrid** — manual top section for rules/FAQ, auto-generated lower table with markers

**Decision: C — hybrid**

Rationale:

- Top-level operational knowledge such as agent decision rules, naming conventions, and FAQ cannot come from frontmatter and should be human-maintained.
- Lower `id / provides / requires / idempotent / purpose` table has setup `.md` frontmatter as source of truth, so auto-generation prevents drift.
- CI can detect missing updates with `gen-setup-index.py && git diff --exit-code`, integrated with decision 4.

**Implementation:** marker-based replacement. The script overwrites only the region between `<!-- AUTO-GENERATED:START --> ... <!-- END -->`. Manual top/bottom regions are protected.

---

### 4. How to validate `requires_setup`

**Options:**

- **A) CI lint** — `scripts/lint-scenarios.py` runs in PR CI.
- **B) Runtime validation** — agent compares against INDEX immediately before execution.
- **C) Both**

**Decision: A — CI lint only**

Rationale:

- Same philosophy as not adding Stop hook in decision 1: runtime guard is over-investment for now. INDEX injection + CI lint catches more than 95%.
- Initial checks in `lint-scenarios.py`:
  1. No duplicate setup ids.
  2. Each test's `requires_setup` refers to a real setup id.
  3. Each setup's `requires` refers to a real setup id.
  4. Setup DAG has no cycle.
  5. Required frontmatter exists: `id`, `idempotent`, `summary`; `provides`/`requires`/`verify` are optional.
  6. `gen-setup-index.py` output matches current INDEX.md, drift check.

**Trade-off:** verifying that state keys referenced in the test body are transitively provided would require brittle body parsing, so it is excluded. Natural failures during agent execution will reveal it; lint can expand later if needed.

---

### 5. Prompt injection location for INDEX

**Options:**

- **A) Inline the full INDEX in AGENTS.md**
- **B) Put only a pointer in AGENTS.md and rely on on-demand Read**
- **C) Put summary + id list in AGENTS.md; detailed info requires reading INDEX**
- **D) Add setup links at the top of each test .md**

**Decision: C — summary + id list**

Rationale:

- Root cause of the "blocker" misjudgment was not knowing that a setup existed. B relies on the agent voluntarily checking and can recur. A costs too many tokens every session.
- C injects only **what exists**, roughly 300 tokens, so the agent immediately recognizes that `llm-provider-bedrock` setup exists and reads details only when needed. This prevents judgment errors at minimal token cost.
- The auto-gen script from decision 3 can also update the `<!-- SETUP-LIST:START -->` marker in AGENTS.md to prevent drift.

**Trade-off:** AGENTS.md becomes longer. Currently `testenv/nointern/AGENTS.md` does not exist, so it must be created or a section added to README.md.

---

## Decision Summary Table

| # | Decision |
|---|------|
| 1 | Pass setup output through file-based `runs/<run-id>/state.json`. Do not add Stop hook at this stage. |
| 2 | Use frontmatter `idempotent: bool` + `verify:` shell command. Agent trusts state.json cache only after verify passes. |
| 3 | Hybrid INDEX: manual top section for rules/FAQ, marker-based auto-generated lower table. |
| 4 | CI lint only through `scripts/lint-scenarios.py`. No runtime guard. |
| 5 | Put decision rules + setup id list in `testenv/nointern/AGENTS.md` with marker replacement. Read `scenarios/setup/INDEX.md` on demand for details. |

## Philosophy: Consistency with Existing testenv Principles

This design is consistent with three established testenv principles:

- **"testenv is not an e2e framework"** (Discussion #2358) — setup scenarios are Markdown runbooks and the agent is the runner. This does not add a Python automation framework; it improves reusability within the existing agent-as-runner paradigm.
- **"seed is not a one-shot bootstrap; it is building blocks"** — setup recipes are usage recipes for seed modules. They record which seed functions to call in which order with which arguments.
- **"LLM path uses real API key; LLM-bypass path uses dummy"** — setups keep the same distinction. For example, `llm-provider-bedrock` needs a real key, while `db-cleanup-slack` works in a dummy-key environment.

## Next Steps

Phase 2 draft design document → Phase 3 feasibility check → Phase 4 final design → create PR with `/ship-pr`. Then implement as a stacked PR series. Expected phases: setup skeleton → Slack-related setup → INDEX/gen script → lint/CI → migrate existing TC-INT-SLACK-* → cleanup.

## Migration provenance

- Historical source filename: `0028-testenv-setup-scenarios.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
