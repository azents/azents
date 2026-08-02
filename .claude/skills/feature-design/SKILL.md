---
name: feature-design
description: "Requirements-first workflow for new feature design, design documents, and architecture changes. Use for collaborative or autonomous design: research current behavior, confirm Requirements, resolve material decisions in an ADR, validate Design authority and feasibility, and obtain complete Design approval."
---

# Feature Design Workflow

Use this sequence:

```text
current-system research
→ requirement interview
→ confirmed Requirements
→ system framing
→ material-decision briefing
→ ADR decisions
→ complete Design
→ authority and feasibility validation
→ Design approval
→ final Design
```

Artifact responsibilities:

- **Requirements**: what users need and how success is observed.
- **ADR**: why material architecture or product-contract decisions were chosen.
- **Design**: how approved intent and decisions will be implemented.
- **Spec**: how the implemented system currently behaves.

## Modes and decision ownership

Default to **Collaborative** mode: the requester owns unresolved material decisions.
Enter **Autonomous** mode only when the requester explicitly delegates all remaining
material design decisions; use one dedicated interviewee subagent as the decision
owner.

A request to decide one current topic, handle implementation details, or stop asking
low-level questions is scoped delegation. It does not switch the whole workflow or
authorize later undisclosed decisions.

Material-decision visibility never changes with ownership. Both modes keep the
complete material-decision map and accepted choices visible and recorded. Both
modes require requester confirmation of high-level Requirements; autonomy never
extends to product intent. The same read-only interviewee owns Autonomous decisions
through later discoveries, blockers, and final approval. The root agent retains
user communication and artifact editing.

An early request for Autonomous mode records the delegation, but do not launch the
interviewee or begin autonomous decisions until the requester confirms Requirements.

## Phase 0: Research current behavior

Before the first requirement or design question for an existing product area:

1. read applicable Living Specs;
2. inspect relevant code, contracts, tests, fixtures, and configuration;
3. identify current behavior, terminology, ownership, lifecycle, and boundaries;
4. distinguish current behavior from the requested gap; and
5. brief the requester on confirmed facts and material unknowns.

For a greenfield area, search for related behavior and state when none exists. Do
not ask the requester for repository facts or present existing behavior as a new
choice. Read historical Requirements, ADRs, and Designs only when current sources
leave intent or rationale unclear. Phase 3 still performs complete
requirement-by-requirement analysis.

### Research support

Use reusable research subagents when separate evidence lanes help. Give them the
request, current Requirements draft, confirmed facts, unresolved assumptions,
accepted or rejected directions, and a strict evidence-only role. Start bounded
scouting proactively when useful, but do not delay acknowledgement or interrupt the
current interview. Research agents do not edit artifacts or decide product intent.
Send context deltas as the interview evolves, and redirect or discard results made
stale by a changed primary scenario or accepted direction.

When the requester cannot judge a product convention, offer a scoped benchmark
study before researching. Agree on the question, targets, and comparison dimensions.
Return patterns, implications, and a recommendation, then resume the interview.
Benchmark evidence becomes intent only after requester acceptance.
Do not use benchmarking to determine the requester's actual problem, organization
policy, fixed constraints, or desired outcome.

## Phase 1: Discover Requirements

Keep the main agent as interview owner. Ask one high-value question at a time and
only when its answer could change:

- the primary actor or one primary end-to-end scenario;
- the expected outcome or observable success signal;
- must-have behavior or required scope;
- product, compatibility, security, or operational constraints; or
- non-goals and later material decisions.

Require exactly one primary scenario. Classify other scenarios as supporting,
secondary, or future scope. Skip facts already established by the request or Phase
0. Explain why a question matters and recommend a direction only when evidence is
sufficient.

Periodically summarize confirmed intent and remaining questions. When a later
answer conflicts with an earlier one, state the conflict and confirm the change.

## Phase 2: Confirm the Requirements snapshot

For Azents, read
[references/requirements-template.md](references/requirements-template.md) and
`docs/azents/AGENTS.md`, then create the Requirements snapshot using the required
shared basename and KST creation date.

Requirements contain product intent only:

- problem and user-visible goal;
- primary actor and scenario;
- supporting scenarios;
- goals and non-goals;
- numbered requirements with observable acceptance criteria;
- fixed constraints and open assumptions; and
- requester confirmation.

Keep APIs, data models, libraries, class structure, architecture, implementation
phases, and ADR decisions out of Requirements. Present the complete document and
obtain explicit requester confirmation before creating the ADR or accepting design
decisions.

Before implementation, apply scope changes in this order:

```text
Requirements → ADR → Design
```

Return to the requester for any new actor, user-visible behavior, required scope,
contract, relaxed constraint, or changed success signal, including in Autonomous
mode.

After verified implementation, set the matching Requirements and Design
`implemented` date and treat the Requirements, accepted ADR, and Design as one
immutable historical snapshot. Later changes require a new snapshot; current
behavior belongs in Living Specs.

## Phase 3: Frame the system problem

After Requirements confirmation, inspect the complete affected system. Capture:

- current behavior and the gap from each requirement;
- ownership, source-of-truth, lifecycle, and interface boundaries;
- reusable components and integrations;
- implementation, contracts, state, tests, fixtures, configuration, documentation,
  and generated surfaces that become obsolete;
- API, event, persistence, security, migration, and operational impact;
- feasibility constraints;
- fixed or derived outcomes;
- candidate material decisions; and
- agent-owned local implementation categories.

Do not treat assumptions as current behavior or let existing code silently redefine
confirmed Requirements.

## Phase 4: Resolve material decisions

Before discussing an individual decision, brief the complete current decision map:

- **Fixed or derived outcomes**: important consequences already determined by
  Requirements, accepted ADRs, current Specs, or project constraints. Disclose but
  do not reopen them.
- **Material decisions**: unresolved choices with materially different product,
  architecture, security, persistence, source-of-truth, ownership, lifecycle,
  interface, configuration, operational, failure, recovery, migration, rollout,
  compatibility, fallback, or authoritative-removal outcomes.
- **Agent-owned details**: identifiers, file layout, helper boundaries, equivalent
  local structures, fixture composition, and other local reversible choices that
  create no new behavior, state, configuration, contract, authority, or mode.
  State these categories once and do not ask about individual choices.

Track material decisions as an explicit checklist with pending, current, delegated,
and accepted states.

### Decision admission

Create a decision point only when:

1. approved authority does not already determine the outcome;
2. at least two viable options remain;
3. those options produce materially different outcomes; and
4. the choice is required for a coherent Design.

A consequential but fixed outcome is briefing, not a question. A choice that fails
the materiality test belongs to the agent. Frame decisions at the consequence
level and bundle dependent parameters; do not split code-shape details into
requester questions.

### Visibility, delegation, and ADR recording

Keep material decisions visible regardless of owner:

- the requester owns them in Collaborative mode;
- delegating one topic applies only to that topic;
- delegating local details applies only to the stated agent-owned categories; and
- the interviewee owns them in Autonomous mode.

When research or an accepted choice changes the material-decision map, re-brief the
complete map before continuing. Earlier scoped delegation does not cover a new
topic. Never silently append or adopt a material decision.

After the initial briefing, create the same-basename snapshot ADR before accepting
the first decision. For every material decision:

1. state one consequence-level question;
2. present realistic options and trade-offs;
3. recommend when evidence supports a direction;
4. obtain the choice from the current decision owner; and
5. record it immediately as the next `<snapshot>/ADR-DN` before continuing.

Discuss one decision at a time. In Collaborative mode, wait unless that exact topic
was delegated. In Autonomous mode, send each decision separately to the dedicated
interviewee. Reference affected Requirements instead of duplicating them in the
ADR. Proceed only when the material-decision map has no unresolved item.

## Phase 5: Write the complete Design

Before writing, read
[references/design-template.md](references/design-template.md) and
`docs/azents/AGENTS.md`. Use the exact Requirements/ADR basename for the primary
Design.

The Design must:

- trace every Requirement through accepted ADR decisions to implementation
  mechanisms;
- define architecture, ownership, interfaces, data, lifecycle, failures,
  migration, operations, observability, and verification as applicable;
