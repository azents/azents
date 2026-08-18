# Azents testenv

`testenv/azents` provides local infrastructure, reusable fixtures, and prerequisite snapshots for Azents development and E2E tests. Product behavior is verified in `testenv/azents/e2e`; this package prepares the environment that those tests need.

## Quick start

Prepare the local non-secret environment from this directory:

```bash
cd testenv/azents
uv run testenv bootstrap local
```

The bootstrap command prepares the non-secret `.env`, Docker Compose infrastructure, the current-worktree devserver, the `devserver` fixture, and a doctor summary. It does not create external secrets, perform OAuth logins, write directly to the product database, or run E2E tests.

Inspect or prepare an individual fixture with the supported fixture commands:

```bash
uv run testenv fixture doctor agent-basic --json
uv run testenv fixture up agent-basic --json
uv run testenv fixture reset agent-basic --json
```

Prepare external prerequisite metadata before running tests that need live credentials or browser state:

```bash
uv run testenv prerequisite prepare --profile live --json
```

Prerequisite snapshots contain safe metadata and guidance only. They must never contain raw access keys, secret keys, tokens, passwords, or browser credentials.

## E2E tests

Azents E2E tests live under `testenv/azents/e2e`:

```bash
cd testenv/azents/e2e
uv run pytest ./src/tests/required/public/test_health.py
```

Maintained suite ownership:

- `src/support_tests/` — Docker-free support tests that do not open listeners or start product services.
- `src/tests/required/` — credential-free product E2E using the Docker Runtime Provider.
- `src/tests/web/` — browser, TLS gateway, and worktree-built Web image E2E.

Each suite directory owns one execution profile through `suite.toml`. CI may split a suite into timing-balanced lanes, but every lane retains the same suite profile.

## Local infrastructure

Start or stop the testenv infrastructure directly when needed:

```bash
docker compose -f testenv/azents/docker-compose.yaml up -d
docker compose -f testenv/azents/docker-compose.yaml down
```

The Compose stack provides PostgreSQL, Valkey, and RustFS on test-only host ports. The stack intentionally uses disposable state and does not declare persistent volumes.

## Devserver lifecycle

The testenv devserver commands manage the current worktree's backend processes and local infrastructure:

```bash
cd testenv/azents
uv run devserver.py up
uv run devserver.py status
uv run devserver.py logs -n 200
uv run devserver.py down
```

Useful variants:

```bash
uv run devserver.py up --reload
uv run devserver.py up --no-infra --no-migrate
uv run devserver.py restart
uv run devserver.py down --all
```

Runtime state and logs are stored under the gitignored `testenv/azents/.state/` directory.

## Preflight

Run the legacy preflight utility when diagnosing local prerequisites:

```bash
cd testenv/azents
python preflight.py
```

Exit codes:

- `0` — all required checks passed.
- `1` — at least one required check failed.
- `2` — the preflight utility could not run.

Checks cover the repository root, Docker, Docker Compose, uv, tmux, Python, project dependencies, required environment values, devserver ports, infrastructure health, and migration state. A failed dependency causes dependent checks to skip instead of producing misleading secondary failures.

## Fixture setup substrate

The `agent-basic` fixture uses the setup metadata under `setup/` and handlers under `testenv/setup_handlers/`. These setup files are fixture implementation details, not a product QA catalog.

```bash
cd testenv/azents
uv run python scripts/gen-setup-index.py
```

The generator refreshes `setup/INDEX.md` and the setup list in `AGENTS.md` from setup frontmatter.

## Quality checks

```bash
cd testenv/azents
uv run ruff check .
uv run ruff format --check .
uv run ty check --error-on-warning
uv run pytest

cd e2e
uv run ruff check .
uv run ruff format --check .
uv run ty check --error-on-warning
uv run pytest ./src
```

## Constraints

- Use user-facing APIs, UI flows, slash commands, or OAuth flows to prepare product state.
- Do not insert, update, or delete product rows directly from test scenarios or helpers.
- Cleanup SQL is limited to designated database-reset setup paths.
- Keep external credential checks in prerequisite preparation; E2E tests consume the resulting snapshot.
- Keep product verification in E2E tests and use testenv only for fixture and prerequisite support.
