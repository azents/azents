---
title: Do not set `temperature` in `.opencode/agents/*.md` frontmatter — most agents use reasoning models, and temperature settings can break those calls.
---

# No Agent Temperature

- AVOID setting `temperature` in `.opencode/agents/*.md` frontmatter.
- Reasoning models usually do not accept temperature overrides, so agent markdown must not declare one.

## Bad

```yaml
---
description: Reviews diffs
mode: subagent
model: openai/gpt-5.4
temperature: 0.1
---
```

## Good

```yaml
---
description: Reviews diffs
mode: subagent
model: openai/gpt-5.4
---
```
