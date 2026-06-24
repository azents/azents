---
title: "testenv Recipes Structure Design"
created: 2026-04-12
updated: 2026-04-12
implemented: 2026-04-12
issue: 2505
---

# testenv Recipes Structure Design

## Directory Structure

```
testenv/nointern/
├── scenarios/       # only TC-*.md (actual test scenarios)
├── setup/           # test prerequisite state (infrastructure separate from scenarios)
├── recipes/         # reusable pattern documents (reference separate from scenarios)
└── scripts/
    ├── _helpers/    # common Python package
    └── run-tc-*.py  # TC runner
```

## Setup vs Recipe vs Scenario

| Category | Location | Purpose | Reference method |
|------|------|------|----------|
| Setup | `setup/` | Create test prerequisite state | frontmatter `requires_setup` |
| Recipe | `recipes/` | Reusable interaction pattern | `@recipe-id` in step |
| Scenario | `scenarios/` | Actual test scenario | executed by runner |

## Recipe Reference Spec

When referencing recipe in scenario QA runner steps, use `@recipe-id` format:

```markdown
1. Initialize Slack test environment with @slack-test-bootstrap
2. Bind agent to QA channel with @qa-channel-with-binding
```

The `@` prefix distinguishes it from setup (`requires_setup`). Recipe is not a frontmatter dependency; it is a pattern referenced inline in steps.
