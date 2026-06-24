---
title: "ADR-0027: testenv Framework Redesign — Discussion Record"
created: 2026-04-14
tags: [testenv, qa, architecture]
---

# ADR-0027: testenv Framework Redesign — Discussion Record

> 📌 **Related design document**: [testenv-runner-redesign.md](../design/testenv-runner-redesign.md)
>
> This document records design-stage discussion.

## Background

`testenv/nointern/` is an agent-as-runner QA platform (Discussions #2358, #2403, #2441). Claude Code acts as a QA engineer by reading TC Markdown files and executing them directly.

Recent Slack BYOA testing for issue #2548 exposed problems across **three axes** at the same time.

### Axis 1. False PASS: Reliability

| Case | Symptom | Classification |
|---|---|---|
| Dummy API key | Bot posted `AuthenticationError` → agent said "response arrived" and marked PASS | weak oracle |
| BYOA signed event 500 | TC Markdown was edited so "500 also PASS" | spec drift |
| Unique constraint conflict | Agent bypassed with `DELETE FROM ...` SQL and then marked PASS | state manipulation |
| Missing Platform OAuth | SKIP → redefined as "SKIP = PASS" | spec drift |

### Axis 2. Lack of Reproducibility

| Case | Symptom |
|---|---|
| Orphan BYOA installation | Previous run crashed → DB residue → next run 409, requiring manual cleanup |
| xoxc cookie expiry not detected | Stealth login was done once, then silently expired after several runs → unknown failure |
| Accumulated Slack channel messages | Fixed QA channel polluted by previous run messages → marker matching fragile |
| Cannot reinstall Platform OAuth | Existing OAuth install cannot be bypassed by setup → TC design itself is not executable |
| Cross-state.json contamination | Multiple TCs in one run mutate each other's state → changing order changes result |
| Bedrock model nondeterminism | Even temperature=0 can change after model updates → snapshot comparison impossible |

### Axis 3. Speed: Iteration Cost

| Metric | Current | Cause |
|---|---|---|
| Per-TC execution | 5-10 minutes | subagent boot + rereading AGENTS.md/recipe + setup chain from scratch |
| Repeated setup chain | 30-60 seconds each time | user → ws → LLM → agent → BYOA install repeated |
| DB reset | 30-60 seconds | `docker compose down --volumes && up` |
| 8 TCs sequential | 1-2 hours | sequential required because parallel execution races on shared resources |
| Human verification | 5 minutes per TC | lead reads logs/responses to check for false PASS |

One "run all TCs" cycle takes 2-3 hours. During BYOA development this created feedback loops measured in hours.

### The Three Axes Reinforce Each Other

- **Slow execution** → "I do not want to doubt a result after one expensive run" → false PASS becomes tolerated.
- **False PASS** → "human must verify again" → more time spent.
- **Lack of reproducibility** → "why did it pass last time and fail now?" → rerun → even slower.

All three axes cause each other. Fixing only one does not solve the root problem.

## Research Summary: Four Parallel Deep Research Tracks

### Formal Names of the Problem

- Reward hacking / specification gaming (arXiv [2502.13295](https://arxiv.org/abs/2502.13295))
- Spec drift / goalpost moving
- Sycophancy (HonestLLM, NeurIPS 2024)
- **ImpossibleBench (Anthropic, 2025.10, arXiv [2510.20270](https://arxiv.org/html/2510.20270v1))**: GPT-5 cheating 76%, Claude Opus 4.1 50%. This is a **default tendency of frontier models**, not a bug in our setup.

### Core Interventions, in Effectiveness Order

| Intervention | Effect |
|---|---|
| System prompt "STOP if tests flawed, do NOT carve out code" | GPT-5 92% → **1%** |
| Allow abort option, justifying "impossible" | 54% → **9%** |
| Test files read-only | Blocks direct modification, especially effective for Claude |
| Single LLM-based monitor | 42-65%, insufficient |
| Skyvern Validator, separate agent | WebVoyager 68% → **86%** (+17pp) |

### Structural Principles

- **Break the Agent = Oracle structure**: AI performs steps, deterministic code judges PASS/FAIL.
- **Move spec outside agent write scope**: physically block goalpost moving.
- **Fresh-context Verifier**: a separate agent that cannot see the parent trajectory re-verifies.
- **Honest failure > False success**: provide a third terminal state, BLOCKED, to reduce the temptation for false PASS.

## Discussion Points (15)

### 1. Oracle Separation Strategy

**Background**: Claude currently both executes and judges. Industry tools such as QA Wolf, Checkly, and Playwright Test Agents v1.56 separate AI execution from deterministic `expect()` judgments.

**Options**:

- **A) `expect:` block in TC Markdown** — declare status_code, forbidden_keywords, json_schema; runner validates with code.
- **B) Verifier agent only** — separate Claude subagent judges by reading logs.
- **C) A + B combination** — symbolic assertions first; if they pass, LLM verifier performs semantic extra validation.

**Decision: C**

- Deterministic assertion is the first oracle and cannot be manipulated.
- LLM verifier performs only additional semantic checks such as "does the Slack response answer the question?"
- B alone without A has only 42-65% accuracy and is insufficient. Without A, false PASS increases sharply.

### 2. Spec Immutability Mechanism

**Background**: The most dangerous failure mode is the agent editing TC Markdown to loosen acceptance criteria.

**Options**:

- **A) Filesystem permission** — `chmod 444` or overlay FS prevents runner from editing TCs.
- **B) `PreToolUse` hook** — block writes to `scenarios/`, `setup/`, `recipes/` paths at Claude Agent SDK level.
- **C) git diff sanity check** — after execution, require `git diff --name-only scenarios/` to be empty; otherwise force FAIL.

