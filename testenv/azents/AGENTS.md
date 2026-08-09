# testenv/azents — Agent Instructions

This directory is the test substrate for preparing local infrastructure, fixtures, and external prerequisite snapshots required by azents E2E tests. Product behavior verification belongs primarily in E2E tests. Feature QA plans and evidence belong in design, issue, PR, or report context. `testenv` is not a long-term verification catalog or an E2E wrapper, and it does not primarily own product behavior validation.

Coding and operational conventions for this area live in `.claude/rules/testenv-conventions.md`, including the no-direct-DB-write rule and live credential snapshot rules.

## Quality Checks

```bash
cd testenv/azents
uv run ruff check .
uv run ruff format --check .
uv run ty check --error-on-warning
uv run pytest
```

## Event Preparation Path

```bash
cd testenv/azents
uv run testenv bootstrap local
uv run testenv prerequisite prepare --profile live --json
uv run testenv fixture doctor <fixture-id> --json
uv run testenv fixture up <fixture-id> --json
```

- `bootstrap local` prepares only non-secret `.env`, Docker Compose infrastructure, the current-worktree devserver, `fixture up devserver`, and a doctor summary. It does not create external secrets, log in to Tailscale/OAuth, write directly to the product DB, or run E2E tests.
- If a fixture is missing or stale, prepare it explicitly using `fixture doctor`, `fixture up`, or `fixture reset` guidance.
- Legacy TC markdown, `run-tc`, verifier, and markdown bash fallback are not part of the event path.
- When new product behavior needs verification, consider adding E2E coverage first. `testenv` should only provide fixture/prerequisite support that enables E2E execution.
- E2E tests that require external credentials/prerequisites must read a snapshot produced during the prepare phase instead of running doctor directly inside the test.
- `prerequisite prepare` records external prerequisites such as Bedrock AWS shared credentials and browser/OAuth storage state as safe metadata only. Snapshots and CLI output must not contain raw secrets.

## Event E2E Path

azents E2E tests live under `testenv/azents/e2e/` as an exception so they can share the fixture/readiness/support boundary.

```bash
cd testenv/azents/e2e
uv run pytest ./src/tests/azents/public/test_health.py
```

E2E is the primary location for product behavior verification. `testenv` is the fixture/prerequisite support layer that makes E2E execution possible.

Required CI runs one Docker-free Testenv unit job and four credential-free E2E lanes from `testenv/azents/e2e`. Testenv unit uses `uv run pytest -vv ./src/unit_tests`. Deterministic E2E uses `uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src/tests`. Focused Runtime Provider E2E runs selected Docker Provider journeys. Kubernetes containment E2E creates a disposable kind cluster and runs the production Kubernetes Provider and Runner images through qualification, security, storage-lifecycle, network, and rollback checks. Web Surface E2E runs separately with `uv run pytest -vv -m "web_surface and not live_external and not runtime_provider" ./src/tests` and exercises worktree-built web applications through a real browser and gateway.

Each executed lane uploads JUnit XML, pytest output, slow-test timing, and Docker diagnostics even when pytest fails. Failed browser tests also capture a screenshot and page HTML when the browser session is available. Same-repository pull requests receive one sticky E2E observability comment that links to the workflow artifacts and summarizes each executed lane. Fork pull requests remain read-only and do not publish the comment.

Tests under `src/unit_tests/` must not start an HTTP/WebSocket server, open a network
listener, use Docker, build a product image, or depend on browser, Runtime Provider, or
external prerequisite state. Tests requiring any of those boundaries remain under
`src/tests/` as E2E verification.

Live/external verification runs only with the `azents-live-e2e` PR label, a maintainer comment on same-repository PRs, a manual workflow, or a nightly workflow. Live workflows run E2E tests marked `live_external`. Requested live verification fails when credentials are missing; nightly optional verification records prerequisite-not-ready as a skip summary.

## Fixture Setup Substrate

The `agent-basic` fixture internally uses `setup/*.md` and `testenv/setup_handlers/*.py` to create reusable seed state. This setup substrate is an implementation detail of fixture providers. Do not add new product behavior verification by directly running setup files or by adding legacy TC-style checks.

Keep only setup entries that are actually referenced by fixtures, E2E tests, or prerequisites.

<!-- SETUP-LIST:START -->
- `agent-dummy-key` — Create agent with dummy-key LLM integration and shell tool enabled
- `llm-provider-dummy` — Register dummy-key OpenAI LLM integration and ModelConfig for LLM-bypass pipeline tests
- `test-user-workspace` — Create new azents user and workspace, record in state.json
<!-- SETUP-LIST:END -->

## Scripts

- `scripts/gen-setup-index.py` regenerates `setup/INDEX.md` and the setup-list block in this file from setup frontmatter.

When adding setup support, first verify that a fixture, E2E test, or prerequisite actually needs it. If needed, add `setup/<id>.md` and `testenv/setup_handlers/<id>.py`, then run `uv run python scripts/gen-setup-index.py`.

## Key Documents

- [`README.md`](README.md) — devserver, fixture, and prerequisite command details
- [`setup/INDEX.md`](setup/INDEX.md) — fixture setup substrate catalog
