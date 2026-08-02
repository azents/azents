---
name: feature-design
description: "Requirements-first workflow for new feature design, design documents, and architecture changes. Use for collaborative or autonomous design: research current Living Specs and code before interviewing the user, confirm high-level requirements, preserve an immutable requirements snapshot, use reusable research subagents without blocking the conversation, record design decisions in an ADR, validate repository feasibility, and produce an implementable final design."
---

# Feature Design Workflow

Use this sequence:

```text
pre-interview current-system research
→ requirement interview
→ confirmed Requirements snapshot
→ system-grounded problem framing
→ complete material-decision briefing
→ ADR decisions
→ complete design draft
→ design authority audit
→ feasibility validation
→ design approval
→ final design
```

Keep each artifact's responsibility distinct:

- **Requirements**: what users need and how success is observed.
- **ADR**: why material architecture or product-contract decisions were chosen.
- **Design**: how the system will satisfy the requirements and ADR decisions.
- **Spec**: how the implemented system currently behaves.

## Modes

| User request | Mode |
| --- | --- |
| "Design this", "write a design doc" | **Collaborative**: discuss design decisions with the user |
| Explicitly delegate all remaining material design decisions | **Autonomous**: discuss design decisions with a dedicated interviewee subagent |

Default to collaborative mode. A request to decide one current point, choose local
implementation details, or stop asking low-level questions does not switch the
whole workflow to autonomous mode. Only explicit delegation of all remaining
material design decisions does.

Both modes require the user to confirm the high-level Requirements before design
decisions begin. Autonomous mode delegates decision ownership, not material
decision visibility or product intent.

## Phase 0: Pre-interview current-system research

After restating the request and before asking the first requirement or design question,
research the current product behavior:

1. read the applicable Living Specs first;
2. inspect the relevant code paths, contracts, tests, fixtures, and configuration;
3. identify the current terminology, ownership, lifecycle, and user-visible behavior;
4. distinguish behavior that already exists from the requested gap; and
5. record evidence-backed unknowns that genuinely require requester intent.

This phase is mandatory for changes to an existing product area. For a genuinely
greenfield area, search for related specs and code, then state that no current
implementation was found.

Use the findings to avoid presenting existing behavior as a new option or asking the
requester to supply facts available from the repository. Before the first interview
question, give a concise briefing of the confirmed current behavior, the requested
gap, and any material uncertainty. Ask only a question that remains after this
research and could change the user-visible contract or scope.

Read historical Requirements, ADRs, and Designs only when current specs or code leave
product intent or rationale unclear. This preliminary research grounds the interview;
Phase 3 remains the complete requirement-by-requirement system analysis.

## Phase 1: Requirement discovery

Keep the main agent as the interview owner. Use the Phase 0 evidence to distinguish
known facts from assumptions, and ask one high-value question at a time.

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

Start limited, reversible scouting proactively when it will prepare better questions,
but never wait for it before acknowledging the request and briefing the user. This
does not relax Phase 0: do not ask the first interview question until the required
current-system research is complete. Do not interrupt the current topic merely
because later background research completed. Keep results in the main agent's
research context until they naturally support the current or next question.

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
- existing implementation, contracts, state, tests, fixtures, configuration, and
  documentation that the change supersedes or makes obsolete;
- likely API, event, persistence, security, and migration impact;
- constraints that affect feasibility; and
- fixed or derived design outcomes;
- candidate material decisions; and
- categories of local implementation detail the agent will own.

Do not treat assumptions as current behavior. Do not let existing code structure silently redefine the confirmed Requirements.

## Phase 4: Material decision backlog, authority baseline, and ADR discussion

Before discussing any individual decision, present the complete current material
decision map. Separate it into:

- **Fixed or derived outcomes**: important consequences already determined by
  confirmed Requirements, accepted ADR decisions, current Specs, or project
  constraints. Brief them without reopening them.