- include only material mechanisms authorized by Requirements, accepted ADRs,
  unchanged current Specs, or project constraints;
- assign stable IDs and a Design revision to material mechanisms;
- identify removal authority, replacement boundaries, and absence evidence;
- define an E2E-first Test Strategy; and
- state assumptions and non-blocking risks without using them to create behavior or
  authority.

Local implementation details do not belong in the authority table. When a
mechanism combines approved sources, cite them all; synthesis and Design approval
do not create authority. A new material mechanism returns to Phase 4 before it
enters Design.

Finish the full draft before reopening discussion. Continue through non-material
unknowns with explicit assumptions; return any new product scope to Requirements
and any new material choice to the ADR flow.

## Phase 6: Validate and approve the Design

### Authority audit

Audit in both directions:

- every Requirement has a credible Design mechanism;
- every material mechanism has allowed authority;
- derived mechanisms cite all approved sources and introduce no remaining choice;
- local details create no material behavior, state, contract, authority, or mode;
- every removal has authority and a replacement or terminal boundary; and
- no unapproved second authority or optional behavior remains.

Authorization and feasibility are independent. A mechanism being common,
implementable, reversible, low-risk, or non-blocking does not authorize it.
Resolve authority failures through Requirements, ADR, or removal from Design.

### Feasibility check

Validate each requirement and material mechanism against the real repository:

- canonical data, identity, ownership, lifecycle, and current code paths;
- API, event, persistence, migration, compatibility, concurrency, retry, and
  failure impact;
- security, permissions, and operational risks;
- reusable components and integrations;
- removal and absence-verification paths; and
- deterministic fixtures, E2E prerequisites, and evidence requirements.

Report `feasible`, `conditional`, or `blocked` with concrete evidence. A blocker
must contradict confirmed Requirements or an accepted ADR, prevent an approved
outcome, require an unapproved material change, force mutually exclusive paths,
prevent a credible implementation or verification plan, or make feasibility
impossible to conclude. Local naming, refactoring, polish, and bounded risk are not
feasibility blockers and do not create authority.

Resolve requirement blockers through `Requirements → ADR → Design` and design
blockers through `ADR → Design`, then repeat affected authority and feasibility
checks.

### Design approval

After both checks pass, present a compact approval brief covering:

- the material-decision map and owners;
- architecture, ownership, source-of-truth, and interface boundaries;
- state, configuration, runtime modes, and operational controls;
- migration, rollout, rollback, failure, retry, recovery, compatibility, and
  fallback behavior;
- removal and replacement obligations;
- derived material mechanisms; and
- categories of agent-owned local details.

In Collaborative mode, obtain explicit requester approval. Scoped delegation does
not replace complete Design approval. In Autonomous mode, the dedicated interviewee
approves the Design and the root agent reports the full brief to the requester;
product-scope changes still return to the requester.

Record approval using the reference template. Approval is valid only while its
Design revision and exact authority ID set match the current authority section. A
later material change invalidates approval and repeats the affected authority,
feasibility, and approval steps.

## Phase 7: Finalize

Finalize only when Requirements, ADR, Design authority, feasibility evidence, and
Design approval agree. Report:

- Requirements, ADR, Design, mode, and decision owner;
- accepted material decisions and authorities;
- removal and replacement scope;
- requirement-level feasibility evidence;
- remaining non-blocking risks;
- implementation phases or one focused PR; and
- living-spec and verification work.

Do not start implementation until the requester asks. Then switch to the appropriate
shipping workflow.

## Guardrails

- Research current behavior before the first requirement or design question.
- Do not ask requesters for repository facts or non-material code-shape choices.
- Confirm Requirements before ADR decisions in every mode.
- Keep research evidence separate from product intent and decision ownership.
- Brief the complete material-decision map before individual decisions and after
  any material change.
- Scoped delegation never hides or authorizes later material topics.
- Do not finalize unauthorized mechanisms or treat feasibility as authority.
- Do not proceed without revision-bound complete Design approval.
- Keep implemented Requirements, ADRs, and Designs immutable and current behavior
  in Living Specs.
- Keep git-tracked artifacts in English.
