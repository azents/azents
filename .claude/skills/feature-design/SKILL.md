---
name: feature-design
description: "Requirements-first workflow for new feature design, design documents, and architecture changes. Use for collaborative or autonomous design: interview the user to confirm high-level requirements, preserve an immutable requirements snapshot, use reusable research subagents without blocking the conversation, record design decisions in an ADR, validate repository feasibility, and produce an implementable final design."
---

# Feature Design Workflow

Use this sequence:

```text
requirement interview
→ confirmed Requirements snapshot
→ system-grounded problem framing
→ ADR decisions
→ complete design draft
→ feasibility validation
→ final design
```

Keep each artifact's responsibility distinct:

- **Requirements**: what users need and how success is observed.
- **ADR**: why hard-to-reverse design decisions were chosen.
- **Design**: how the system will satisfy the requirements and ADR decisions.
- **Spec**: how the implemented system currently behaves.

## Modes

| User request | Mode |
| --- | --- |
| "Design this", "write a design doc" | **Collaborative**: discuss design decisions with the user |
| "Proceed autonomously", "handle it yourself", "decide and continue" | **Autonomous**: discuss design decisions with a dedicated interviewee subagent |

Default to collaborative mode. Both modes require the user to confirm the high-level Requirements before design decisions begin. Autonomous mode delegates design choices, not product intent.

## Phase 1: Requirement discovery

Keep the main agent as the interview owner. Restate the request, distinguish known facts from assumptions, and ask one high-value question at a time.

### Interview priorities

Establish, in dependency order:

1. the primary actor;
2. one primary end-to-end user scenario;
3. the expected outcome;
4. must-have behavior;
5. scope boundaries and non-goals;
6. fixed product, compatibility, security, or operational constraints; and
7. an observable success signal.

Do not use this list as a fixed questionnaire. Skip information already established by the request or prior answers. Ask a question only when its answer could change the primary scenario, user-visible contract, required scope, fixed constraints, success criteria, or later design-decision backlog.

Explain briefly why a question matters. Offer realistic examples or options when they help, but always allow a different answer. Recommend a direction only when evidence is sufficient.

Require exactly one primary scenario before completing discovery. Record additional scenarios as supporting, secondary, or future scope.

After several questions or a topic transition, summarize what is known and what remains. If a later answer contradicts an earlier one, state the conflict and confirm the change instead of silently overwriting it.

### Benchmark Assist

When the user lacks domain background, says they are unsure, asks how comparable products behave, or cannot judge a product convention, offer a quick benchmark study scoped to the current interview question.

Before researching:

1. state the research question;
2. propose two to four behaviorally relevant targets or target categories;
3. state the user-flow dimensions to compare; and
4. let the user accept or adjust the scope.

Return a compact pattern comparison, implications for this feature, and a recommendation. Then resume the interrupted interview question. Benchmark evidence informs the user's choice; it never becomes a requirement until the user accepts it.

Do not use benchmark research to answer questions only the requester can answer, such as their actual problem, organization policy, fixed constraints, or desired outcome.

### Reusable research subagents

Prefer long-lived research subagents so the main agent retains the interview context. Reuse one subagent per research lane instead of spawning a new one for each question. Typical lanes include:

- product and benchmark patterns;
- current repository and product behavior; and
- external platform or technical capabilities.

Give each research subagent:

- the original request;
- the current Requirements draft;
- confirmed facts and unresolved assumptions;
- the current interview or design question;
- accepted and rejected directions; and
- a strict evidence-only role that does not edit artifacts or decide product intent.

Send context deltas to the same subagent as the interview evolves. Redirect or discard stale research when the primary scenario changes.

Start limited, reversible scouting proactively when it will prepare better questions, but never wait for it before responding to the user. Do not interrupt the current topic merely because background research completed. Keep results in the main agent's research context until they naturally support the current or next question.

The main agent always owns user communication, Requirements confirmation, ADR updates, and final synthesis.

## Phase 2: Requirements snapshot

Once the primary scenario is stable, create the Requirements document before creating an ADR. For Azents, use:

```text
docs/azents/requirements/{word}-{YYMMDD}-{slug}.md
```