- **Material decisions**: unresolved choices whose viable options produce
  materially different product, architecture, security, persistence, source of
  truth, ownership, lifecycle, API or event boundary, configuration, operational
  mode, failure or recovery, migration, rollout, compatibility, fallback, or
  removal of an authoritative behavior, contract, persisted state,
  source-of-truth path, or operational mode. Keep these visible as an explicit
  checklist with pending, current, delegated, and accepted items.
- **Agent-owned implementation categories**: identifiers, file layout, helper
  boundaries, equivalent local data structures, fixture composition, and other
  local reversible choices that create no new behavior, state, configuration,
  contract, authority, or operational mode. State these categories once; do not
  enumerate or ask about individual choices.

Admit a requester decision point only when all of these are true:

1. confirmed authority does not already determine the outcome;
2. at least two viable options remain;
3. the options create materially different outcomes on one of the boundaries
   above; and
4. the choice must be resolved to produce a coherent Design.

An important consequence with only one authorized outcome belongs in the fixed or
derived briefing, not the decision backlog. A local choice that fails the
materiality test belongs to the agent and must not become a requester question.

Frame each decision as one consequence-level topic. Bundle dependent parameters
that determine the same outcome. Do not split identifiers, filenames, class or
function boundaries, library mechanics, or equivalent code-shape choices into
separate questions unless the requester explicitly made them part of the product
contract.

Material decision visibility and decision ownership are separate:

- In collaborative mode, the requester owns unresolved material decisions.
- Delegating the current decision applies only to that named topic.
- Delegating local details applies only to the agent-owned categories.
- Neither scoped delegation changes the workflow mode or authorizes undisclosed
  later material decisions.
- In autonomous mode, the dedicated interviewee owns unresolved material
  decisions, but the complete material decision map and every accepted choice
  remain visible and recorded.

If later research, an accepted decision, or a blocker adds, removes, splits, or
reorders a material decision, update and re-brief the complete map before
continuing. Previous delegation does not cover a newly discovered topic unless
the user explicitly delegated all remaining material decisions. Do not silently
append or adopt a material decision.

After the backlog briefing, create the ADR before accepting the first design
decision. The initial ADR may contain the unresolved backlog while discussion is
active.

For Azents, create the ADR at `docs/azents/adr/{requirements-basename}.md`.
Use `<snapshot>/ADR` for the document and `<snapshot>/ADR-DN` for accepted
decisions. Keep all material decisions for the snapshot in this one ADR. Do not
allocate a global ADR number. Legacy numbered ADRs are historical inputs only and
are not valid current ADR files after migration.

For every material decision:

1. state the question;
2. provide realistic options and trade-offs;
3. recommend one option when evidence is sufficient;
4. obtain the decision from its current owner; and
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

Discuss one material decision at a time. In collaborative mode, wait for the user
unless that exact topic was delegated. In autonomous mode, send each decision
separately to the dedicated interviewee subagent. After acceptance, record the
decision as the next `<snapshot>/ADR-DN`. Reference the affected
`<snapshot>/REQ-N` items from the ADR; do not duplicate requirement text.

Proceed to the complete design draft only when the material decision map has no
unresolved item.

## Phase 5: Complete design draft

Write the complete draft under the project-approved design location. For Azents, use `docs/azents/design/{requirements-basename}.md` for the primary snapshot Design. Supporting plans, audits, and validation reports keep their separate descriptive naming rules.

Reference the Requirements document rather than copying its requirements. Include
forward traceability from `<snapshot>/REQ-N` through `<snapshot>/ADR-DN` to the
proposed design mechanisms.

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

Every primary Design must also include reverse authority traceability:

```markdown
## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | ... | ... | `required | decided | existing | derived` |
```

Include only material mechanisms, not every local implementation choice. Each row
must trace to confirmed Requirements, an accepted ADR decision, an unchanged
current Spec, or a project constraint. When a mechanism is derived from multiple
sources, cite each source and include the resulting synthesis in final approval.
Design synthesis and approval do not create authority or replace a Requirement or
ADR decision.

Use stable document-local IDs. Keep an unchanged mechanism's ID across revisions,
allocate a new ID for a new mechanism, and do not reuse a removed ID. Increment
the Design revision whenever a material mechanism or its authority changes.

