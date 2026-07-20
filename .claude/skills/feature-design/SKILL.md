---
name: feature-design
description: "ADR-first workflow for new feature design, design documents, and architecture changes. Use for collaborative user discussion or autonomous discussion with a dedicated subagent interviewee. Complete a full draft, validate repository feasibility, revisit only blocker decisions, update the ADR before revising the design, and produce an implementable final design."
---

# Feature Design Workflow

Use an ADR-first design loop:

1. frame the problem;
2. create the ADR before accepting the first design decision;
3. complete the design draft;
4. validate feasibility against the real system; and
5. finalize when no blocker remains.

A draft or feasibility check may return to discussion, but only for a newly discovered blocker. Record every accepted decision in the ADR before revising the design.

## Modes

| User request | Mode |
| --- | --- |
| "Design this", "write a design doc" | **Collaborative**: discuss decisions with the user |
| "Proceed autonomously", "handle it yourself", "decide and continue" | **Autonomous**: discuss the same decisions with a dedicated subagent interviewee instead of the user |

Default to collaborative mode unless the user explicitly requests autonomous execution. Autonomous mode replaces the human participant; it does not remove or compress the discussion workflow.

## Workflow

### Phase 1: Problem framing

Inspect the current code and living specs before proposing a solution. Capture:

- user-visible goal and pain point;
- current behavior;
- non-goals;
- constraints and compatibility expectations;
- likely systems, files, APIs, data models, and lifecycle boundaries; and
- the initial decision backlog.

Do not treat assumptions as current behavior.

### Phase 2: ADR baseline and initial decisions

Create the ADR before accepting the first design decision. The initial ADR may contain unresolved questions while discussion is active.

For each initial decision that determines the architecture or product contract:

1. state the question;
2. provide realistic options and trade-offs;
3. recommend one option when evidence is sufficient;
4. obtain the decision from the user in collaborative mode or from the interviewee subagent in autonomous mode; and
5. update the ADR immediately before continuing.

Use this format for every decision discussion, whether the interviewee is the user or a subagent:

```markdown
### Decision Point: <name>

**Question**: <specific question>

**Options**
- A. <option> — pros/cons
- B. <option> — pros/cons

**Recommendation**: <recommended option and why>

Please choose A/B or adjust the direction.
```

Discuss one decision at a time and wait for the current interviewee's answer before continuing. In collaborative mode, post each decision as a separate GitHub Discussion comment or present it separately in an Issue, PR, terminal, or IDE conversation. In autonomous mode, send each decision separately to the dedicated interviewee subagent.

Once the ADR has enough accepted decisions to define a coherent direction, proceed to the design draft.

### Phase 3: Complete design draft

Write the complete draft under the project-approved design location. For Azents, use `docs/azents/design/` unless a more specific rule applies.

Include, as applicable:

- problem, goals, and non-goals;
- current behavior;
- proposed architecture and ownership boundaries;
- API and data-model changes;
- runtime and lifecycle behavior;
- state transitions and failure handling;
- security and permissions;
- migration, rollout, and rollback;
- observability and operational risks;
- test strategy and fixture requirements;
- alternatives considered; and
- assumptions and unresolved risks.

**Finish the draft before reopening discussion.** When drafting reveals a contradiction or unknown, record it as a candidate blocker and continue through every remaining section using explicit assumptions where necessary. Do not stop at the first difficult point or ask the user to resolve local implementation details mid-draft.

After the full draft exists, classify every candidate blocker. Reopen discussion only when the point meets the blocker criteria below. Resolve non-blockers without reopening discussion or record them as assumptions, risks, follow-up work, or implementation details.

If a blocker is found after drafting, follow this loop:

```text
ADR → complete design draft → blocker discussion → ADR update → design revision
```

After resolving the blocker, update the ADR first, revise the affected design sections, and continue to feasibility validation.

### Phase 4: Feasibility check

Validate the complete draft against the real repository and product constraints. Do not validate only the happy-path architecture.

Check:

- canonical source data and whether required identity and ordering survive each projection;
- current code paths, ownership boundaries, and lifecycle state;
- current specs in `docs/azents/spec/`;
- relevant ADRs and implemented design documents;
- API, event, persistence, migration, and compatibility impact;
- live-to-durable transitions, retries, pagination, concurrency, and failure modes;
- security, permissions, and operational risks;
- existing component and integration reuse;
- testability, deterministic fixtures, and E2E prerequisites; and
- whether the implementation can satisfy every accepted decision without hidden contract changes.