Use the KST Requirements creation date. Treat `{word}-{YYMMDD}` as the canonical snapshot ID and reference individual requirements as `{word}-{YYMMDD}/REQ-N`. Reserve the exact Requirements basename for the snapshot's later ADR and Design, even when those documents are created on a later date:

```text
docs/azents/adr/{same-basename}.md
docs/azents/design/{same-basename}.md
```

- Choose a short lowercase feature word such as `slack`, `memory`, or `billing`.
- Use a slug that names the specific user-visible capability, not an implementation method or broad topic.
- Avoid numeric allocation, `v2`, `final`, and similar mutable-version naming.
- If the same word and date collide, combine the same requirement effort or choose a more precise feature word. Do not append an arbitrary ordinal.

For Azents, follow [references/requirements-template.md](references/requirements-template.md) and `docs/azents/AGENTS.md`.

Include:

- problem and user-visible goal;
- primary actor and primary scenario;
- supporting scenarios;
- goals and non-goals;
- numbered requirements with observable acceptance criteria;
- fixed constraints;
- open assumptions; and
- explicit requester confirmation.

Do not include APIs, data models, libraries, class structure, architecture choices, implementation phases, or ADR decisions.

Present the complete Requirements document to the user and obtain explicit confirmation. If the initial request already establishes every required field, this may be one confirmation turn. Do not create the ADR or accept design decisions before confirmation.

### Requirements change and immutability

Before implementation, apply product-scope changes in this order:

```text
Requirements → ADR → Design
```

Return to the user whenever a discovery would add a user type, user-visible behavior, required scope, or contract; relax a confirmed constraint; or change the success signal. Do this in autonomous mode as well.

When implementation is complete and verified, set the Requirements and Design documents' `implemented` date. From that point, treat the Requirements, accepted ADR, and Design as one immutable historical snapshot. Never rewrite them to match later behavior. Create a new snapshot for later work on the same topic. Keep current behavior only in the living specs.

## Phase 3: System-grounded problem framing

After Requirements confirmation, inspect the current code and living specs. Limited background scouting may already exist, but now perform the complete repository analysis.

Capture:

- current behavior and the gap from each requirement;
- relevant ownership and lifecycle boundaries;
- reusable components and integrations;
- likely API, event, persistence, security, and migration impact;
- constraints that affect feasibility; and
- the initial design-decision backlog.

Do not treat assumptions as current behavior. Do not let existing code structure silently redefine the confirmed Requirements.

## Phase 4: ADR baseline and design decisions

Create the ADR before accepting the first design decision. The initial ADR may contain unresolved questions while discussion is active.

For Azents, create the ADR at `docs/azents/adr/{requirements-basename}.md`. Use `<snapshot>/ADR` for the document and `<snapshot>/ADR-DN` for accepted decisions. Keep all hard-to-reverse decisions for the snapshot in this one ADR. Do not allocate a new global ADR number. Existing numbered ADRs remain historical inputs and must not be renamed.

For every decision that determines architecture or product contract:

1. state the question;
2. provide realistic options and trade-offs;
3. recommend one option when evidence is sufficient;
4. obtain the decision from the user in collaborative mode or the interviewee subagent in autonomous mode; and
5. update the ADR immediately before continuing.

Use this format:

```markdown
### Decision Point: <name>

**Question**: <specific question>

**Options**
- A. <option> — pros/cons
- B. <option> — pros/cons

**Recommendation**: <recommended option and why>

Please choose A/B or adjust the direction.
```

Discuss one decision at a time. In collaborative mode, wait for the user. In autonomous mode, send each decision separately to the dedicated interviewee subagent. After acceptance, record the decision as the next `<snapshot>/ADR-DN`. Reference the affected `<snapshot>/REQ-N` items from the ADR; do not duplicate requirement text.

Once the ADR defines a coherent direction, proceed to the complete design draft.

## Phase 5: Complete design draft

Write the complete draft under the project-approved design location. For Azents, use `docs/azents/design/{requirements-basename}.md` for the primary snapshot Design. Supporting plans, audits, and validation reports keep their separate descriptive naming rules.