Classify each mechanism as:

- `required`: directly required by confirmed Requirements;
- `decided`: selected by an accepted ADR decision;
- `existing`: retained from an unchanged current Spec or project constraint; or
- `derived`: necessary synthesis of multiple approved sources with no remaining
  material choice.

Do not introduce a material mechanism as an assumption, conventional detail,
rollout precaution, risk mitigation, fallback, or feasibility fix. If it lacks
authority, return it to the material decision map before treating it as Design.

Every primary Design must include this section:

```markdown
## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |
```

Cover obsolete code, contracts, state, tests, fixtures, configuration,
documentation, and generated surfaces as applicable. A replacement may be
`None` when the behavior disappears entirely. Use an explicit `None` finding
only after system-grounded analysis finds no removal obligations. Treat every
identified removal as part of the design deliverable rather than optional later
cleanup.

Finish the complete draft before reopening discussion. Record contradictions or
unknowns as candidate blockers and continue using explicit assumptions that do
not create behavior or authority. If the draft reveals a new material decision,
update and resolve the material decision map before continuing.

## Phase 6: Design authority audit

Audit the complete draft in both directions:

- every confirmed Requirement has a Design mechanism;
- every material Design mechanism has an allowed authority;
- every material synthesis derived from approved sources is explicit;
- agent-owned local details do not create a new runtime branch, state,
  configuration, contract, fallback, compatibility path, failure behavior,
  operational responsibility, or source of truth;
- every removal has authority and a replacement or terminal boundary; and
- no unapproved second authority or optional behavior remains.

Authorization and feasibility are separate. A mechanism being implementable,
reversible, common, low-risk, or non-blocking does not authorize it.

Resolve an authority failure through:

```text
product scope change → Requirements
material design decision → ADR
unsupported mechanism → remove from Design
```

Do not continue while the authority audit has an unresolved or pending item.

## Phase 7: Feasibility check

Validate the complete draft against the real repository and product constraints. Check:

- whether every requirement has a credible implementation and verification path;
- canonical source data and projection identity;
- current code paths, ownership, and lifecycle state;
- current specs and relevant historical ADRs/designs;
- API, event, persistence, migration, and compatibility impact;
- whether every removal has a credible call-site, dependency, data, migration,
  test, fixture, generated-artifact, and spec cleanup path as applicable;
- whether absence verification proves that no superseded path remains as an
  unapproved second authority or compatibility fallback;
- retries, pagination, concurrency, and failure modes;
- security, permissions, and operational risks;
- existing component and integration reuse; and
- deterministic fixtures, E2E prerequisites, and evidence requirements.

Produce a compact matrix with `feasible`, `conditional`, or `blocked` results and concrete evidence for each requirement and major decision.

A point is a feasibility blocker only when leaving it unresolved would:

- contradict confirmed Requirements or an accepted ADR decision;
- make required user-visible behavior infeasible;
- require an unapproved contract, security, persistence, or ownership change;
- force mutually exclusive architecture paths;
- prevent a credible implementation or verification plan; or
- make feasibility impossible to conclude.

Local refactoring, naming, reversible polish, conventional implementation
details, and bounded risks are not feasibility blockers by themselves. This
classification does not grant Design authority.

Resolve requirement blockers through `Requirements → ADR → Design`. Resolve design-only blockers through `ADR → Design`. Repeat the affected feasibility checks and do not finalize while a blocker remains.

## Phase 8: Design approval

After the authority audit and feasibility check pass, present a compact approval
brief covering:

- the complete material decision map and decision owners;
- architecture, ownership, source-of-truth, and interface boundaries;
- new state, configuration, runtime modes, and operational controls;
- migration, rollout, rollback, failure, retry, and recovery behavior;
- compatibility and fallback behavior;
- removal and replacement obligations;
- material Design syntheses derived from multiple approved sources; and
- categories of local implementation detail the agent will own.

In collaborative mode, obtain explicit requester approval of the complete Design.
Scoped delegation of individual decisions or local details does not replace this
approval. In autonomous mode, have the dedicated interviewee approve the complete
Design and report the full approval brief to the user. Product-scope changes still
return to the requester.

