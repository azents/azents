---
title: "GitHubToolkit Shell Env Injection Feature"
tags: [backend, frontend, engine, sandbox, toolkit, github, historical-reconstruction]
created: 2026-04-24
updated: 2026-04-24
implemented: 2026-04-24
document_role: primary
document_type: design
snapshot_id: github-260424
migration_source: "docs/azents/design/github-toolkit-shell-env-2026-04-24.md"
historical_reconstruction: true
---

## Implementation Complete Status (2026-04-24)

Shipped 8-stack PR series through `/ship-feature` workflow.

| Stack | PR | Scope |
|---|---|---|
| 1/8 | #2952 | design document (original of this file) |
| 2/8 | #2953 | Phase 1 — Backend (`GitHubToolkit.expose_env()` + providers for 3 auth modes) |
| 3/8 | #2954 | Phase 2 — agent-runtime `nointern-git-credential` helper + entrypoint |
| 4/8 | #2955 | Phase 3 — `GithubConfigFields.tsx` toggle + Warning Alert + i18n 4 locales |
| 5/8 | #2956 | Phase 4 — 5 testenv QA scenarios (TC-CRED-GITHUB-SHELL-001~004 + TC-WEB-GITHUB-SHELL-001) |
| 6/8 | #2957 | design-implementation audit + spec sync report |
| 7/8 | _this PR_ | Spec Promotion — finalize design `implemented` + update `toolkit.md` |
| 8/8 | _next PR_ | Cleanup |

### Main Changes from Design

- No special deviation. Implemented as designed.
- 2 TODO-DOCUMENTED items (non-blocking):
  1. Extend `seed.github_pat.register()` testenv helper — automate dummy PAT registration step in TC-CRED-GITHUB-SHELL-001 handler
  2. `seed.github_app.*` testenv helper — automate TC-CRED-GITHUB-SHELL-002/003 handlers (currently manual runbook)

### Audit report

See `design/github-toolkit-shell-env-audit-report-2026-04-24.md`.

### ADR Candidate (waiting for user approval)

1. "Supply both MCP secret + shell env within single GitHubToolkit resolve path" — decision related to SRP interpretation. If user approves, create as `docs/nointern/adr/NNNN-github-toolkit-dual-consumer.md`.

# GitHubToolkit Shell Env Injection Feature

