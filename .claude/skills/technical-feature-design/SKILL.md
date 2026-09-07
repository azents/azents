---
name: technical-feature-design
description: "Requirements-first workflow for technical feature design and architecture changes. Use when converting a requester-provided product design document or a bounded technical objective into repository Requirements, material ADR decisions, an implementable Design, and authority and feasibility evidence."
---

# Technical Feature Design Workflow

Use this sequence:

```text
optional product design input
→ current-system research
→ confirmed repository Requirements
→ system framing
→ material technical-decision briefing
→ ADR decisions
→ complete implementation Design
→ authority and feasibility validation
→ Design approval
→ final Design
```

Artifact responsibilities:

- **Product design document**: optional requester-provided context describing product intent and user-visible behavior. It is not a repository artifact or implementation authority by itself.
- **Requirements**: requester-confirmed, public-safe outcomes and observable acceptance criteria for this repository snapshot.
- **ADR**: why material technical, architecture, or implementation-contract decisions were chosen.
- **Design**: how the approved intent and decisions will be implemented.
- **Spec**: how the implemented system currently behaves.

## Input routing

### When a product design document is provided

Read the supplied content before starting the Requirements interview.

1. Extract the document's stated status or approval, revision, product goal, applicable actor or system context, user-visible outcomes, required behavior and states, constraints, non-goals, acceptance criteria, and open product questions.
2. Separate explicit requester-approved intent from drafts, recommendations, assumptions, evidence, and unresolved questions.
3. Do not infer or investigate the document's authoring system, producer, storage location, or surrounding workflow.
4. Do not search for an unavailable document. Ask the requester to provide the content needed for the current decision.
5. Do not copy private provenance, private URLs, personal information, research transcripts, or other non-public evidence into repository artifacts.
6. Translate only requester-confirmed and public-safe product outcomes into Requirements.
7. Do not reopen confirmed product behavior unless repository evidence exposes a contradiction, feasibility blocker, or missing product decision.

A provided document is context until the requester confirms the repository Requirements that represent its applicable intent. After confirmation, Requirements are the product authority for this development snapshot.

### When no product design document is provided

Use a bounded Requirements interview. Confirm only information that can change the implementation contract:

- the primary user scenario or primary system outcome;
- the observable result;
- must-have scope and non-goals;
- compatibility, security, operational, and product constraints; and
- unresolved user-visible behavior that must be decided before technical design.

For infrastructure, internal tooling, migration, performance, reliability, or other primarily technical work, use one **primary system outcome** instead of inventing a user actor or journey. Supporting user or operator effects remain observable acceptance criteria when applicable.

If value, workflow, terminology, defaults, visibility, permissions as experienced by users, cancellation, or recovery behavior remains materially uncertain, brief the gap and ask the requester for the missing product decision. Do not invent product intent or invoke an undisclosed workflow.

## Modes and decision ownership

Default to **Collaborative** mode: the requester owns unresolved material decisions.
Enter **Autonomous** mode only when the requester explicitly delegates all remaining material technical decisions; use one dedicated interviewee subagent as the decision owner.

A request to decide one topic, handle implementation details, or stop asking low-level questions is scoped delegation. It does not authorize later undisclosed decisions.

Both modes keep the complete material-decision map and accepted choices visible and recorded. Both require requester confirmation of Requirements. Autonomous authority covers material technical decisions, not new product intent or user-visible behavior.

## Phase 0: Research current behavior

Before the first requirement or design question:

1. read applicable Living Specs;
2. inspect relevant code, contracts, tests, fixtures, generated surfaces, and configuration;
3. identify current behavior, terminology, ownership, lifecycle, and boundaries;
4. distinguish current behavior from the requested outcome; and
5. brief the requester on confirmed facts, input-document gaps, and material unknowns.

For a greenfield area, search for related behavior and state when none exists. Do not ask the requester for repository facts or present existing behavior as a new choice. Read historical Requirements, ADRs, and Designs only when current sources leave intent or rationale unclear.

### Research support

Use bounded research subagents when separate repository evidence lanes help. Give them the request, confirmed Requirements or current draft, fixed outcomes, unresolved assumptions, and a strict evidence-only role. Research agents do not edit artifacts or decide intent.

Benchmarking may explain established technical or interoperability conventions. It does not determine the requester's product problem, policy, fixed constraints, or desired outcome.