Record the approval in the Design:

```markdown
## Design Approval

- Mode: `Collaborative | Autonomous`
- Decision owner: `<requester or interviewee>`
- Approved on: `YYYY-MM-DD`
- Approved Design revision: `<revision>`
- Approved authority IDs: `<exact ID set>`
- Approved scope: `<material Design summary>`
```

Any material change after approval reopens the affected
`Requirements → ADR → Design` path and requires a new authority audit,
feasibility check, and Design approval. The approval is valid only when its
revision and exact authority ID set match the current `Design Authority` section.

## Phase 9: Final design

Finalize only after Requirements, ADR, Design authority, feasibility evidence, and
Design approval agree.

Summarize:

- the Requirements document and short ID;
- accepted ADR decisions and rejected alternatives;
- Design approval mode and decision owner;
- material Design mechanisms and their authorities;
- validated system and data boundaries;
- planned removals, replacement authorities, and absence evidence;
- requirement-level feasibility evidence;
- remaining non-blocking risks and assumptions;
- implementation phases or why one focused PR is sufficient;
- required living-spec updates; and
- the verification plan.

Do not start implementation unless the user asks to proceed.

## Autonomous mode

Enter autonomous mode only when the user explicitly delegates all remaining
material design decisions. A local request such as "choose this", "handle the
details", or "stop asking low-level questions" remains scoped and does not change
the mode.

Require the user to confirm the high-level Requirements before autonomy begins.
The user must at least confirm the problem, primary actor, one primary scenario,
expected outcome, must-have boundary, fixed constraints or non-goals, and success
signal.

After confirmation:

1. launch one dedicated interviewee subagent for design decisions;
2. give it the Requirements, system framing, evidence, and current ADR state;
3. keep the same interviewee through initial decisions, later material decisions,
   blockers, and final Design approval; and
4. keep research subagents separate from the interviewee role.

The interviewee may critique and choose visible material design options, but it
may not add user-visible scope, alter confirmed Requirements, hide material
decisions, or edit artifacts. Return to the user for any product-scope change.

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
- Design approval: `<mode, decision owner, date>`
- Key decisions:
  - <decision and rationale>
- Design authority:
  - <material mechanism and authority>
- Removal and replacement:
  - <obsolete unit, replacement authority, removal boundary, and absence evidence>
- Feasibility:
  - <requirement-level evidence>
- Remaining non-blockers:
  - <risk or assumption>
- Next steps:
  - <implementation or review step>
```

## Guardrails

- Do not ask the first requirement or design question before researching applicable
  Living Specs and relevant code.
- Do not ask the requester to resolve current-system facts that repository evidence
  can answer.
- Do not skip explicit user confirmation of high-level Requirements, even in autonomous mode.
- Do not let research subagents own or interrupt the interview.
- Do not turn benchmark patterns into requirements without user acceptance.
- Do not create an ADR before the Requirements document is confirmed.
- Do not begin individual ADR decision discussion before briefing the complete
  current material decision map.
- Do not ask the requester to choose identifiers, file layout, helper boundaries,
  equivalent local data structures, fixture names, or other non-material code
  shape.
- Do not treat scoped delegation as permission to hide or decide later material
  topics.
- Do not finalize a Design with an unauthorized material mechanism.
- Do not treat feasibility, reversibility, convention, or low risk as Design
  authority.
- Do not proceed without complete Design approval.
- Do not duplicate the Requirements source of truth in the ADR or design.
- Do not create or retain a numbered ADR file, or use a different primary Design basename, for an Azents development snapshot. Legacy numbered ADRs may appear only in explicit historical provenance or ambiguity records.
- Do not silently weaken a requirement to avoid a feasibility problem.
- Do not modify implemented Requirements, adopted ADRs, or implemented designs.
- Keep current behavior in `docs/azents/spec/`.
- Keep git-tracked artifacts in English.
- If the user asks to implement after final design approval, switch to the appropriate shipping workflow.