> Source issue: [#2950](https://github.com/azents/azents/issues/2950)
> Discussion: [#2951](https://github.com/azents/azents/discussions/2951)
> Predecessor feature: sandbox-credential-injection (PR #2912~#2947 merged)

## Overview

A path to inject arbitrary env into sandbox shell with `EnvVarToolkit` has shipped. Based on this, add shell env injection to existing `GitHubToolkit` so **agent can immediately execute automation such as `git push`, `gh pr create` from shell**.

Core: **not a separate toolkit type or token source addition.** Expose the tokens issued/stored by the 3 auth modes already supported by `GitHubToolkit` (`per_user_pat`, `github_app`, `github_app_platform`) to sandbox shell through `Toolkit.expose_env()`.

## User Scenario

Workspace manager:
1. Edit existing GitHubToolkit in `/w/{handle}/toolkits`
2. Turn ON "Expose shell env" toggle + acknowledge warning checkbox
3. Save

Agent session (LLM):
```
$ gh repo clone owner/repo target/
$ cd target && echo "fix" > README.md
$ git add README.md && git commit -m "docs"
$ git push origin HEAD:fix-branch
$ gh pr create --title "Docs fix" --body "..."
```
All commands above run **with automatic authentication**. Token is freshly supplied by GitHubToolkit on every resolve.

## Architecture

```mermaid
flowchart LR
  subgraph GitHubToolkit["GitHubToolkit (existing)"]
    P["per_user_pat<br/>GitHubPATRepository"]
    A["github_app<br/>JWT → installation"]
    AP["github_app_platform<br/>JWT → installation"]
  end
  subgraph Resolver["at resolve() time"]
    P --> TOK{issue token}
    A --> TOK
    AP --> TOK
  end
  TOK -->|MCP secret (existing)| MCP["GitHub MCP Toolkit"]
  TOK -->|expose_env() (new)| SHELL["Agent shell sandbox"]
  SHELL -->|credential helper| HELPER["/usr/local/bin/<br/>nointern-git-credential"]
  HELPER -->|GH_TOKEN env| GIT["git push / fetch"]
  SHELL -->|GH_TOKEN env| GH["gh CLI"]
  MCP --> API[(api.github.com)]
  GIT --> API
  GH --> API
```

1. At Agent session start, `GitHubToolkitProvider.resolve()` issues token by auth mode.
2. Same token branches into two paths:
   - **MCP secret** (existing) — for Octokit function calls
   - **Shell env** (new) — return by `Toolkit.expose_env()` → `BuiltinToolkit.set_peer_toolkits` → `_collect_secret_env` → `sandbox.exec(env=...)`
3. `git` / `gh` in Sandbox authenticate automatically through env path.

## Data Model

### `GitHubToolkitConfig` change (`python/apps/nointern/src/nointern/core/tools.py`)

```python
class GitHubToolkitConfig(BaseModel):
    github_auth_type: Literal["pat", "github_app", "github_app_platform", "per_user_pat"]
    toolsets: list[str] = ...
    timeout: float = 30.0
    # new
    inject_shell_env: bool = Field(
        default=False,
        description="When ON, inject GH_TOKEN/GITHUB_TOKEN into sandbox shell",
    )
```

DB storage: as-is in `toolkit_configs.config` (JSONB). No migration needed (backward compat with pydantic default).

### Credentials

Reuse existing credential schema:
- `per_user_pat`: user × workspace PAT in `GitHubPATRepository`
- `github_app`: `GitHubSecretsApp` (app_id, private_key, installation_id)
- `github_app_platform`: `GitHubSecretsAppPlatform` (installation_id)

## Provider/Toolkit Implementation

### `GitHubToolkit.expose_env()` (new override)

```python
class GitHubToolkit(Toolkit[GitHubToolkitConfig]):
    def __init__(self, ..., resolved_token: str | None = None):
        ...
        self._resolved_token = resolved_token  # in-session cache (value at resolve time)

    async def expose_env(self) -> dict[str, str]:
        """Inject GH_TOKEN/GITHUB_TOKEN into shell.

        Returns empty dict if inject_shell_env=False. If ON, obtain fresh token by
        auth mode and set same value to both env names.
        """
        if not self._config.inject_shell_env:
            return {}
        token = await self._get_fresh_token()
        if token is None:
            return {}
        return {"GH_TOKEN": token, "GITHUB_TOKEN": token}
```

`_get_fresh_token()` branches by auth mode:

| Mode | Behavior |
|---|---|
| `per_user_pat` | `GitHubPATRepository.get_token(user_id, workspace_id)` — DB read, long-lived PAT |
| `github_app` | check cached installation token → if TTL near expiry (< 5 min), reissue with `exchange_installation_token(jwt, installation_id)` |
| `github_app_platform` | same pattern, using platform credentials |

Cache strategy: Provider injects `resolved_token` + `expires_at` into `GitHubToolkit` instance. Every `expose_env()` call checks TTL and reissues if needed.

### `GitHubToolkitProvider.resolve()` change

Previously only MCP secret was issued, so token was not passed when creating `GitHubToolkit(...)`. Now, when `inject_shell_env=True`, issued token is passed as `resolved_token`. Same value as MCP secret, so no extra API call (reuse existing resolve logic).

## Sandbox-daemon Change

### `nointern-git-credential` helper script

Add following file to sandbox image:

`python/apps/nointern-sandbox-daemon/sandbox-image/usr/local/bin/nointern-git-credential`
```sh
#!/bin/sh
# Respond to git credential helper protocol with token passed by GitHubToolkit as shell env.
# Prefer GH_TOKEN, then check GITHUB_TOKEN.
token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
if [ -z "$token" ]; then
  exit 0  # empty response → let git try another path
fi

# We handle only get among git get/store/erase actions
if [ "$1" != "get" ]; then
  exit 0
fi

# same format as actions/checkout
echo "protocol=https"
echo "host=github.com"
echo "username=x-access-token"
echo "password=$token"
```

### Entrypoint change

`sandbox-image/entrypoint.sh` (or Dockerfile `RUN` line):
```sh
chmod +x /usr/local/bin/nointern-git-credential
git config --system credential.helper '!/usr/local/bin/nointern-git-credential'
```

Apply to all users/dirs with `--system` option. Even if agent only runs `git clone`, helper is immediately called → reads token from env and responds.

### Dockerfile Change Scope

- COPY helper script 1 line
- `git config --system` 1 line in entrypoint

Almost no impact on existing image layer.

## Frontend (UI/UX)

### `GitHubConfigFields.tsx` change (`typescript/apps/nointern-web/src/features/toolkits/components/`)

Add section to existing GitHub toolkit edit form:

```
┌────────────────────────────────────────────────┐
│ Existing fields (auth_type, toolsets, timeout)│
├────────────────────────────────────────────────┤
│ Expose GitHub token to shell                   │
│ ┌──────────────────────────────────────────┐  │
│ │ ⚠ Long-lived credential warning         │  │
│ │                                          │  │
│ │ GitHub token is injected into shell      │  │
│ │ child processes in Agent sandbox as      │  │
│ │ GH_TOKEN / GITHUB_TOKEN env. Enable only │  │
│ │ when you understand and accept that full │  │
│ │ isolation is not possible.               │  │
│ │                                          │  │
│ │ ☐ I acknowledge leakage risk             │  │
│ └──────────────────────────────────────────┘  │
│ ☐ Enable shell env exposure (toggle)          │
└────────────────────────────────────────────────┘
```

Reuse EnvVarToolkit Warning Alert pattern (orange Alert + acknowledge checkbox).

### i18n

`workspace.toolkits.github.shellEnv.*` 4 locales (ko-KR, en-US, ja-JP, fr-FR).

## testenv QA Scenarios

Actual sandbox injection verification for each of 3 auth modes. Marker-based end-to-end.

### TC-CRED-GITHUB-SHELL-001 — per_user_pat

setup:
- `test-user-workspace`, `default-shell-env`, `llm-provider-bedrock`, `agent-with-shell`
- GitHubPAT seed (register real PAT from SSM credential or dummy for test)
- Create GitHubToolkit (`github_auth_type=per_user_pat`, `inject_shell_env=true`)
- Attach to Agent

steps:
1. Start Chat session
2. Prompt: "Run `echo $GH_TOKEN | wc -c` in shell and tell me token length — do not print actual value"
3. Verify function_call_item output contains non-zero positive integer in stdout (proves token actually injected into env, without logging value)

### TC-CRED-GITHUB-SHELL-002 — github_app (BYOA)

Same structure, `github_auth_type=github_app` + BYOA credentials setup.

### TC-CRED-GITHUB-SHELL-003 — github_app_platform

Same structure, `github_auth_type=github_app_platform`.

### TC-CRED-GITHUB-SHELL-004 — git clone via credential helper

Run only once after all auth modes pass:
- Prompt: "Run `git clone https://github.com/nointern-qa/sandbox-repo.git /tmp/repo` in shell and tell me whether clone succeeded"
- Evidence: function_call output includes `Cloning into '/tmp/repo'...` + repo file confirmed by `ls /tmp/repo` result

### TC-WEB-GITHUB-SHELL-001 — UI toggle roundtrip

Playwright:
1. Create GitHubToolkit (auth_type=per_user_pat)
2. Turn ON "Shell env exposure" toggle, check ack, save
3. Verify DB `config.inject_shell_env=true`
4. Turn OFF toggle → save → verify DB again

## Infrastructure Changes

- **sandbox-daemon image**: one helper script + one entrypoint line (Dockerfile change)
- **sandbox-daemon k8s / docker-compose**: no change
- **DB schema**: no change (backward compat with pydantic default)
- **API spec**: no change (config field of existing ToolkitConfigCreateRequest is already open JSON)

## Feasibility Verification

| Item | Result |
|---|---|
| Reuse `GitHubPATRepository.get_token()` | ✅ (used in existing per_user_pat resolve) |
| Reuse `exchange_installation_token()` | ✅ (used in existing github_app resolve `on_auth_failure`) |
| `BuiltinToolkit.set_peer_toolkits` path | ✅ (verified in sandbox-credential-injection) |
| `git config --system credential.helper` | ✅ (standard used by actions/checkout for 10 years) |
| actual `git --version` / `gh --version` in sandbox | ⚠️ needs verification (whether installed in current image) |

Last item is checked by investigating Dockerfile during Phase 2 implementation; add `apt-get install -y git gh` if needed.

## Risks

| Risk | Mitigation |
|---|---|
| long-running command fails during 1h installation token TTL | mitigated in Phase 1 by fresh token on every `expose_env()` call; long-running (e.g. clone over 10 min) still vulnerable — document |
| git enters interactive prompt if helper script error occurs → sandbox hangs | when helper returns empty response, git moves to next helper. Also set `GIT_TERMINAL_PROMPT=0` in entrypoint to prevent interactive prompt |
| token readable by other processes in sandbox through `/proc/self/environ` | assumed impossible to fully isolate by design — disclosed with Warning UI (same as EnvVarToolkit) |
| ghcr.io docker login recognizes `GITHUB_TOKEN` → unexpected 3P tool recognition | intended behavior, not leakage path. accept |
| system session without user in per_user_pat mode | keep existing behavior — if token=None, `expose_env()` returns empty dict |

## Implementation Plan (by Phase)

| Phase | Content | Target files |
|---|---|---|
| 1 (Backend) | `GitHubToolkitConfig.inject_shell_env` + `GitHubToolkit.expose_env()` + token cache injection in Provider.resolve + audit log | `core/tools.py`, `engine/tools/github.py`, `engine/tools/github_test.py` |
| 2 (Sandbox-daemon) | `nointern-git-credential` helper script + Dockerfile + entrypoint change + docker integration test | `nointern-sandbox-daemon/sandbox-image/`, `executor_docker_integration_test.py` |
| 3 (Frontend) | toggle + Warning Alert + ack checkbox in `GitHubConfigFields.tsx`, i18n 4 locales | `features/toolkits/components/GitHubConfigFields.tsx`, `messages/*.json` |
| 4 (testenv QA) | TC-CRED-GITHUB-SHELL-001~004 + TC-WEB-GITHUB-SHELL-001 scenarios + handler | `testenv/nointern/scenarios/`, `tc_handlers/` |
| 5 (audit + spec-sync) | full design↔implementation audit + affected spec (domain/toolkit.md) sync | audit report |
| 6 (spec promotion) | finalize design `implemented` + spec update + ADR candidate | `docs/nointern/design/`, `spec/domain/toolkit.md` |
| 7 (cleanup) | remove stale docs | — |

## Alternatives Considered

Alternatives considered and rejected in Discussion #2951:

1. **Create new toolkit type `GitHubShellToolkit`** — rejected. Existing `GitHubToolkit` already has 3 auth modes. There was concern whether one toolkit supplying both "token for MCP" and "shell env" violates SRP, but actually these are "two consumers of same token", so supplying both in one resolve path is natural.

2. **Manual EnvVarToolkit registration (user directly enters `GITHUB_TOKEN`)** — rejected. Feature from issue #2873 (EnvVarToolkit) already makes this possible today, but:
   - user must register PAT twice (GitHub MCP + EnvVarToolkit)
   - on PAT expiry, both places must be updated
   - GitHub App installation token 1h refresh is impossible with EnvVarToolkit (stores only long-lived)
   - falls behind "first-class GitHub" experience trend (Codex/Cursor/Codespaces)

3. **Token URL embed method (`https://x-access-token:$TOKEN@github.com/...`)** — rejected. Token exposed in `git remote -v`, reflog, error log. Higher security risk.

4. **`credential.helper store` (plaintext file)** — rejected. File remains in sandbox filesystem and may be included in snapshot.

5. **`GIT_CONFIG_KEY_N` env (git 2.31+)** — considered, but burdens agent with preserving env on every git command. credential helper script is cleaner.

6. **`GH_TOKEN` only** — rejected. Third-party tools such as `docker login ghcr.io` look for `GITHUB_TOKEN`. Setting both like `actions/checkout` gives minimum friction.

7. **Include OAuth user-to-server (GitHub App) in Phase 1 scope** — rejected. Requires full OAuth flow UI + storage schema + refresh token implementation, expanding scope. Future separate feature.