Reference the Requirements document rather than copying its requirements. Include a traceability matrix from `<snapshot>/REQ-N` through `<snapshot>/ADR-DN` to the proposed design mechanisms.

Include, as applicable:

- current behavior and requirement gaps;
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

Finish the full draft before reopening discussion. Record contradictions or unknowns as candidate blockers and continue using explicit assumptions. After the draft is complete, reopen only points that meet the blocker criteria.

For a design blocker, update the ADR before revising the design. For a requirement blocker, return to the user and update Requirements before the ADR or design.

## Phase 6: Feasibility check

Validate the complete draft against the real repository and product constraints. Check:

- whether every requirement has a credible implementation and verification path;
- canonical source data and projection identity;
- current code paths, ownership, and lifecycle state;
- current specs and relevant historical ADRs/designs;
- API, event, persistence, migration, and compatibility impact;
- retries, pagination, concurrency, and failure modes;
- security, permissions, and operational risks;
- existing component and integration reuse; and
- deterministic fixtures, E2E prerequisites, and evidence requirements.

Produce a compact matrix with `feasible`, `conditional`, or `blocked` results and concrete evidence for each requirement and major decision.

A point is a blocker only when leaving it unresolved would:

- contradict confirmed Requirements or an accepted ADR decision;
- make required user-visible behavior infeasible;
- require an unapproved contract, security, persistence, or ownership change;
- force mutually exclusive architecture paths;
- prevent a credible implementation or verification plan; or
- make feasibility impossible to conclude.

Local refactoring, naming, reversible polish, conventional implementation details, and bounded risks are not blockers by themselves.

Resolve requirement blockers through `Requirements → ADR → Design`. Resolve design-only blockers through `ADR → Design`. Repeat the affected feasibility checks and do not finalize while a blocker remains.

## Phase 7: Final design

Finalize only after Requirements, ADR, design, and feasibility evidence agree.

Summarize:

- the Requirements document and short ID;
- accepted ADR decisions and rejected alternatives;
- validated system and data boundaries;
- requirement-level feasibility evidence;
- remaining non-blocking risks and assumptions;
- implementation phases or why one focused PR is sufficient;
- required living-spec updates; and
- the verification plan.

Do not start implementation unless the user asks to proceed.

## Autonomous mode

Require the user to confirm the high-level Requirements before autonomy begins. The user must at least confirm the problem, primary actor, one primary scenario, expected outcome, must-have boundary, fixed constraints or non-goals, and success signal.

After confirmation:

1. launch one dedicated interviewee subagent for design decisions;
2. give it the Requirements, system framing, evidence, and current ADR state;
3. keep the same interviewee through initial decisions and later blockers; and
4. keep research subagents separate from the interviewee role.

The interviewee may critique and choose design options, but it may not add user-visible scope, alter confirmed Requirements, or edit artifacts. Return to the user for any such change.

The root agent remains responsible for research coordination, recommendations, Requirements and ADR updates, design writing, feasibility validation, and final synthesis.

## Output expectations

For interactive progress, report the current phase, what was learned, and the next action concisely.

For final output, use:

```markdown
## Design Result

- Requirements: `<path>` (`<short-id>`)
- ADR: `<path>`
- Design doc: `<path>`
- Mode: Collaborative | Autonomous
- Primary scenario: <scenario>
- Key decisions:
  - <decision and rationale>
- Feasibility:
  - <requirement-level evidence>
- Remaining non-blockers:
  - <risk or assumption>
- Next steps:
  - <implementation or review step>
```

## Guardrails

- Do not skip explicit user confirmation of high-level Requirements, even in autonomous mode.
- Do not let research subagents own or interrupt the interview.
- Do not turn benchmark patterns into requirements without user acceptance.
- Do not create an ADR before the Requirements document is confirmed.
- Do not duplicate the Requirements source of truth in the ADR or design.
- Do not create a new numbered ADR or use a different primary Design basename for an Azents development snapshot.
- Do not silently weaken a requirement to avoid a feasibility problem.
- Do not modify implemented Requirements, adopted ADRs, or implemented designs.
- Keep current behavior in `docs/azents/spec/`.
- Keep git-tracked artifacts in English.
- If the user asks to implement after final design approval, switch to the appropriate shipping workflow.