## Phase 1: Confirm repository Requirements

Keep the main agent as interview owner. Ask one high-value question at a time and only when its answer could change a public requirement or material technical decision.

When a product design document was supplied:

- show which outcomes are directly supported by requester-approved content;
- identify draft, missing, contradictory, confidential, or technically infeasible portions;
- ask only about gaps that matter to the repository Requirements; and
- write public-safe requirements without naming or linking the source system.

When no document was supplied, discover the bounded intent directly. Do not broaden a technical request into speculative product scope.

For Azents, read [references/requirements-template.md](references/requirements-template.md) and `docs/azents/AGENTS.md`, then create the Requirements snapshot using the required shared basename and KST creation date.

Requirements contain intent, not implementation:

- problem or technical gap;
- primary actor and scenario, or primary system outcome;
- supporting scenarios or effects;
- goals and non-goals;
- numbered requirements with observable acceptance criteria;
- fixed constraints and open assumptions; and
- requester confirmation.

Keep APIs, data models, libraries, class structure, architecture, implementation phases, and ADR decisions out of Requirements. Present the complete document and obtain explicit requester confirmation before accepting ADR decisions.

Before implementation, apply scope changes in this order:

```text
Requirements → ADR → Design
```

Return to the requester for a new actor, user-visible behavior, required scope, contract, relaxed constraint, changed success signal, or changed primary system outcome. Do not attempt to update or locate an external product document.

After verified implementation, set the matching Requirements and Design `implemented` date and treat the Requirements, accepted ADR, and Design as one immutable historical snapshot. Later changes require a new snapshot; current behavior belongs in Living Specs.

## Phase 2: Frame the system problem

After Requirements confirmation, inspect the complete affected system. Capture:

- current behavior and the gap from each requirement;
- ownership, source-of-truth, lifecycle, and interface boundaries;
- reusable components and integrations;
- implementation, contracts, state, tests, fixtures, configuration, documentation, and generated surfaces that become obsolete;
- API, event, persistence, security, migration, and operational impact;
- feasibility constraints;
- fixed or derived outcomes;
- candidate material technical decisions; and
- agent-owned local implementation categories.

Do not treat assumptions as current behavior or let existing code silently redefine confirmed Requirements.

If repository constraints require user-visible behavior not authorized by Requirements, stop that decision lane and return the exact product question and consequence to the requester. Continue independent technical research.

## Phase 3: Resolve material technical decisions

Before discussing an individual decision, brief the complete current decision map:

- **Fixed or derived outcomes**: consequences already determined by Requirements, accepted ADRs, current Specs, or project constraints. Disclose but do not reopen them.
- **Material technical decisions**: unresolved choices with materially different architecture, security, persistence, source-of-truth, ownership, lifecycle, interface, configuration, operational, failure, recovery, migration, rollout, compatibility, fallback, or authoritative-removal outcomes.
- **Product questions**: unresolved choices that would change user value, workflow, terminology, defaults, visibility, user control, or user-visible recovery. Return these to the requester and update Requirements before continuing the affected lane.
- **Agent-owned details**: identifiers, file layout, helper boundaries, equivalent local structures, fixture composition, and other local reversible choices that create no new behavior, state, configuration, contract, authority, or mode.

Track material decisions as an explicit checklist with pending, current, delegated, and accepted states.

### Decision admission

Create a technical decision point only when:

1. approved authority does not already determine the outcome;
2. at least two viable options remain;
3. those options produce materially different technical or operational outcomes; and
4. the choice is required for a coherent Design.

A consequential but fixed outcome is a briefing, not a question. A choice that fails the materiality test belongs to the agent. Do not reclassify a missing product decision as a technical choice.

### ADR recording

After the initial briefing, create the same-basename snapshot ADR before accepting the first material decision. For every material technical decision:

1. state one consequence-level question;
2. present realistic options and trade-offs;
3. recommend when evidence supports a direction;
4. obtain the choice from the current decision owner; and
5. record it immediately as the next `<snapshot>/ADR-DN` before continuing.

Discuss one decision at a time. In Collaborative mode, wait unless that exact topic was delegated. In Autonomous mode, send each technical decision separately to the dedicated interviewee. Proceed only when no material technical decision or blocking product question remains.

## Phase 4: Write the complete Design