Produce a compact feasibility matrix with `feasible`, `conditional`, or `blocked` results and concrete evidence.

If feasibility discovers a blocker, follow this loop:

```text
ADR → design draft → feasibility check → blocker discussion → ADR update
```

Then revise the design and repeat the affected feasibility checks. Do not declare the design final while a blocker remains.

If feasibility finds no blocker, proceed directly:

```text
ADR → design draft → feasibility check → final design
```

### Blocker criteria

A newly discovered point is a blocker only when leaving it unresolved would do at least one of the following:

- invalidate or contradict an accepted ADR decision;
- make a required user-visible behavior or system invariant infeasible;
- require an unapproved API, event, persistence, security, or ownership-boundary change;
- force a choice between mutually exclusive architecture paths;
- prevent a credible feasibility conclusion or implementation plan; or
- make the required verification strategy impossible.

The following are not blockers by themselves:

- local refactoring or component-organization choices;
- naming, copy, spacing, or other reversible polish decisions;
- a straightforward test-fixture or migration implementation detail;
- an independent enhancement that can be deferred without violating the design;
- an engineering choice with one clearly safe conventional solution; or
- a risk that can be bounded and documented without changing an accepted decision.

When several blockers exist, collect them after the draft or feasibility pass and discuss them one at a time in dependency order. Do not turn every newly noticed detail into another design loop.

### Phase 5: Final design

Finalize only after the design and feasibility evidence agree with the ADR.

The final design must summarize:

- accepted decisions and their ADR source;
- rejected alternatives;
- validated system and data boundaries;
- feasibility evidence;
- remaining non-blocking risks and assumptions;
- implementation phases or the reason one focused PR is sufficient;
- required living-spec updates; and
- the verification plan.

Do not start implementation unless the user asks to proceed.

## Autonomous mode

Run the same decision discussion as collaborative mode, replacing the user with a dedicated subagent interviewee.

Before the first decision discussion:

1. launch one subagent dedicated to the interviewee role;
2. give it the problem framing, constraints, evidence, and current ADR state; and
3. tell it to answer decision questions and critique recommendations without editing the ADR or design document.

Keep the same interviewee for initial decisions, post-draft blockers, and feasibility blockers so the discussion retains context. Present the same options, trade-offs, recommendation, and one-decision-at-a-time sequence used with a human. Wait for the interviewee's answer, then update the ADR before changing the design.

The root agent remains responsible for repository research, recommendations, ADR and design writing, feasibility validation, and final synthesis. Do not replace the interview with a unilateral root-agent decision or ask the interviewee to author the artifacts.

Autonomous output must include:

- ADR and final design paths;
- key decisions and interviewee rationale;
- feasibility evidence;
- assumptions and remaining risks; and
- proposed implementation and verification plan.

## ADR rules

- Use an ADR for decisions that change a system boundary, persistent contract, security model, ownership rule, or long-term product behavior.
- For Azents feature design, create the ADR before recording the first accepted decision.
- Update the active, unimplemented ADR immediately after each accepted decision.
- Never rewrite an adopted or implemented ADR. Create a new superseding ADR when an established decision changes.
- Treat the ADR as the decision source of truth; keep detailed mechanics and feasibility evidence in the design document.

## Output expectations

For interactive progress, report the current phase, what was learned, and the next action concisely.

For final output, use:

```markdown
## Design Result

- ADR: `<path>`
- Design doc: `<path>`
- Mode: Collaborative | Autonomous
- Key decisions:
  - <decision and rationale>
- Feasibility:
  - <validated evidence>
- Remaining non-blockers:
  - <risk or assumption>
- Next steps:
  - <implementation or review step>
```

## Guardrails

- Do not invent current behavior; inspect code and living specs.
- Do not interrupt an incomplete draft merely because one section is difficult.
- Do not reopen discussion for a point that does not block another accepted decision or required outcome.
- Do not silently weaken an accepted requirement to avoid a feasibility problem.
- Do not overwrite implemented design history as if it were a living spec.
- Keep current behavior in `docs/azents/spec/`.
- Keep git-tracked artifacts in English.
- If the user asks to implement after final design approval, switch to the appropriate shipping workflow instead of mixing implementation into this skill.
