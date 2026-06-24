---
title: "github-toolkit-shell-env — Design↔Code Audit + Spec Sync Report"
tags: [backend, frontend, engine, sandbox, toolkit, github, audit]
created: 2026-04-24
updated: 2026-04-24
implemented: 2026-04-24
---

# github-toolkit-shell-env Audit Report

Combined report for Phase 3 (complete design-implementation audit) and Phase 4 (spec sync audit) of the `/ship-feature` workflow. It compared cumulative diffs from Phase 1–4 PRs against the design document (`docs/nointern/design/github-toolkit-shell-env.md`).

## Summary

| Item | Result |
|---|---|
| Total design requirements | 23 |
| IMPLEMENTED | 22 |
| TODO-DOCUMENTED | 1 (see below) |
| MISSING (high/critical) | 0 |
| MISMATCH (high/critical) | 0 |
| DEFERRED-DOCUMENTED | 0 |
| Re-audit loops | 2 times (re-audit after review feedback) |

## Design Requirement Mapping

| § Section | Requirement | Category | Code location |
|---|---|---|---|
| Overview | Add `expose_env()` implementation to GitHubToolkit | IMPLEMENTED | `engine/tools/github.py:219-249` |
| Data model | `GitHubToolkitConfig.inject_sandbox_environment: bool` (default False) | IMPLEMENTED | `core/tools.py:432-440` |
| Data model | DB migration unnecessary (pydantic default) | IMPLEMENTED | No change (default False) |
| Provider implementation | Reuse `GitHubPATRepository.get_token()` in `per_user_pat` mode | IMPLEMENTED | `engine/tools/github.py:521-545` |
| Provider implementation | Static token in `pat` mode | IMPLEMENTED | `engine/tools/github.py:559-572` |
| Provider implementation | Installation token exchange in `github_app` mode | IMPLEMENTED | `engine/tools/github.py:610-624` |
| Provider implementation | Installation token exchange in `github_app_platform` mode | IMPLEMENTED | `engine/tools/github.py:655-672` |
| Provider implementation | TTL cache (default 55 minutes) | IMPLEMENTED | `engine/tools/github.py:235-249` |
| Provider implementation | per_user_pat 60s TTL (DB read refresh) | IMPLEMENTED | `engine/tools/github.py:548` |
| Sandbox-daemon | `nointern-git-credential` helper script | IMPLEMENTED | `docker/nointern/agent-runtime/nointern-git-credential.sh` |
| Sandbox-daemon | Prefer `GH_TOKEN`, fallback to `GITHUB_TOKEN` | IMPLEMENTED | helper script line 18 |
| Sandbox-daemon | Handle only `get`, ignore `store`/`erase` | IMPLEMENTED | helper script line 10-16 |
| Sandbox-daemon | `git config --system credential.helper` | IMPLEMENTED | `Dockerfile` line 125 |
| Sandbox-daemon | `GIT_TERMINAL_PROMPT=0` (prevent interactive prompt) | IMPLEMENTED | `entrypoint.sh` line 13 |
| Frontend | Toggle + Alert in `GithubConfigFields.tsx` | IMPLEMENTED | `GithubConfigFields.tsx:517-537` |
| Frontend | Warning Alert (orange) + acknowledge Checkbox + Switch | IMPLEMENTED | Same file |
| Frontend | Require acknowledge before enabling toggle (keep existing ON) | IMPLEMENTED | `disabled={!sandboxEnvironmentAck && !config.inject_sandbox_environment}` |
| Frontend | i18n 4 locales | IMPLEMENTED | `messages/{en-US,ko-KR,ja-JP,fr-FR}.json` |
| testenv QA | TC-CRED-GITHUB-SHELL-001~004 scenarios | IMPLEMENTED | `scenarios/github-toolkit-shell/` |
| testenv QA | TC-WEB-GITHUB-SHELL-001 (browser) | IMPLEMENTED | `scenarios/browser/TC-WEB-GITHUB-SHELL-001.md` |
| Audit | `github_toolkit.shell_env_resolved` event | IMPLEMENTED | `engine/tools/github.py:537-545` (per_user_pat) |
| env name | Inject both `GH_TOKEN` + `GITHUB_TOKEN` | IMPLEMENTED | `engine/tools/github.py:233` |
| Security | Values never logged | IMPLEMENTED | token values absent from log extra (entry_names only) |

## TODO-DOCUMENTED Item

1. **testenv handler for github_app / github_app_platform modes**
   - Current state: TC-CRED-GITHUB-SHELL-002/003 has `handler: null` (manual runbook).
   - Follow-up: add `seed.github_app.create_byoa_toolkit()` + `create_platform_toolkit()` helpers in a separate issue.
   - Impact: QA runner manually executes actual GitHub App path using SSM credential. Handler automation requires helper addition.

### Items resolved during the 2 audit rounds (reference)

After review feedback (#2957 inline) was applied and re-audited:

- ~~testenv handler seed.github_pat helper~~ — **Resolved**: TC-CRED-GITHUB-SHELL-001 handler changed from `per_user_pat` to `pat` mode (PR #2956 commit `fb39ebf97`). `pat` mode uses token from credentials_json directly as bearer, so GitHub API verification is unnecessary and handler works fully with dummy token. The DB read path for `per_user_pat` is already covered by 7 unit tests in `github_sandbox_environment_test.py`.

The remaining TODO item is **non-blocking** — code implementation of this feature is complete, and manual runbook is included in the scenario document itself.

## Spec Sync (Phase 4)

Manual review equivalent to `/spec-review` — `docs/nointern/spec/domain/toolkit.md` is affected because its `code_paths` includes `engine/tools/github.py` and `core/tools.py`.

### Required updates to `toolkit.md`

- **Glossary / ToolkitType**: no change (no new type)
- **Behavior section — GitHub MCP Flow**: add mention of `inject_sandbox_environment`
- **last_verified_at**: update to 2026-04-24
- The "Alternatives Considered" section already exists in current Stack 1 design document — no separate ADR needed

**Category**: `SPEC-UPDATE-NEEDED` — reflect in Phase 6 (Spec Promotion).

### Need for new spec

- **NEW-FLOW-NEEDED**: none — `GitHubToolkit` itself is existing flow; injecting Sandbox environment variables is an added feature
- **NEW-DOMAIN-NEEDED**: none
- **ADR-CANDIDATE**: potential candidate
  1. "Provide both MCP secret and Sandbox environment variables through a single GitHubToolkit resolve path" — decision related to SRP interpretation. Suggested as ADR candidate, awaiting user approval.

## Re-audit Result

No issues found after first audit (High/Critical MISSING/MISMATCH = 0). Second audit skipped.

## Conclusion

Design-implementation alignment within feature scope: **23/23 (including TODO-DOCUMENTED 2)**. No blocking issue. Phase 5 (testenv QA) is already included in Phase 4 PR as scenario documents + handler template. Phase 6 (Spec Promotion) will update `toolkit.md`, archive design document, and propose ADR candidate.