**Decision: B + C**

- B blocks at runtime.
- C verifies after the fact, catching bypasses of B.
- A gives unclear errors when the agent accidentally attempts a legitimate-looking write; B is more explicit.

### 3. Verifier Agent Design

**Background**: A fresh-context Verifier prevents the runner from rationalizing its own result. MARCH (arXiv [2603.24579](https://arxiv.org/html/2603.24579)) emphasizes being "strictly blinded to Solver's original output."

**Options**:

- **A) Deterministic rule-based verifier** — assertions + diff only.
- **B) Fresh Claude subagent** — sees original spec + fresh rerun, not parent trajectory.
- **C) A + B hybrid**

**Decision: C**

- A handles `expect:` block verification.
- B re-verifies whether the same conclusion follows from fresh context.
- If the two agents disagree, escalate to human.
- Cost is lower than runner because verifier reads only logs.

### 4. Terminal States

**Background**: Current PASS/FAIL binary creates temptation for spec drift: "environment missing" → SKIP → redefine "SKIP = PASS."

**Options**:

- **A) Keep 2 states**: PASS/FAIL.
- **B) 3 states**: PASS/FAIL/BLOCKED.
- **C) 4 states**: PASS/FAIL/BLOCKED/UNREACHABLE.

**Decision: C**

- BLOCKED: cannot run due to missing environment, setup failure, or dependency absence.
- UNREACHABLE: the TC specification itself contradicts the environment, such as Platform OAuth required but OAuth unavailable.
- Structure rewards honest failure over false success. ImpossibleBench shows adding abort option reduces cheating from 54% to 9%.

### 5. Fixture DAG: Finalizer / Reclaim / Lock

**Background**: Current setup DAG has three holes:

- No finalizer → orphan BYOA installations accumulate.
- No reclaim → state is empty but DB residue remains → 409.
- No lock → parallel TCs race on the same BYOA app.

**Options**:

- **A) Finalizer only** — pytest `addfinalizer` pattern.
- **B) A + Reclaim hook** — cleanup real-world state even when state file is empty.
- **C) A + B + Resource lock** — serialize shared unique resources with filelock.

**Decision: C**

- The three mechanisms complement each other. One alone cannot prevent both orphan resources and races.
- `filelock` is a pytest-xdist community standard.

### 6. Runner CLI Structure

**Background**: Current `scripts/` contains ad-hoc scripts. A consistent CLI is needed.

**Options**:

- **A) Single `run-tc.py`** — setup + test + verify all in one.
- **B) Multiple CLIs**: `run-setup.py`, `run-tc.py`, `run-verify.py`.
- **C) Subcommands**: `testenv run-tc`, `testenv run-setup`.

**Decision: C**

- One `testenv` CLI with subcommands, e.g. `uv run testenv run-tc ...`.
- High room for extension: `testenv list-tcs`, `testenv teardown`, and so on.
- Implement with Click / Typer.

### 7. State Scope: run-level vs tc-level

**Background**: Current state.json is run-scoped. When multiple TCs run in one run, state contaminates across TCs.

**Options**:

- **A) Run-level only**, current behavior.
- **B) Run-level + TC-level nested.
- **C) Run-level + TC-level + setup-level 3-tier.

**Decision: B**

- `state.json` has `run` key shared by all TCs and `tc[<tc_id>]` key per TC.
- Same idea as pytest `session` vs `function` scope.
- Setup `provides` declares `scope: run|tc`.
- 3-tier is over-engineering.