Before writing, read [references/design-template.md](references/design-template.md) and `docs/azents/AGENTS.md`. Use the exact Requirements/ADR basename for the primary Design.

The Design must:

- trace every Requirement through accepted ADR decisions to implementation mechanisms;
- define architecture, ownership, interfaces, data, lifecycle, failures, migration, operations, observability, and verification as applicable;
- include only material mechanisms authorized by Requirements, accepted ADRs, unchanged current Specs, or project constraints;
- assign stable IDs and a Design revision to material mechanisms;
- identify removal authority, replacement boundaries, and absence evidence;
- define an E2E-first Test Strategy; and
- state assumptions and non-blocking risks without using them to create behavior or authority.

Local implementation details do not belong in the authority table. A new material technical mechanism returns to Phase 3. A new user-visible behavior returns to Requirements and requester confirmation.

Finish the full draft before reopening discussion. Continue through non-material unknowns with explicit assumptions.

## Phase 5: Validate and approve the Design

### Authority audit

Audit in both directions:

- every Requirement has a credible Design mechanism;
- every material mechanism has allowed authority;
- derived mechanisms cite all approved sources and introduce no remaining choice;
- local details create no material behavior, state, contract, authority, or mode;
- every removal has authority and a replacement or terminal boundary; and
- no unapproved second authority or optional behavior remains.

Authorization and feasibility are independent. A mechanism being common, implementable, reversible, low-risk, or non-blocking does not authorize it.

### Feasibility check

Validate each requirement and material mechanism against the real repository:

- canonical data, identity, ownership, lifecycle, and current code paths;
- API, event, persistence, migration, compatibility, concurrency, retry, and failure impact;
- security, permissions, and operational risks;
- reusable components and integrations;
- removal and absence-verification paths; and
- deterministic fixtures, E2E prerequisites, and evidence requirements.

Report `feasible`, `conditional`, or `blocked` with concrete evidence. A blocker must contradict confirmed Requirements or an accepted ADR, prevent an approved outcome, require an unapproved material change, force mutually exclusive paths, prevent a credible implementation or verification plan, or make feasibility impossible to conclude.

Resolve a user-visible feasibility conflict through requester-confirmed Requirements. Resolve a material technical conflict through ADR and Design. Then repeat affected authority and feasibility checks.

### Design approval

After both checks pass, present a compact approval brief covering:

- the material technical-decision map and owners;
- architecture, ownership, source-of-truth, and interface boundaries;
- state, configuration, runtime modes, and operational controls;
- migration, rollout, rollback, failure, retry, recovery, compatibility, and fallback behavior;
- removal and replacement obligations;
- derived material mechanisms; and
- categories of agent-owned local details.

In Collaborative mode, obtain explicit requester approval. In Autonomous mode, the dedicated interviewee approves the technical Design and the root agent reports the full brief to the requester; product-scope changes still return to the requester.

Record approval using the reference template. Approval is valid only while its Design revision and exact authority ID set match the current authority section.

## Phase 6: Finalize

Finalize only when Requirements, ADR, Design authority, feasibility evidence, and Design approval agree. Report:

- Requirements, ADR, Design, mode, and decision owner;
- whether a requester-provided product design document informed Requirements;
- accepted material technical decisions and authorities;
- removal and replacement scope;
- requirement-level feasibility evidence;
- remaining non-blocking risks;
- implementation phases or one focused PR; and
- Living Spec and verification work.

Do not include private document provenance or inaccessible links in repository artifacts or the final implementation brief. Do not start implementation until the requester asks; then switch to the appropriate shipping workflow.

## Guardrails

- Research current behavior before the first requirement or technical decision question.
- Treat a provided product design document as optional context until repository Requirements are confirmed.
- Do not search for, infer, name, or depend on the document's authoring system or producer.
- Keep private provenance, URLs, research, and personal information out of public artifacts.
- Do not ask requesters for repository facts or non-material code-shape choices.
- Confirm Requirements before ADR decisions in every mode.
- Keep product questions separate from material technical decisions.
- Brief the complete technical decision map before individual decisions and after a material change.
- Do not finalize unauthorized mechanisms or treat feasibility as authority.
- Do not proceed without revision-bound complete Design approval.
- Keep implemented Requirements, ADRs, and Designs immutable and current behavior in Living Specs.
- Keep git-tracked artifacts in English.
