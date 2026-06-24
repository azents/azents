---
name: e2e-debugging
description: Debug Azents E2E tests, fixtures, browser state, and local integration failures.
---

# Azents E2E Debugging

Azents E2E tests live under `testenv/azents/e2e/`.

## Common Commands

```bash
cd testenv/azents/e2e
uv run pytest ./src -v
```

Run a focused test:

```bash
cd testenv/azents/e2e
uv run pytest ./src/tests/azents/public/test_health.py -v -s
```

## Fixture Preparation

```bash
cd testenv/azents
uv run testenv bootstrap local
uv run testenv prerequisite prepare --profile live --json
uv run testenv fixture doctor <fixture-id> --json
uv run testenv fixture up <fixture-id> --json
```

## Debugging Pattern

1. Reproduce with the smallest E2E test selection.
2. Capture server logs and browser traces when available.
3. Check fixture readiness before changing product code.
4. Fix fixture support only when the product behavior is already correct.
5. Prefer adding or updating E2E coverage for product behavior verification.

## Notes

- E2E tests may require Docker.
- Live/external tests require prepared prerequisite snapshots.
- Do not write product verification as legacy setup scripts; use E2E tests as the primary verification layer.