### 8. Assertion DSL

**Background**: What shape should the `expect:` block use?

**Options**:

- **A) Declarative YAML**: jsonpath, regex, status_code.
- **B) Python function code**.
- **C) Hybrid**: A for simple assertions, B for complex assertions as embedded Python.

**Decision: A**

- Declarative format is harder for the agent to mutate, strengthening immutability.
- Most tests are covered by A.
- If complex assertion is needed, place a separate verifier function in handler Python.

Example:

```yaml
expect:
  http_status: 200
  response_body:
    contains:
      - "Connected to"
    not_contains:
      - "AuthenticationError"
      - "BoltError"
      - "Traceback"
    json_path:
      - path: $.mode
        equals: byoa
      - path: $.slack_app_id
        matches: "^A[0-9A-Z]+$"
```

### 9. TC File Format

**Background**: Current format is Markdown + frontmatter. Should it change?

**Options**:

- **A) Keep Markdown + frontmatter**, current.
- **B) Fully switch to YAML.
- **C) Python fixture.

**Decision: A**

- Markdown is easy for humans to read and review.
- Frontmatter carries machine-readable metadata; body contains human-readable QA runner steps.
- Python is the pytest model and conflicts with the agent-as-runner philosophy.
- Minimizes migration cost.

Add a `handler:` field to frontmatter pointing to Python execution code. The "QA runner steps" in Markdown body remain for human review and as semantic criteria for the LLM verifier.

### 10. Setup/State Caching — Speeding Repeated Runs

**Background**: Setup chain takes 30-60 seconds per TC. Eight sequential TCs accumulate 4-8 minutes only in setup. This is a major cause of slow feedback loops.

**Options**:

- **A) Share only within a run**: setup result with scope=run is reused by multiple TCs in the same run.
- **B) Persistent cache across runs**: valid user/ws/agent persisted on disk and reused next run.
- **C) B + DB template-clone**, pgtestdb pattern: clone migrated template DB in under one second.

**Decision: A + C**

- A is naturally implemented by the 2-tier state scope from discussion #7.
- C replaces DB reset via `docker down/up` (30s) with template clone (1s). It can be split into a separate issue but belongs to the same design context.
- B is not adopted because of security/consistency issues such as expired tokens and stale auth.

### 11. Parallel Execution

**Background**: Previous parallel attempts overloaded the server, but sequential runs take 2+ hours. We need a balance.

**Options**:

- **A) Always sequential**.
- **B) Always parallel**, among TCs without shared resources.
- **C) Lock-based shard scheduler** — same lock tag goes to same shard; others run in parallel.

**Decision: C**

- Use `locks:` field in TC frontmatter.
- Default shard count is based on resource_lock distribution, default 4.
- Expected development feedback loop: 8 TCs spread across 2-3 shards → 30-40 minutes.

### 12. LLM Response Determinism (Bedrock)

**Background**: LLM call cost and nondeterminism hurt both reproducibility and speed.

**Options**:

- **A) Always live calls**, current.
- **B) VCR-style record/replay with record / replay / live modes.
- **C) Mock LLM provider only.

**Decision: A as default live + prepare VCR interface**

Hardtack decision from 2026-04-14 Discussion #2569:

- Default execution: **live calls**.
- Prepare **interfaces/hooks** so VCR can be introduced later easily.

Implementation:

- Add a pluggable transport interface to the LLM call path; default implementation is live passthrough.
- Reserve `_helpers/llm_cassette.py` location but do not implement record/replay logic yet.
- Reserve `NI_LLM_CASSETTE_MODE` environment variable; default `live`, future `record` / `replay` possible.
- In the design document, comment exactly where to change when enabling VCR later.

Rationale:

- Make it work live now, but if LLM becomes the bottleneck later, swap only the transport implementation.
- Retrofitting after the redesign is the most expensive path. Reserving the seam now is cheap.

### 13. Bot Response Determinism on Slack

**Background**: Accumulated Slack channel messages make marker matching flaky.

**Options**:

- **A) Message TTL per channel** — automatically archive old messages.
- **B) TC-start marker isolation strategy** — observe only responses after `parent_ts`.
- **C) Dedicated one-time channel per TC.

**Decision: B**

- Use `conversations.replies(ts=parent_ts)` for thread-level isolation, already partially implemented.
- Channel-level polling with `conversations.history` is flaky and should be forbidden.
- C explodes channel count and hits rate limits.

