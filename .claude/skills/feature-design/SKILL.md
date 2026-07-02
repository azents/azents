---
name: feature-design
description: "Workflow for new feature design, design documents, and architecture changes that need technical decisions. Move through discussion, draft, validation, and final design."
---

# Feature Design Workflow

Use this four-phase framework when designing a new feature: discussion → draft → validation → final design. Facts found in later phases may overturn earlier decisions.

## When to use

- The user asks to design a new feature or write a design document.
- The request combines design work with a future implementation PR.
- The change requires architecture or technical decision making.

## Modes

| User request | Mode |
| --- | --- |
| "Design this", "write a design doc" | **Collaborative** by default |
| "Proceed autonomously", "handle it yourself", "decide and continue" | **Autonomous** |

Default to **collaborative mode** unless the user explicitly asks for autonomous execution. Design usually needs user domain knowledge and product judgment.

## Collaborative mode

Discuss one decision point at a time and wait for the user's answer before moving on.

### Execution environment

| Environment | Detection | Phase 1.5 behavior |
| --- | --- | --- |
| Interactive session | Direct terminal/IDE conversation | Present one point at a time and wait for the user |
| GitHub Discussion | Triggered from a Discussion comment | Post each point as a separate comment so each can be discussed independently |
| GitHub Issue/PR | Triggered from an Issue/PR comment | Same as interactive: one point at a time |

### Phase 1: Problem framing

Capture:

- User-visible goal
- Current behavior and pain point
- Non-goals
- Constraints and compatibility expectations
- Systems, files, APIs, and data models likely affected

Do not propose implementation yet. First ensure the problem is understood.

### Phase 1.5: Decision-point discussion

Identify the decisions that determine the design. For each point:

1. State the question.
2. Provide realistic options.
3. Explain trade-offs.
4. Recommend one option when there is enough evidence.
5. Ask the user to confirm or choose.

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

Proceed only after the user answers, unless autonomous mode is active.

### Phase 2: Draft design

Write a draft design document under the project-approved design location. For Azents, use `docs/azents/design/` unless a more specific repository rule applies.

The draft should include:

- Problem and goals
- Non-goals
- Current behavior
- Proposed design
- API/data model changes
- Runtime or lifecycle behavior
- Error handling
- Security and permissions
- Migration or rollout plan
- Test strategy
- Open questions
- Alternatives considered

Keep the design clear enough that another engineer can implement from it.

### Phase 3: Validation

Validate the draft against the repository and product constraints.

Check:

- Existing code paths and ownership boundaries
- Current specs in `docs/azents/spec/`
- Relevant ADRs and implemented design documents
- Failure modes, rollback paths, and operational risks
- Testability and fixture requirements
- Whether the decision is hard to reverse and needs an ADR

If validation finds a contradiction, update the draft and call out the changed decision.

### Phase 4: Final design

Produce the final design document and summarize:

- Accepted decisions
- Rejected alternatives
- Remaining risks
- Implementation phases
- Required spec updates
- Whether an ADR is required

Do not start implementation unless the user asks to proceed.

## Autonomous mode

When the user explicitly asks for autonomous design, run every phase without pausing for each decision. Still record decision points and mark the chosen option as the recommendation.

Autonomous output should include:

- The final design document path
- Key decisions and rationale
- Validation evidence
- Open risks or assumptions
- Proposed implementation plan

## ADR guidance

Create or propose an ADR when the design makes a hard-to-reverse decision, changes a system boundary, introduces a persistent data contract, or establishes a long-term operational policy.

ADR files belong under `docs/azents/adr/` and should be append-only once adopted or implemented.

## Output expectations

For interactive progress updates, keep responses short and focused on the current decision. For final output, include:

```markdown
## Design Result

- Design doc: `<path>`
- Mode: Collaborative | Autonomous
- Key decisions:
  - <decision and rationale>
- Validation:
  - <checks performed>
- Next steps:
  - <implementation or review step>
```

## Guardrails

- Do not invent current behavior; inspect code and specs.
- Do not overwrite implemented design history as if it were a living spec.
- Keep current behavior in `docs/azents/spec/`.
- Keep PR-facing and document text in English.
- If the user asks to implement after design approval, switch to the shipping workflow instead of mixing design and implementation in this skill.
