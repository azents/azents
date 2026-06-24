---
title: "Design for separating testenv setup scenarios and injecting INDEX"
tags: [testenv, nointern, harness, scenarios]
created: 2026-04-11
updated: 2026-04-11
implemented: 2026-04-11
---

# Design for separating testenv setup scenarios and injecting INDEX

## Overview

Separate prerequisites repeatedly described by testenv test scenarios (user/workspace creation, LLM integration registration, agent creation, shell environment preparation, etc.) into **reusable setup recipes**, and inject setup catalog into agent prompt so agent immediately knows "which setups exist".

**Problems solved:**

1. Duplicate prerequisite descriptions between tests — e.g., existing TC-WEB-003, TC-SHELL-001, TC-MCP-001 each inline-copy user/ws seed + LLM integration + agent creation blocks
2. Agent incorrectly judges as "blocker" without knowing setup exists (real case: Slack e2e stack Phase 3 PR #2468 reported missing LLM infrastructure even though `seed.llm` already existed)
3. Setup improvements in one test do not propagate to other tests
4. Setup result delivery methods (user id, integration id, agent id, storage state path) are inconsistent

**Solution:**

1. Collect setup recipes in `scenarios/setup/` directory
2. `scenarios/setup/INDEX.md` catalog (hybrid — manual top + automatic table)
3. Decision rules + setup id list in `testenv/nointern/AGENTS.md` (automatic replacement)
4. Deliver setup output through `runs/<run-id>/state.json`
5. Prevent drift with `scripts/gen-setup-index.py` + `scripts/lint-scenarios.py`

**Implementation scope**: This design implementation migrates all existing **13 testenv scenarios** (sandbox-isolation × 3, chat-streaming × 1, shell-tool × 2, mcp-toolkit × 2, browser × 5) to setup pattern. Slack/Discord-family setup and TC-INT-SLACK-* scenario migration are separate follow-up work.

## Philosophical Consistency

Does not violate existing testenv's three principles:

- **"testenv is not an e2e framework"** — setup is also markdown runbook. It does not create a Python automation framework.
- **"seed is not one-shot bootstrap but building block"** — setup is "usage recipe" of seed functions (which order and which args).
- **"LLM path uses real key, LLM bypass uses dummy key"** — setup preserves same distinction.

Agent is still the runner. Setup is only a reference document saying "prepare this prerequisite like this".

## Discussion Points and Decisions

See `docs/nointern/adr/0028-testenv-setup-scenarios.md` for detailed discussion. Summary of 5 decisions:

1. **Setup output delivery**: `runs/<run-id>/state.json` file-based
2. **Idempotency**: frontmatter `idempotent: bool` + `verify:` shell command
3. **INDEX generation**: hybrid (manual top, automatic table bottom)
4. **Validation**: CI lint only (`lint-scenarios.py`)
5. **Prompt injection**: summary + id list in AGENTS.md (marker replacement)

## File Layout

```
testenv/nointern/
├── AGENTS.md                        # NEW — agent decision rules + setup-list marker
├── scenarios/
│   ├── INDEX.md                     # (existing) test scenario catalog
│   ├── setup/                       # NEW — setup recipe directory
│   │   ├── INDEX.md                 # NEW — setup catalog (marker based auto-gen)
│   │   ├── db-reset-nointern.md
│   │   ├── test-user-workspace.md
│   │   ├── default-shell-env.md
│   │   ├── llm-provider-dummy.md
│   │   ├── llm-provider-bedrock.md
│   │   ├── agent-dummy-key.md
│   │   ├── agent-with-shell.md
│   │   ├── sandbox-daemon-image.md
│   │   ├── mock-mcp-server.md
│   │   └── web-storage-state.md
│   ├── sandbox-isolation/           # (existing) TC-SBOX-001/002/005
│   ├── chat-streaming/              # (existing) TC-CHAT-001
│   ├── shell-tool/                  # (existing) TC-SHELL-001/002
│   ├── mcp-toolkit/                 # (existing) TC-MCP-001/002
│   ├── browser/                     # (existing) TC-WEB-001~005
│   └── ...
├── scripts/
│   ├── gen-setup-index.py           # NEW — frontmatter → INDEX + AGENTS.md marker replacement
│   └── lint-scenarios.py            # NEW — CI lint
└── runs/
    ├── .gitkeep
    ├── _state/                      # (existing) storage state cache
    └── YYYY-MM-DD/
        └── <run-id>/                # NEW — per-run workdir
            ├── state.json           # NEW — setup output chain
            └── <test_id>.log        # (existing) execution log
```

Slack/Discord integration family setup (`tailscale-funnel-active`, `ssm-credentials-pulled`, `slack-storage-state`, `slack-oauth-install`, `slack-channel-binding`) proceeds as separate **follow-up work** after Slack/Discord e2e stack (#2463~#2470) merges.

## Data Model

### Setup scenario frontmatter

```yaml
---
id: llm-provider-bedrock                    # unique, kebab-case
summary: Register Bedrock LLM provider integration and connect workspace
requires: [test-user-workspace, ssm-credentials-pulled]
provides: [integration.id, integration.provider, integration.name]
idempotent: false                            # body creates new resource on rerun
verify: |
  uv run python -c "
  from client import build_client_from_env
  import json, os
  state = json.loads(open(os.environ['STATE_FILE']).read())
  iid = state['integration']['id']
  # Check DB through admin API
  import sys; sys.exit(0 if iid else 1)
  "
llm_key_required: true                       # real BEDROCK_* creds needed
created: 2026-04-11
---
```

Fields:

- `id` (required): unique kebab-case, same as setup filename
- `summary` (required): one-line description shown in INDEX table
- `requires` (optional, default `[]`): list of other setup ids, prerequisites
- `provides` (optional, default `[]`): keys recorded in state.json after this setup runs (dot notation possible, e.g. `user.email`, `integration.id`)
- `idempotent` (required): if `true`, body is safe to rerun; if `false`, rerun creates new resource
- `verify` (optional): shell command to check reality before trusting state.json cache. Healthy when exit 0. If absent, judge only by state.json.
- `llm_key_required` (optional, default `false`): same as test scenario frontmatter
- `created` (required): YYYY-MM-DD

### Test scenario frontmatter extension

Existing:
```yaml
---
test_id: TC-SHELL-001
category: shell-tool
severity: high
llm_key_required: true
created: 2026-03-15
title: "Run echo command with shell tool"
---
```

Add:
```yaml
requires_setup:
  - test-user-workspace
  - default-shell-env
  - llm-provider-bedrock
  - agent-with-shell
```

Agent runs this list in DAG order (lint prevents cycles).

### `runs/<run-id>/state.json` schema

JSON object, setup merges its own `provides` keys. Example:

```json
{
  "run_id": "2026-04-11/run-abc123",
  "started_at": "2026-04-11T10:00:00Z",
  "user": {
    "email": "qa-abc123@example.com",
    "access_token": "eyJ...",
    "refresh_token": "eyJ..."
  },
  "ws": {
    "handle": "ws-abc123",
    "id": "019d..."
  },
  "integration": {
    "id": "019d...",
    "provider": "aws_bedrock",
    "name": "Test Bedrock abc123"
  },
  "agent": {
    "id": "019d...",
    "model_slug": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  },
  "funnel": {
    "url": "https://example-testenv.example.invalid"
  },
  "slack": {
    "installation": {
      "id": "019d...",
      "team_id": "T0AS59YEVHB",
      "bot_user_id": "U0ABCDE"
    }
  }
}
```

Merge semantics: setup records to dot-path such as `state["slack"]["installation"] = {...}`. If path already exists, object merge (shallow); if path is new, create it.

### Run ID selection

**Rule:** Agent first sets `TESTENV_RUN_ID` env var when starting testenv work (create if absent):

```bash
export TESTENV_RUN_ID="$(date -u +%Y-%m-%d)/run-$(uuidgen | cut -c1-8)"
mkdir -p "testenv/nointern/runs/$TESTENV_RUN_ID"
```

Setup body references `STATE_FILE="testenv/nointern/runs/$TESTENV_RUN_ID/state.json"`. All setups/tests in one session share same run id.

## Agent Decision Rules

(This block is injected into AGENTS.md)

Steps for agent when running test scenario:

1. **Ensure Run ID**: if `TESTENV_RUN_ID` absent, create it. Prepare `runs/$TESTENV_RUN_ID/` directory and `state.json` (empty `{}`).
2. **Read test scenario**: parse `requires_setup` list in frontmatter.
3. **Expand DAG**: recursively collect each setup's `requires` and sort topologically.
4. **For each setup, decide**:
   - Does state.json have all keys in setup `provides`?
     - If no → **run**
   - Does `verify` command exist?
     - If no → **skip**
     - If yes and exit 0 → **skip**
     - If yes and exit ≠ 0 + `idempotent: true` → **rerun**
     - If yes and exit ≠ 0 + `idempotent: false` → **escalate** (check for cleanup setup; if absent, report to user)
5. **Run setup**: follow body steps in setup .md verbatim. After completion, merge `provides` keys into state.json.
6. **Run test body**: execute runbook steps in test scenario .md.
7. **Record**: append summary to `runs/$TESTENV_RUN_ID/<test_id>.log`.

## INDEX Structure

### `scenarios/setup/INDEX.md`

```markdown
# Setup Recipes

Reusable setup recipe catalog. Test scenarios reference these recipes with
`requires_setup` frontmatter.

## Agent Decision Rules

[4-step rule inline — content synchronized with AGENTS.md]

## Naming Convention

- kebab-case, noun phrase. Example: `llm-provider-bedrock`, `slack-oauth-install`
- Cleanup form is `db-cleanup-<domain>`
- Environment/infra setup form is `<resource>-<state>` (e.g. `tailscale-funnel-active`)

## state.json Schema

[summary of main keys]

## Catalog

<!-- AUTO-GENERATED:START -->
| id | provides | requires | idempotent | purpose |
|----|----------|----------|------------|------|
| db-reset-nointern | — | — | ✓ | nointern DB table clean slate (idempotent) |
| test-user-workspace | user.*, ws.* | — | ✗ | seed new nointern user/workspace |
| default-shell-env | shell_env.id | test-user-workspace | ✗ | default shell environment of Workspace |
| llm-provider-dummy | integration.id (dummy) | test-user-workspace | ✗ | Dummy key LLM integration (LLM bypass path) |
| llm-provider-bedrock | integration.id | test-user-workspace | ✗ | Real Bedrock LLM integration |
| agent-dummy-key | agent.id | llm-provider-dummy, default-shell-env | ✗ | Dummy key agent (for pipeline verification) |
| agent-with-shell | agent.id | llm-provider-bedrock, default-shell-env | ✗ | Bedrock agent with Shell tool |
| sandbox-daemon-image | — | — | ✓ | build agent-runtime sidecar image |
| mock-mcp-server | mock_mcp.* | — | ✓ | verify fixtures/mock_mcp_server.py availability |
| web-storage-state | web_state.path | test-user-workspace | ✓ | nointern-web login storage state cache |
<!-- AUTO-GENERATED:END -->

## FAQ / Troubleshooting

[manual section]
```

### `testenv/nointern/AGENTS.md` (new file)

```markdown
# testenv/nointern — Agent Instructions

## Role

Scenarios in this directory are runbooks executed directly by agent acting as QA engineer.
Before running test scenario under `scenarios/`, required prerequisites reference reusable recipes in `scenarios/setup/`.

## Run ID

Set `TESTENV_RUN_ID` at work start and create corresponding run directory:

​```bash
export TESTENV_RUN_ID="$(date -u +%Y-%m-%d)/run-$(uuidgen | cut -c1-8)"
mkdir -p "testenv/nointern/runs/$TESTENV_RUN_ID"
echo '{}' > "testenv/nointern/runs/$TESTENV_RUN_ID/state.json"
​```

## Setup Decision Rules

For each setup listed in test scenario `requires_setup` frontmatter:

1. Does state.json have all keys in setup `provides`?
   - **No**: run setup body
2. Does setup have `verify` command?
   - no: **skip**
   - yes and exit 0: **skip**
   - yes and exit ≠ 0 + `idempotent: true`: **rerun**
   - yes and exit ≠ 0 + `idempotent: false`: **escalate** — search and run cleanup setup; if still failing, report to user

## Available setup

See [scenarios/setup/INDEX.md](scenarios/setup/INDEX.md) for details.

<!-- SETUP-LIST:START -->
- `db-reset-nointern` — nointern DB table clean slate (idempotent)
- `test-user-workspace` — seed new nointern user/workspace
- `default-shell-env` — default shell environment of Workspace
- `llm-provider-dummy` — Dummy key LLM integration (LLM bypass path)
- `llm-provider-bedrock` — Real Bedrock LLM integration
- `agent-dummy-key` — Dummy key agent (for pipeline verification)
- `agent-with-shell` — Bedrock agent with Shell tool
- `sandbox-daemon-image` — build agent-runtime sidecar image
- `mock-mcp-server` — verify fixtures/mock_mcp_server.py availability
- `web-storage-state` — nointern-web login storage state cache
<!-- SETUP-LIST:END -->

## state.json

Setup output storage. Each setup merges its own `provides` keys into this file,
and later setup/test reads it. Even if session compacts/restarts, one state.json can recover.

## Execution log

Append each test execution summary to `runs/$TESTENV_RUN_ID/<test_id>.log`.
```

**Backtick escaping caution**: bash block inside AGENTS.md is actually wrapped in triple backticks, but this draft avoids it with zero-width space.

## Example Setup Recipe

### `scenarios/setup/test-user-workspace.md`

```markdown
---
id: test-user-workspace
summary: Create new nointern user and workspace, record in state
requires: []
provides:
  - user.email
  - user.access_token
  - user.refresh_token
  - ws.handle
  - ws.id
idempotent: false
verify: |
  uv run python -c "
  import json, os, sys
  state = json.loads(open(os.environ['STATE_FILE']).read())
  handle = state.get('ws', {}).get('handle')
  if not handle:
      sys.exit(1)
  # Confirm DB existence
  import subprocess
  r = subprocess.run(
      ['docker', 'exec', 'nointern-testenv-db-1',
       'psql', '-U', 'nointern', '-d', 'nointern', '-tA', '-c',
       f\"SELECT 1 FROM workspaces WHERE handle = '{handle}';\"],
      capture_output=True, text=True,
  )
  sys.exit(0 if r.stdout.strip() == '1' else 1)
  "
llm_key_required: false
created: 2026-04-11
---

# setup: test-user-workspace

## Purpose

Create nointern user and workspace to use during one session.

## Execution

Use `testenv/nointern` as cwd:

​```bash
uv run python -c "
import json, os
from client import build_client_from_env

client = build_client_from_env()
user = client.auth.create_user()
ws = client.workspace.create(user)

state_file = os.environ['STATE_FILE']
state = json.loads(open(state_file).read())
state.setdefault('user', {}).update({
    'email': user.email,
    'access_token': user.access_token,
    'refresh_token': user.refresh_token,
})
state.setdefault('ws', {}).update({
    'handle': ws.handle,
    # if id is absent in workspace creation response, query from DB
})
open(state_file, 'w').write(json.dumps(state, indent=2))
print(f'SEEDED user={user.email} ws={ws.handle}')
"
​```

## Notes

- `seed.auth.Auth.create_user` creates email as `qa-{unique}@example.com`
- workspace handle is `ws-{unique}`
- second run within same session creates new user/ws (idempotent: false)
```

(Concrete bodies of other setup recipes are written in phase PRs)

## Example: Test Scenario (after setup application)

The part where existing `TC-WEB-003` described prerequisites inline is replaced by setup reference:

```markdown
---
test_id: TC-WEB-003
category: browser
severity: high
llm_key_required: true
requires_setup:
  - test-user-workspace
  - llm-provider-bedrock
  - agent-with-shell
created: 2026-04-10
title: "Chat session → message → LLM response UI rendering"
---

# TC-WEB-003 — Chat session (UI)

## Purpose
[existing content]

## Prerequisite

Setup scenarios (see `requires_setup`):
- `test-user-workspace` → state.user, state.ws
- `llm-provider-bedrock` → state.integration
- `agent-with-shell` → state.agent

Read `ws.handle` and `agent.id` from state.json and use in test body.

## QA runner steps

[existing steps, but `SLUG`/`HANDLE`/`AGENT_ID` are queried from state.json]
```

Duplicate seed blocks in each test disappear, and improving one place (setup recipe) benefits every test.

## Tooling

### `scripts/gen-setup-index.py`

**Function**: scan frontmatter of `scenarios/setup/*.md` → replace auto-gen blocks in INDEX.md and AGENTS.md.

**Input**: `testenv/nointern/scenarios/setup/*.md` (excluding INDEX.md)
**Output** (in-place modify):
- `<!-- AUTO-GENERATED:START/END -->` in `testenv/nointern/scenarios/setup/INDEX.md`
- `<!-- SETUP-LIST:START/END -->` in `testenv/nointern/AGENTS.md`

**Usage**:
```bash
cd testenv/nointern
uv run python scripts/gen-setup-index.py
```

**Dependency**: `python-frontmatter` (add to testenv pyproject.toml).

### `scripts/lint-scenarios.py`

**Checks**:

1. setup `id` uniqueness
2. setup `id` == filename (e.g., `llm-provider-bedrock.md` → id same)
3. required frontmatter exists: setup needs `id`, `summary`, `idempotent`, `created`
4. each test scenario `requires_setup` references real setup id
5. each setup `requires` references real setup id
6. setup DAG has no cycle (Kahn / DFS)
7. `gen-setup-index.py` result matches current INDEX.md + AGENTS.md (drift check)

**Usage**:
```bash
uv run python scripts/lint-scenarios.py
```

**exit**: 0 = pass, 1 = error (print each error to stderr)

**CI integration**: Add to GitHub Actions workflow. Trigger on testenv/nointern/ changes.

## Feasibility Verification Results

Prototype was actually written and executed in `/tmp/feasibility/`. All items passed.

### Dependencies

- `python-frontmatter==1.1.0` already exists in `testenv/nointern/pyproject.toml`. No new dependency.
- `graphlib` is Python standard library (3.9+). Use `TopologicalSorter` for DAG sort + cycle detection.

### gen-setup-index.py prototype (verified)

With 4 sample setups (`db-cleanup-slack`, `test-user-workspace`, `llm-provider-bedrock`, `agent-with-shell`):

- Replaced only between `<!-- AUTO-GENERATED:START/END -->` in `INDEX.md` with table — **success**. Top rule section and bottom FAQ section preserved.
- Replaced only between `<!-- SETUP-LIST:START/END -->` in `AGENTS.md` with id list — **success**. Two marker replacements work together.
- When no changes, no-op as `unchanged` — idempotent execution possible in pre-commit / CI.
- `re.sub` + `re.DOTALL` pattern sufficient. Script under 50 lines.

### lint-scenarios.py prototype (verified)

All 6 checks caught actual failure cases:

| Check | Failure simulation | Result |
|------|----------------|------|
| id uniqueness + filename match | filename != id | ✅ error |
| required frontmatter exists | missing `created` | ✅ error |
| Test `requires_setup` validity | references `nonexistent-setup` | ✅ error |
| Setup `requires` validity | nonexistent setup name | ✅ error |
| DAG cycle | `cycle-a ↔ cycle-b` | ✅ catches `graphlib.CycleError` |
| INDEX/AGENTS drift | add new setup without running gen | ✅ error (runs gen + diff) |

Caution with `graphlib.TopologicalSorter` — if explicitly calling `prepare()`, `static_order()` errors with "cannot prepare more than once". Call `static_order()` directly.

### Setup chain simulation (verified)

Ran 4-setup chain three times to confirm decision rules.

**First pass** (empty state):
```
resolved order: [db-cleanup-slack, test-user-workspace,
                 llm-provider-bedrock, agent-with-shell]
all actions: run
```
DAG resolution returns correct topological order.

**Second pass** (populated state, verify passes):
```
db-cleanup-slack: run      (runs every time because provides absent)
test-user-workspace: skip
llm-provider-bedrock: skip
agent-with-shell: skip
```
Setup with `provides: []` runs every time — intended behavior (cleanup is repeatable reset action).

**Third pass** (state corruption — `ws.handle = ""`):
```
test-user-workspace: escalate   (verify fail + idempotent: false)
others: skip
```
Only that setup escalates on partial corruption. No cascade — consistent with design that each setup `verify` checks reality of its own provides. This is intended behavior: `llm-provider-bedrock` staying "skip" assumes integration.id still exists in DB.

### state.json merge pattern (verified)

Shallow merge that recursively walks `dot-path` and writes only leaf. Example:

```python
def merge_state(state, provides, values):
    for key in provides:  # e.g., "user.email"
        parts = key.split(".")
        target = state
        for p in parts[:-1]:
            target = target.setdefault(p, {})
        target[parts[-1]] = values[key]
```

Within 5 lines. Multiple setups merging into same parent key (`state.user.email`, `state.user.access_token`) combine without conflict.

### verify command execution (verified)

Run multi-line bash from frontmatter `verify: |` with `subprocess.run(["bash", "-c", verify], env={..., "STATE_FILE": ...})`. Exit-code based judgment works.

YAML literal block scalar (`|`) preserves multi-line bash well — no quote escaping needed.

### Lessons learned (design adjustments)

1. **Meaning of `provides: []` setup finalized** — define as "reset/no-output action that runs every time". This covers `db-cleanup-*`, `truncate-*`, `wipe-*` styles.
2. **No cascade** — verify failure of one setup does not automatically trigger rerun of upstream setup. Each setup verify checks its own reality, so cascade is unnecessary (and risky — can cause unintended reset). If needed, test scenario explicitly adds cleanup setup to `requires_setup`.
3. **Need cleanup of lint drift check revert logic** — prototype runs gen, checks diff, then reverts original state. Implementation should be cleaner with "generate to temp file for comparison" → "compare to original". Functionality same.
4. **Setup without verify allowed** — if provides is empty like `db-cleanup-*`, verify can also be absent (always run). Defined as optional field.
5. **AGENTS.md currently absent** — `testenv/nointern/` currently has no AGENTS.md. Phase 3 PR must create it.

### Prototype location

Phase 3 feasibility prototype was temporarily written under `/tmp/feasibility/` and is not committed to this design PR. Real implementation proceeds in each phase of stacked PR series. Core prototype scripts are reusable enough to become starting point of Phase 2 (Tooling).

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Too fine-grained setup scenarios make instructions hard for agent to follow | Keep INDEX short; setup at domain unit (< 15 initial target) |
| flaky `verify` command makes skip/rerun decisions unstable | Use only deterministic checks such as curl/SQL for verify; no LLM calls |
| sensitive values (bot token, api key) stored in state.json → gitignored but possible accidental commit | `runs/` directory already gitignored. Additionally block `runs/**/state.json` in pre-commit hook |
| Agent again decides setup is "absent" despite INDEX injection | Add checklist to PR report template: "Did this test run setup X/Y/Z?" |
| marker replacement script bug overwrites manual area | clear marker comments, dry-run mode in gen script, check diff in CI |

## Implementation Plan (stacked PR series)

This design implementation aims to **migrate all existing testenv scenarios (13) to setup pattern**. Slack/Discord family setup and TC-INT-SLACK-* scenario migration are out of scope for this implementation plan — separate follow-up after #2463~#2470 stack merge.

### Existing 13 scenarios (migration targets)

| Category | Scenario | LLM path | Main prereq |
|---------|---------|---------|------------|
| sandbox-isolation | TC-SBOX-001/002/005 (3) | bypass | sandbox-daemon-image |
| chat-streaming | TC-CHAT-001 (1) | bypass (dummy key) | user/ws + llm-provider-dummy + agent-dummy-key |
| shell-tool | TC-SHELL-001/002 (2) | through real LLM (real Bedrock) | user/ws + default-shell-env + llm-provider-bedrock + agent-with-shell |
| mcp-toolkit | TC-MCP-001/002 (2) | through dummy key | user/ws + llm-provider-dummy + agent-dummy-key + mock-mcp-server |
| browser | TC-WEB-001~005 (5) | partly through real LLM (TC-WEB-003/005) | user/ws + web-storage-state + optional llm-provider-bedrock + agent-with-shell |

### Phase split

1. **Design document** (current PR #2475) — discussion + design + plan
2. **Phase 1: Setup infra skeleton + core setup** — `scenarios/setup/` directory, INDEX.md template, `runs/<run-id>/state.json` convention, core setup 4 files: `db-reset-nointern` / `test-user-workspace` / `default-shell-env` / `llm-provider-dummy` / `agent-dummy-key`
3. **Phase 2: Tooling** — `scripts/gen-setup-index.py` + `scripts/lint-scenarios.py` + CI workflow job registration. Smoke using Phase 1 setups.
4. **Phase 3: AGENTS.md + decision rule injection** — create `testenv/nointern/AGENTS.md`, place markers, run gen script for first setup list fill.
5. **Phase 4: Sandbox-isolation + chat-streaming migration**
   - New setup: `sandbox-daemon-image`
   - Migration: TC-SBOX-001/002/005 (requires_setup: `[sandbox-daemon-image]`)
   - Migration: TC-CHAT-001 (requires_setup: `[db-reset-nointern, test-user-workspace, default-shell-env, llm-provider-dummy, agent-dummy-key]`)
   - actual execution and report
6. **Phase 5: Shell-tool + mcp-toolkit migration**
   - New setup: `llm-provider-bedrock`, `agent-with-shell`, `mock-mcp-server`
   - Migration: TC-SHELL-001/002 (requires_setup: `[test-user-workspace, default-shell-env, llm-provider-bedrock, agent-with-shell]`)
   - Migration: TC-MCP-001/002 (requires_setup: `[test-user-workspace, default-shell-env, llm-provider-dummy, agent-dummy-key, mock-mcp-server]`)
   - actual execution (real Bedrock creds needed) and report
7. **Phase 6: Browser scenario migration**
   - New setup: `web-storage-state` (promote login flow of TC-WEB-002 to setup, or reclassify TC-WEB-002 itself as setup recipe — decide inside phase)
   - Migration: TC-WEB-001 (requires_setup: `[]` — unauthenticated smoke)
   - Migration: TC-WEB-002 (promote to setup recipe or keep as test and call setup)
   - Migration: TC-WEB-003 (requires_setup: `[test-user-workspace, llm-provider-bedrock, agent-with-shell, web-storage-state]`)
   - Migration: TC-WEB-004 (requires_setup: `[test-user-workspace, web-storage-state, llm-provider-bedrock]`)
   - Migration: TC-WEB-005 (requires_setup: `[test-user-workspace, llm-provider-bedrock, agent-with-shell, web-storage-state]`)
   - actual execution and report
8. **Cleanup** — remove stale documents (delete inline prereq sections from existing scenarios), update `scenarios/INDEX.md`, update README explanation

### Follow-up work (out of scope for this implementation)

- **Slack/Discord integrations family setup**: `tailscale-funnel-active`, `ssm-credentials-pulled`, `slack-storage-state`, `slack-oauth-install`, `slack-channel-binding`
- **TC-INT-SLACK-005~013 migration**: proceed on top of this implementation pattern after Slack/Discord e2e stack (#2463~#2470) merges

### Stack independence

- Phase 2 (tooling) can run right after Phase 1 or in parallel with Phase 1 — INDEX auto-generation/lint helps verify Phase 1, so early merge is preferable.
- Phase 3 (AGENTS.md) after Phase 2 — gen script must exist to fill initial setup-list.
- Phase 4/5/6 are category-independent and can be parallelized, but if using stacked PR, proceed sequentially (sandbox → shell → browser has low dependency).

## Alternatives Considered

### (Rejected) Python scenario class + pytest-style runner
Direction explicitly rejected in Discussion #2403. testenv is not an "automated e2e framework" but a "platform where agent acts as QA engineer". Adding Python automation violates this philosophy.

### (Rejected) Force state validation with Stop hook
Discussed in decision 1. Once root cause (missing INDEX injection) is fixed, hook is overinvestment. Keep possibility if actual skip recurs later.

### (Rejected) Manually describe setup links at top of each test .md
`requires_setup` frontmatter already fulfills this role. Body top links are duplicate.

### (Rejected) Context-only state transfer (without file)
Vulnerable to session compaction/crash. Low reproducibility.

### (Rejected) DB-only state transfer (without runs/ file)
High indirect query cost and SQL typing burden for each setup. Identifiers must be somewhere, so they end up stored in file anyway.

## Current Implementation Status (2026-04-20)

- ✅ 19 setup recipe files written
- ✅ `setup/INDEX.md` auto-generation works (`gen-setup-index.py`)
- ✅ 19 Python handlers implemented (`setup_handlers/`)
- ✅ scenario `requires_setup` references (used by 65 TCs)
- ⚠️ Automatic injection of `<!-- SETUP-LIST:START/END -->` markers in AGENTS.md incomplete — need one run of `gen-setup-index.py` to fill initial list

## Notes

- This design proceeds separately from Slack/Discord integrations e2e stack (#2463-#2470). Implementation scope of this stack is **full migration of existing 13 testenv scenarios**. Slack-related setup and TC-INT-SLACK-* migration proceed as separate follow-up after this stack completes.
- Existing `runs/_state/{email}.json` (storage state cache) remains unchanged. New `runs/<date>/<run-id>/state.json` has different purpose (setup output delivery).
- TC-WEB-002 has dual role: test that "verifies login flow itself" and setup that "creates storage state". In Phase 6, decide during actual migration whether to promote it to setup recipe or keep as test while setup references TC-WEB-002.