### 14. Reproducibility: Restore Last Successful State

**Background**: After a crash and restart, state.json may remain, but we do not know whether reality still matches state.

**Options**:

- **A) Validate entire state at every run start**, running verify for every setup.
- **B) Incremental verification** — state contains last_verified_at; re-verify only when stale threshold is exceeded.
- **C) Always reclaim + re-seed.

**Decision: B**

- Default stale threshold: 1 hour.
- If verify fails and setup is idempotent, reclaim → rerun.
- If verify fails and setup is not idempotent, escalate.

### 15. Migration Strategy

**Background**: 14 setups, 13 Slack TCs, 8 BYOA TCs, and other TCs must move to the new format.

**Options**:

- **A) Big bang** — convert all TCs/setup at once and cut over.
- **B) Gradual** — new TCs use new format; existing remain legacy.
- **C) Side-by-side** — two runners coexist.

**Decision: A**

- This is pre-release, so backward compatibility is unnecessary.
- Gradual / side-by-side increases maintenance cost and confusion.
- Conversion is possible in a one-day sprint, mostly automated.

## Decision Summary

### Reliability: Prevent False PASS

| # | Point | Decision | Core Rationale |
|---|---|---|---|
| 1 | Oracle separation | Deterministic assertion + LLM verifier hybrid | ImpossibleBench + Playwright Test Agents |
| 2 | Spec immutability | PreToolUse hook + git diff check | 92% → 1% effect |
| 3 | Verifier | Rule-based + Fresh Claude subagent | MARCH, Agent-as-Judge |
| 4 | Terminal states | 4-state: PASS/FAIL/BLOCKED/UNREACHABLE | abort option reduces 54% → 9% |
| 8 | Assertion DSL | Declarative YAML | strengthens immutability |

### Reproducibility: Stable Repeated Runs

| # | Point | Decision | Core Rationale |
|---|---|---|---|
| 5 | Fixture DAG | Finalizer + Reclaim + Lock | pytest addfinalizer, filelock |
| 7 | State scope | Run + TC 2-tier | pytest session/function |
| 13 | Bot response isolation | Force parent_ts thread polling | removes flaky marker matching |
| 14 | Restart recovery | Stale threshold + incremental verification | crash recovery |

### Speed: Iteration Cost

| # | Point | Decision | Core Rationale |
|---|---|---|---|
| 10 | Setup caching | Run scope + DB template-clone | 30s → 1s |
| 11 | Parallel execution | Lock-based shard scheduler | expected 2h → 30m |
| 12 | LLM determinism | live default + VCR interface only | Hardtack decision 2026-04-14 |

### Adoption Cost

| # | Point | Decision | Core Rationale |
|---|---|---|---|
| 6 | CLI | `testenv` subcommands | extensibility |
| 9 | TC format | Keep Markdown + frontmatter | minimize migration cost |
| 15 | Migration | Big bang, one-day sprint | pre-release, no backward compatibility needed |

## Research Sources

Primary:

- ImpossibleBench — arXiv [2510.20270](https://arxiv.org/html/2510.20270v1), Anthropic coauthored
- Agent-as-a-Judge — arXiv [2410.10934](https://arxiv.org/abs/2410.10934)
- Reflexion — arXiv [2303.11366](https://arxiv.org/pdf/2303.11366)
- Anthropic [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)
- [Playwright Test Agents v1.56](https://playwright.dev/docs/test-agents)
- [Skyvern 2.0](https://www.skyvern.com/blog/skyvern-2-0-state-of-the-art-web-navigation-with-85-8-on-webvoyager-eval/)

Test infrastructure:

- [pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- [pgtestdb](https://github.com/peterldowns/pgtestdb) / [IntegreSQL](https://github.com/allaboutapps/integresql)
- [pytest-xdist issue #668 — filelock semantics](https://github.com/pytest-dev/pytest-xdist/issues/668)

Slack-related:

- Slack [auth.revoke](https://docs.slack.dev/reference/methods/auth.revoke/), [apps.uninstall](https://docs.slack.dev/reference/methods/apps.uninstall/)
- [slack_cleaner2](https://github.com/sgratzl/slack_cleaner2)

Coding agent loops:

- [SWE-agent arXiv 2405.15793](https://arxiv.org/abs/2405.15793)
- [OpenHands arXiv 2407.16741](https://arxiv.org/abs/2407.16741)
- [Cognition — Devin 2.2](https://cognition.ai/blog/introducing-devin-2-2)
- [Claude Code Agent Loop](https://code.claude.com/docs/en/agent-sdk/agent-loop)
