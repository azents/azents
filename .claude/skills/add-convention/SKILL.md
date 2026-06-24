---
name: add-convention
description: Add a path-scoped coding convention to .claude/conventions/. Trigger phrases include "add a rule for X", "we should always do Y", "let's enforce Z", "document our convention for W", "make agents aware that ...", "ban this pattern", or any request to make future agent edits respect a new project-wide invariant. NOT for one-off code comments, workflow how-tos, or domain explanations — those go elsewhere.
---

# Add a Convention

Add a new convention body under `.claude/conventions/<scope>/` so that agents editing files in that scope see it in the generated index and can fetch the full rule on demand.

## Step 0 — Branch from main

Conventions are team-wide and ship as their own PR. Cut a fresh branch from `main` *before* writing the body — never piggyback a convention onto a feature branch.

```bash
git checkout main && git pull && git checkout -b convention/<short-slug>
```

## Step 1 — Pick a scope

Open `scripts/generate-conventions-index.py` and read `SCOPE_CONFIG`. Pick the most specific scope whose `paths:` glob matches the files this rule applies to.

Current scopes:

| Scope | Applies to |
| --- | --- |
| `global` | Every file in the repo |
| `python` | `python/**` |
| `python-azents` | `python/apps/azents/**` |
| `typescript` | `typescript/**` |
| `typescript-azents-web` | `typescript/apps/azents-web/**` |
| `infra` | `infra/**` |
| `github-actions` | `.github/workflows/**` |
| `testenv-azents` | `testenv/azents/**` |

If no scope fits, **stop and ask the user** — adding a scope is a separate change (new entry in `SCOPE_CONFIG`, new index file in `.claude/rules/`, new directory in `.claude/conventions/`). When uncertain between two scopes, prefer the more specific one; when uncertain whether anything fits, prefer `global`.

## Step 2 — Pick a kebab-case filename

Topic-first, no redundant prefixes. The folder already implies "convention", so don't restate it.

Good:
- `pre-allocate-slices.md`
- `gorm-tx-parameter.md`
- `no-empty-value-defaults.md`
- `mantine-css-vars.md`

Bad:
- `rule-about-slices.md` (says "rule" — folder already implies it)
- `convention-pre-allocate.md` (restates "convention")
- `slices.md` (too vague — what about slices?)

## Step 3 — Write the title

This single line is the most important thing in the workflow. Agents read **only** the title from the index table and decide from that whether to fetch the body. A vague title means relevant rules get ignored OR irrelevant rules get fetched and burn context — both are failure modes.

Aim for: a specific situation + the action/avoidance + (optional) why-it-matters.

Good titles:

- `Pre-allocate slice capacity with make([]T, 0, n) when the final length is known to avoid grow-and-copy.`
- `Pass *gorm.DB explicitly into repository functions instead of holding it on a struct, so callers control the transaction boundary.`
- `Use NamedTuple or frozen dataclass for any function returning more than one value — bare tuples break silently when the field order changes.`
- `Prefer Mantine CSS variables (var(--mantine-color-*)) over hardcoded hex/rgba so dark mode theming works.`

Bad titles:

- `Slice rules.` (vague — about what?)
- `How we use gorm.` (multi-rule — split it)
- `pre-allocate-slices.md convention.` (restates the filename)
- `Follow Go best practices for slices.` ("best practices" is meaningless)

## Step 4 — Write the body

Use this template. Bodies must be readable in under ten seconds — if longer, split into multiple bodies, each with its own title.

````markdown
---
title: <single line that lets a future agent decide whether the rule applies to the edit they're about to make>
---

# <Human-friendly title>

<Optional one-sentence rationale, only if the "why" is not obvious from the rule.>

- ALWAYS / AVOID bullet stating the rule precisely
- Exception clauses, if any

## Bad

```<lang>
// minimal counter-example
```

## Good

```<lang>
// minimal corrected form
```
````

Rules:

- Frontmatter contains **only** `title:` (no `paths:`, no `scope:` — the folder name encodes scope).
- The title must be a single line — no embedded newlines.
- Keep the body short. Long bodies get skipped. If the rule needs more than ~10 seconds of reading, split it.

## Step 5 — Place the file

Drop it at `.claude/conventions/<scope>/<filename>.md`.

## Step 6 — Let pre-commit regenerate the index

Do **not** manually run `python scripts/generate-conventions-index.py`.
Do **not** install `python-frontmatter` into the repo or an ad hoc Python
environment to run the generator. The generator runs inside pre-commit's
isolated environment.

After adding the body file, stage it and commit. If pre-commit updates the
matching `.claude/rules/*-conventions.md` index, accept that generated diff,
stage the updated index, and commit again.

Check after pre-commit:

- The new row appears in the matching `.claude/rules/<scope>-conventions.md` (or `conventions.md` for `global`).
- The title in the table matches what you wrote.
- No unrelated convention index rows changed.

If pre-commit reports a validation error, fix the body (missing title,
multi-line title, file in the wrong place) and rerun the commit.

## Step 7 — Stage and commit

```bash
git add .claude/conventions/<scope>/<filename>.md .claude/rules/<scope>-conventions.md
git commit -m "convention: <one-line title>"
```

The pre-commit hook runs the generator. If it changes the index and stops the
commit, stage the generated index and commit again.

## Step 8 — Open a PR against main

```bash
gh pr create --base main --title "convention: <title>" --body "<rationale + a sentence on when to apply>"
```

The team reviews the convention before it starts shaping everyone's edits — a one-line title that the whole team is going to read before/after every relevant edit deserves the same scrutiny as a small refactor.

## When NOT to use this skill

| If it's really… | Use instead |
| --- | --- |
| A workflow ("how do I run X", "how do we deploy Y") | A skill under `.agents/skills/<name>/SKILL.md` |
| Domain context ("what is Agent", "what does the runtime provider do") | Update the relevant `AGENTS.md` |
| A one-off pattern in one file | A code comment at the spot |
| Already enforced by a linter, type checker, or codegen | Let the existing tool do it — adding a convention is duplication |
| Personal preference for *you* the user (not the team) | Save it as a memory in your global Claude config, not as a project convention |

## Why the title carries most of the weight

Agents do not read every body when they edit a file. They scan the index table for the matching scope, decide row-by-row from the title alone whether the body is worth fetching, and only then read the body.

Two failure modes follow from a fuzzy title:

1. **False negative** — the title sounds generic ("Slice rules"), the agent skips it, and the convention silently fails to apply. Now the rule exists but doesn't bind anyone.
2. **False positive** — the title is too broad ("Tips for writing Python") and the agent fetches the body for unrelated edits, burning context on rules that don't apply.

A good title is a one-line trigger: it names the situation precisely enough that an agent can match it against the edit they're about to make.
