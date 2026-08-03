---
name: skill-creator
description: Create, repair, and validate Agent Skill packages. Use when the user asks to create, update, fix, or diagnose a SKILL.md or a reusable Agent Skill.
---

# Skill Creator

Create filesystem Skills that Azents can discover and load. Use Shell file tools to
inspect, write, and validate the package instead of reporting a Skill as created
without checking its saved content.

## Choose the destination

- Use `/workspace/agent/.agents/skills/<skill-name>/SKILL.md` for an Agent-wide
  Skill unless the user requests a Project-specific location.
- Use `<project-path>/.agents/skills/<skill-name>/SKILL.md` for a Project Skill.
- Use `.claude/skills` only when compatibility with that convention is explicitly
  requested.
- Before changing an existing package, inspect its current `SKILL.md` and preserve
  unrelated adjacent files unless the user asks to replace them.

## Required frontmatter

Every discoverable `SKILL.md` must start with valid YAML frontmatter containing a
kebab-case `name` and a non-empty `description`.

```markdown
---
name: example-skill
description: Explain what the Skill does and when an Agent should use it.
---

# Example Skill
```

`description` is the discovery field shown to Agents. Do not substitute `summary`
for `description`; a Skill without `description` is not included in the Azents
Skill projection.

## Creation workflow

1. Briefly confirm the requested Skill's purpose, trigger conditions, scope, and
   destination.
2. Choose a stable kebab-case directory and `name`. They should match unless the
   user explicitly requests otherwise.
3. Create the directory and write `SKILL.md` with the required frontmatter.
4. Write concise instructions that tell an Agent what to do, what constraints
   apply, and what result to return. Keep secrets, private keys, access tokens,
   and credentials out of the Skill body.
5. Read the saved file back and verify:
   - the YAML frontmatter is present and closed;
   - `name` is non-empty and kebab-case;
   - `description` is non-empty;
   - the file is valid UTF-8 and lives directly at
     `<skill-directory>/SKILL.md`.
6. Report the exact saved path and any validation failure. Do not report success
   when the required frontmatter is missing.

## Projection lifecycle

Filesystem Skill discovery refreshes when the current run ends. A Skill created or
repaired during this run becomes available for the next run after the refresh.
Do not claim that the current run has loaded the new Skill. After the run clears,
confirm that the `/skill-name` action appears or, on a later run, that
`load_skill` accepts the exact `SKILL.md` path.

## Repair workflow

When an existing Skill is not discovered:

1. Verify that its file path is under a supported Skill root.
2. Inspect the frontmatter before changing the body.
3. Add or repair `description`; replace `summary` only when it was incorrectly
   used as the discovery description.
4. Re-read the saved file, then wait for the current run to complete before
   checking discovery in the next run.
