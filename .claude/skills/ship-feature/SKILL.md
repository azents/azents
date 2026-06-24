---
name: ship-feature
description: "기능 설계 논의 완료 후, 설계 문서 → 구현 계획 → phase별 구현을 stacked PR로 쌓아서 ship하는 워크플로우. 사용 시점: (1) 설계 논의가 끝나고 구현 단계로 넘어갈 때, (2) '이제 구현하자', 'ship-feature', (3) 설계 문서가 있고 이를 코드로 만들어야 할 때."
---

# Feature Ship 워크플로우

설계 논의 완료 후, stacked PR로 설계 문서 → 구현 계획 → phase별 구현 → 정리까지 **전부 한번에** 만든다.

## PR 스택 구조

```
main ← design-doc ← impl-plan ← phase1 ← phase2 ← ... ← verification ← spec-promotion ← cleanup
```

| 순서 | PR | 내용 |
|------|-----|------|
| 1 | 설계 문서 | `docs/` 아래 설계 문서 |
| 2 | 구현 계획 | multi-phase 계획 — **project-approved `plans/` 위치에 작성한다. nointern 은 `docs/nointern/plans/` 에 multi-phase/phase plan 문서를 작성한다.** 추가/변경된 기능 전부에 대한 E2E primary 검증 매트릭스와 testenv fixture/prerequisite support 필요 여부 포함 필수 |
| 3~N-3 | phase별 구현 | 각 phase 상세 구현 계획 + 코드 + 테스트 (frontend UI가 있으면 구현 phase 중 하나로 포함) |
| N-2 | E2E/testenv 검증 | 계획에 명시된 E2E 와 testenv fixture/prerequisite support 검증 전체 실행 + 실행 명령/환경/증거가 포함된 세부 리포트 + **관련 current spec 을 구현 diff와 strict 대조하여 구현 누락/spec drift 표 작성** + 발견된 이슈 즉시 수정 (반복 루프) |
| **N-1** | **spec-promotion** | **`/spec-review` + design implemented 확정 + spec 갱신 + ADR 후보 제안** |
| N | cleanup | 구현 완료 후 stale한 phase별 plan 문서 제거 |

## PR 제목 규칙

시리즈 PR임을 알 수 있도록 **통일된 prefix**를 사용한다:

```
{feature-name} [1/N]: 설계 문서
{feature-name} [2/N]: 구현 계획
{feature-name} [3/N]: Phase 1 — {phase 설명}
{feature-name} [4/N]: Phase 2 — {phase 설명}
...
{feature-name} [N-2/N]: Phase X — E2E/testenv verification
{feature-name} [N-1/N]: Phase X+1 — spec impact + promotion
{feature-name} [N/N]: Phase X+2 — cleanup
```

예시:
```
shared-storage [1/9]: 설계 문서
shared-storage [2/9]: 구현 계획
shared-storage [3/9]: Phase 1 — Storage 인프라
shared-storage [4/9]: Phase 2 — 파일 도구
shared-storage [5/9]: Phase 3 — 스킬 시스템
shared-storage [7/10]: Phase 5 — 사용자 제어 UI
shared-storage [8/10]: Phase 6 — E2E/testenv verification
shared-storage [9/10]: Phase 7 — spec impact + promotion
shared-storage [10/10]: Phase 8 — cleanup
```

N은 전체 PR 수. 중간에 PR이 추가/삭제되면 번호를 조정하지 않아도 된다.

## 워크플로우

각 phase 브랜치가 준비되는 즉시 `/ship-pr`로 PR을 열고, CI/리뷰 완료를 기다리지 않고 다음 phase 브랜치 작성으로 진행한다.

### 1. ADR + 설계 문서 PR

설계 단계는 `designer` subagent 에 위임한다. 목표는 `/feature-design` 에서 논의·합의된 주요 결정을 ADR로 먼저 기록하고, 그 결정을 근거로 기능의 목표 상태를 독립적으로 이해 가능한 설계 문서로 고정하는 것이다. 구현 계획은 이 단계의 대상이 아니다.

`designer` 에게 전달할 입력:

- 사용자와 합의한 기능 목표
- `/feature-design` 에서 논의된 결정, trade-off, rejected option, 사용자 합의 내용
- 관련 기존 discussion, ADR, design, spec 문서 경로
- 관련 코드 영역 또는 탐색해야 할 키워드
- ADR 출력 경로: `docs/{project}/adr/NNNN-{decision-slug}.md`
- 설계 문서 출력 경로: `docs/{project}/design/{feature}.md`
- 구현 계획은 다음 phase에서 작성하므로 phase 분할, 작업 순서, 파일별 checklist, testenv fixture/prerequisite support 목록은 제외한다는 제약

`designer` 완료 기준:

- `/feature-design` 에서 합의된 주요 architecture/product decision이 ADR로 기록되어 있다.
- ADR에는 context, decision, considered options, consequences가 포함되어 있다.
- 설계 문서만 읽고도 새 세션이 구현 계획을 작성할 수 있다.
- 설계 문서는 관련 ADR을 근거 문서로 링크한다.
- ADR decision은 안정적인 ID로 참조 가능해야 한다. 예: `ADR-0012-D1`.
- 설계 문서에는 `## Requirements` 섹션이 있고, 각 requirement는 related decisions와 acceptance criteria를 포함한다.
- 설계 문서에는 `## Decision Table` 섹션이 있고, 모든 ADR decision이 최소 하나 이상의 requirement에 매핑되어 있다.
- 문제 정의, 목표/비목표, 현재 상태, 목표 상태, 사용자-visible behavior, 데이터/상태/API/권한/외부 연동 변화, 운영 prerequisite, rollout/failure mode, Test Strategy, acceptance criteria가 문서화되어 있다.
- nointern 설계의 Test Strategy 는 E2E primary 검증, testenv fixture/prerequisite support 필요 여부와 이유, fixture/seed, credential/prerequisite snapshot, evidence, CI 정책을 포함한다.
- 설계 문서에는 `## QA Checklist` 가 있고, 각 항목은 `What to check`, `Why it matters`, `How to check`, `Expected result`, `Execution result`, `Fixes applied` 를 가진다.
- 설계 PR 단계에서 `Execution result` 와 `Fixes applied` 는 `TBD` 로 남긴다. 실제 실행 기록은 verification phase 가 채운다.
- open question과 사용자 결정 필요 항목이 확정 사실과 분리되어 있다.
- 설계 목표나 acceptance criteria가 사용자 합의 없이 축소되지 않았다.

호출 prompt 예시:

```text
Use the `designer` subagent for this phase.

You are responsible for the ADR + design phase of `/ship-feature`.

Create ADR(s) for decisions already made during `/feature-design`, then create or update the design document for `{feature}` at `{design_doc_path}`.

Inputs:
- Feature goal: `{feature_goal}`
- Feature-design decisions and trade-offs: `{feature_design_summary}`
- Existing context: `{context_paths}`
- Relevant code areas or keywords: `{code_hints}`

Requirements:
- Write ADR(s) first for accepted decisions from `/feature-design`. Do not invent new decisions.
- Each ADR must include context, decision, considered options, and consequences.
- Use the next available ADR number under `docs/{project}/adr/`.
- Give each ADR decision a stable ID that the design document can reference, such as `ADR-0012-D1`.
- Write a design document, not an implementation plan.
- Link the relevant ADR(s) from the design document.
- Include `## Requirements`. Each requirement must have an ID, related ADR decision IDs, and acceptance criteria.
- Include `## Decision Table` immediately after requirements. It must map each ADR decision ID back to one or more requirements; no ADR decision may be unmapped.
- The document must be detailed enough that a fresh session can read only this document and write the implementation plan.
- Include problem/background, goals, non-goals, current state, target state, user-visible behavior, data/state/API/permission/external-system changes, operational prerequisites, rollout/failure modes, and acceptance criteria.
- Include `## QA Checklist` with one section per required verification item. Each item must state what is checked, why it matters, how it will be checked, and expected result; leave execution result and fixes applied as `TBD`.
- Do not include phase breakdown, task ordering, file-by-file checklist, implementation checklist, or testenv fixture/prerequisite support list.
- Use `explore` subagents when codebase investigation is broad.
- If you find missing prerequisites, architectural gaps, or uncertain decisions, separate them as open questions or user decisions. Do not silently reduce scope.
- Modify only the ADR(s), the design document, and any directly related documentation needed to make the design self-contained.
```

ADR과 설계 문서 작성 후 해당 문서만 커밋하고 `/ship-pr` 로 PR을 연다. PR 생성 후 리뷰/CI를 기다리지 않고 구현 계획 PR로 진행한다.

### 2. Multi-phase Plan PR

Multi-phase plan 단계는 `designer` subagent 에 위임한다. 목표는 설계 문서를 구현 상세로 바로 풀어 쓰는 것이 아니라, stacked PR 시리즈의 phase 경계와 phase 간 연결을 설계하는 것이다.

Multi-phase plan 문서는 project-approved planning 위치에 저장한다.
nointern 에서는 `docs/nointern/plans/` 아래에 multi-phase plan 과 phase plan 을 작성한다.

`designer` 에게 전달할 입력:

- 확정된 설계 문서 경로: `docs/{project}/design/{feature}.md`
- 관련 기존 discussion, plan, spec 문서 경로
- 관련 코드 영역 또는 탐색해야 할 키워드
- PR 스택 규칙: `main ← design-doc ← impl-plan ← phase1 ← phase2 ← ... ← verification ← spec-promotion ← cleanup`
- 구현 계획 출력 위치: project rule 을 따른다. nointern 의 multi-phase plan 과 phase별 상세 구현 계획은 `docs/nointern/plans/` 아래에 둔다.
- 각 phase의 상세 구현 계획은 해당 phase PR에서 별도 phase 상세 구현 계획으로 작성한다는 제약. nointern 에서는 `docs/nointern/design/` 에 phase plan 을 두지 않는다.
- 추가/변경된 기능 전체를 커버하는 E2E primary 검증 매트릭스와 testenv fixture/prerequisite support 필요 여부를 반드시 포함한다는 제약

`designer` 완료 기준:

- 설계 문서의 requirements와 acceptance criteria가 phase 경계 안에 빠짐없이 배치되어 있다.
- 각 phase는 담당하는 requirement를 명시한다.
- multi-phase plan에는 requirement table이 있고, 각 requirement가 어떤 phase에 매핑되는지 정의한다.
- 각 phase는 이전 phase에서 무엇을 받아 다음 phase에 무엇을 제공하는지 명확하다.
- 각 phase는 독립 PR로 review 가능한 크기와 책임을 가진다.
- phase 간 dependency, base branch 관계, rebase/cascade 영향이 명확하다.
- 각 phase의 완료 상태가 “다음 phase가 시작할 수 있는 조건”으로 표현되어 있다.
- 각 phase의 상세 구현 계획은 작성하지 않고, 해당 phase에서 작성할 phase 상세 구현 계획의 scope만 정의한다.
- E2E/testenv 검증 phase에서 실행할 E2E 와 fixture/prerequisite doctor 항목이 happy path, edge case, regression을 포함한다.
- blocker, missing prerequisite, external/manual action이 있으면 어느 phase 전에 해결되어야 하는지 분리되어 있다.

호출 prompt 예시:

```text
Use the `designer` subagent for this phase.

You are responsible for the multi-phase planning phase of `/ship-feature`.

Create or update the multi-phase implementation plan for `{feature}` at `{plan_doc_path}`.

Inputs:
- Design document: `{design_doc_path}`
- Existing context: `{context_paths}`
- Relevant code areas or keywords: `{code_hints}`
- Stack shape: `main ← design-doc ← impl-plan ← phase1 ← phase2 ← ... ← verification ← spec-promotion ← cleanup`

Requirements:
- Write a phase-connection plan, not detailed per-phase implementation plans.
- Treat the design document as the source of truth.
- Do not reduce or defer design goals, must-have requirements, or acceptance criteria without explicit user approval.
- Define reviewable phases for the stacked PR series.
- For each phase, include covered requirements, purpose, boundary, input from previous phase, output for next phase, dependency, expected end state, and verification scope.
- Do not write file-by-file implementation details for each phase. Each implementation phase will create its own phase implementation plan in the project-approved location; for nointern, use `docs/nointern/plans/` and do not place phase plans under `docs/nointern/design/`.
- Include a requirement table that maps every design requirement to one or more phases.
- Map every design goal and acceptance criterion to one or more phases.
- Include a required E2E primary matrix covering all added or changed behavior, plus testenv fixture/prerequisite support needs, including happy paths, important edge cases, regressions, fixture readiness, prerequisite snapshot needs, and evidence.
- Identify blockers, missing prerequisites, and external/manual actions separately, including which phase they block.
- Use `explore` subagents when codebase investigation is broad.
- Modify only the multi-phase plan and directly related planning documentation.
```

Multi-phase plan 작성 후 계획 문서만 커밋하고 `/ship-pr` 로 PR을 연다. PR 생성 후 리뷰/CI를 기다리지 않고 첫 구현 phase PR로 진행한다.

### 3. 구현 Phase PR 반복

각 구현 phase는 multi-phase plan에서 정의한 phase boundary를 기준으로 하나의 stacked PR로 만든다. 각 phase는 “phase 상세 구현 계획 → 구현 → 검증 + PR 출하” 순서로 진행한다.

#### Step 1 — Phase 상세 구현 계획

`designer` subagent 에 위임한다. 목표는 multi-phase plan의 phase scope를 해당 phase 구현자가 바로 실행할 수 있는 상세 구현 계획으로 구체화하는 것이다.

`designer` 에게 전달할 입력:

- 확정된 설계 문서 경로: `docs/{project}/design/{feature}.md`
- multi-phase plan 위치 또는 Issue/Project 링크
- 대상 phase 번호와 phase scope
- 이전 phase branch/base와 현재 phase branch/head
- 관련 코드 영역 또는 탐색해야 할 키워드
- phase 상세 구현 계획 출력 위치 또는 Issue/Project/PR body 링크

`designer` 완료 기준:

- 이 문서만 읽고도 구현 agent가 해당 phase를 구현할 수 있다.
- 문서 상단에 `Covered requirements` 를 두고, 이 phase에 할당된 requirement를 명시한다.
- 변경할 파일/모듈, 인터페이스, 데이터 흐름, API/DB/schema/config 영향, 테스트 범위가 구체적이다.
- 해당 phase가 이전 phase output을 어떻게 사용하고 다음 phase에 무엇을 제공하는지 명확하다.
- multi-phase plan의 phase boundary를 넘는 작업은 포함하지 않는다.
- 새 blocker나 prerequisite이 발견되면 구현 계획에 숨기지 않고 open question으로 분리한다.

호출 prompt 예시:

```text
Use the `designer` subagent for this step.

You are responsible for the detailed implementation planning step for phase `{phase_number}` of `/ship-feature`.

Create or update the phase implementation plan at `{phase_plan_path}`.

Inputs:
- Feature design document: `{design_doc_path}`
- Multi-phase plan document: `{plan_doc_path}`
- Target phase: `{phase_number} — {phase_title}`
- Phase scope from multi-phase plan: `{phase_scope}`
- Previous phase output/base branch: `{previous_phase_info}`
- Relevant code areas or keywords: `{code_hints}`

Requirements:
- Write a detailed implementation plan for this phase, not code.
- Save it in the project-approved planning location. For nointern, create phase implementation plans under `docs/nointern/plans/`; do not place phase plans under `docs/nointern/design/`.
- Treat the feature design and multi-phase plan as source of truth.
- Put `Covered requirements` at the top of the phase plan and list the requirements assigned to this phase.
- The document must be detailed enough that an implementation agent can read only this phase document plus the referenced design/plan docs and implement the phase.
- Include exact files/modules likely to change, interfaces, data flow, API/DB/schema/config impacts, tests to add/update, and completion criteria.
- Explain how this phase consumes previous phase outputs and what it provides to the next phase.
- Do not expand beyond the phase boundary unless a blocker makes the boundary invalid.
- If the boundary is invalid, stop and report the gap instead of silently changing scope.
- Use `explore` subagents when codebase investigation is broad.
- Modify only the phase implementation plan and directly related planning documentation.
```

#### Step 2 — 구현

`implementer` subagent 에 위임한다. 구현 agent는 phase 상세 구현 계획을 source of truth로 삼아 코드와 테스트를 작성한다. 구현 중 계획과 코드 현실이 충돌하면 scope를 임의로 바꾸지 않고 gap 절차를 따른다.

호출 prompt 예시:

```text
Use the `implementer` subagent for this step.

You are responsible for implementing phase `{phase_number}` of `/ship-feature`.

Inputs:
- Feature design document: `{design_doc_path}`
- Multi-phase plan document: `{plan_doc_path}`
- Phase implementation plan: `{phase_plan_path}`
- Current branch/base: `{branch_info}`

Requirements:
- Treat the phase implementation plan as the source of truth.
- Implement only this phase scope.
- Add or update tests required by the phase plan.
- If implementation reality conflicts with the plan, stop and report the gap instead of silently changing scope.
- Do not redesign the feature or move work to follow-up without explicit approval.
- Run the relevant quality checks listed in the phase plan when feasible.
- Commit the implementation and test changes.
```

#### Step 3 — 검증 + PR 출하

phase 상세 구현 계획의 완료 기준이 실제 코드와 테스트로 충족되는지 확인한다. 가능한 quality check를 실행한 뒤 커밋하고 `/ship-pr` 로 PR을 연다.

`/ship-pr` 는 PR 생성 전 `/code-review` 를 필수로 실행하므로, 별도 코드 리뷰 step을 중복 실행하지 않는다. `/ship-pr` 를 호출할 때는 phase 상세 구현 계획 경로를 함께 전달하여, 리뷰 기준에 일반 코드 품질뿐 아니라 구현이 phase 상세 구현 계획과 일치하는지도 포함되도록 한다.

Quality check가 오래 걸리거나 CI와 중복되면 다음 phase 작성을 계속한다. 실패 이벤트가 오면 실패한 phase에서 수정 후 후행 브랜치에 cascade 전파한다.

### 4. Pre-verification 구현 일치성 점검

모든 구현 phase PR을 만든 뒤 E2E/testenv 검증 전에, 별도 `auditor` subagent 로 설계/plan의 핵심 요구사항이 구현 phase들에 반영되었는지 점검한다. 목적은 main agent의 self-review bias를 줄이는 것이며, 별도 감사 phase나 장문의 리포트를 만들지 않는다.

`auditor` 는 이 단계에서 정확히 1회 실행한다. 감사 결과에서 발견된 high-impact 항목은 주 agent 가 직접 수정하고, 수정 검증은 E2E/testenv 검증 단계의 실제 명령 실행으로 수행한다.

`auditor` 에게 전달할 입력:

- feature 설계 문서 경로: `docs/{project}/design/{feature}.md`
- multi-phase plan 위치 또는 Issue/Project 링크
- phase 상세 구현 계획 위치 또는 PR body 링크 목록
- 모든 구현 phase의 누적 diff 또는 PR 목록
- 점검 기준: must-have, acceptance criteria, phase output, completion criteria가 코드/테스트/명시적 follow-up으로 추적되는지 확인

완료 기준:

- high-impact 누락 또는 불일치가 없다.
- 발견된 high-impact 항목은 해당 phase 브랜치에서 수정하고 후행 브랜치에 전파한다.
- 남은 follow-up은 PR body 또는 issue로 명시적으로 추적한다.
- 점검 결과 요약을 E2E/testenv 검증 PR body에 포함한다.

### 5. E2E/testenv 검증 — 실제 실행 + 이슈 해결 루프

검증 phase는 `implementer` subagent 에 위임한다. 목표는 multi-phase plan에 명시된 E2E primary 테스트와 testenv fixture/prerequisite support 검증을 실제 환경에서 직접 실행하고, 발견된 이슈를 원인 phase에 수정해 후행 브랜치로 전파하여 **최종 QA Checklist 의 모든 항목을 PASS 상태로 만드는 것**이다. 이 phase는 PASS/FAIL 상태표를 작성하는 단계가 아니라, 실제 QA를 통해 실패를 발견하고 코드를 고쳐 accept 가능한 상태를 만드는 단계다.

이 단계는 Pre-verification 구현 일치성 점검이 PASS 된 뒤 시작한다.

완료 기준:

- plan에 명시된 모든 E2E primary 테스트와 testenv fixture/prerequisite support 검증을 실제 명령으로 실행했다.
- 관련 current spec 을 식별하고, 각 spec 의 요구사항/비즈니스 규칙/API/도메인 모델/frontend route/code_paths 를 누적 구현 diff 와 strict 대조했다.
- strict spec 대조 결과는 항목별 `PASS`, `IMPLEMENTATION MISSING`, `SPEC UPDATE REQUIRED`, `NOT APPLICABLE` 로 기록했다. `IMPLEMENTATION MISSING` 은 verification phase 안에서 원인 phase 수정 + 후행 rebase 전파로 해소해야 하며, unresolved 상태로 완료 처리하지 않는다.
- 각 항목에 실행 명령, 작업 디렉터리, fixture/prerequisite 전제조건, PASS verdict, 검증 증거를 기록했다.
- unit test, static check, type check 는 보조 품질 게이트일 뿐, QA Checklist 항목의 primary evidence 로 쓰지 않았다.
- testenv 만 있고 E2E 가 비어 있는 제품 동작은 먼저 E2E 또는 testenv product scenario 를 추가·보강했다. 예외 사유만 기록하고 완료 처리하지 않았다.
- FAIL/BLOCKED/SKIP/NOT RUN 항목은 최종 산출물에 남기지 않았다. 실패하거나 실행하지 못한 항목은 원인을 분석하고, 자동 해결 가능한 것은 직접 수정했다.
- 수정은 원인 phase 브랜치에 커밋하고 후행 브랜치에 전파했다.
- 설계 문서의 `## QA Checklist` 에서 `Execution result` / `Fixes applied` 의 `TBD` 를 실제 PASS 실행 기록과 수정 기록으로 채웠다.
- 모든 시나리오가 PASS 될 때까지 실행 → 수정 → 재실행을 반복했다.
- 마지막에 전체 suite를 1회 실행해 회귀 없음이 확인되었다.
- 사용자 결정이 필요한 항목만 PR comment로 escalate 했다.

**산출물**:
- `## QA Checklist` 가 모두 PASS 로 채워진 design 문서. 최종 archived/implemented design 에 QA 수행 기록이 남아야 한다.
- **항목별 세부 기록** (실행 명령, 작업 디렉터리, fixture/prerequisite 전제조건, PASS 증거 — CLI JSON, response body, WebSocket event trace, Slack 링크 등)
- **Strict spec 대조표**: 관련 current spec 별 요구사항/비즈니스 규칙/API/도메인 모델/frontend route/code_paths 와 누적 구현 diff 를 대조한 결과. 구현 누락은 수정 완료, spec drift 는 spec-promotion phase 입력으로 명시한다.
- 이슈 해결 커밋 (필요한 phase 브랜치로 돌아가서 수정 + rebase 전파)

**Step 1 — 종합 검증 계획 확인**
- 구현 계획에 명시된 E2E primary 검증 매트릭스와 testenv fixture/prerequisite support 필요 여부를 확인한다.
- product behavior 는 먼저 E2E 로 추가·보강한다.
- testenv 는 E2E 실행에 필요한 fixture/prerequisite support 가 있을 때만 추가한다.
- happy path + 주요 edge case + **추가/변경된 기능 전체를 빠짐없이** 포함한다.

**Step 2 — 환경과 prerequisite 준비**
- deterministic E2E fixture 를 준비한다.
- testenv 가 필요한 경우 `fixture doctor/up` 으로 readiness 를 확인한다.
- external credential/prerequisite 가 필요한 경우 prepare phase snapshot 을 생성하고, 테스트 중에는 snapshot 만 읽는다.
- `.env.example`, preflight 체크, contract lint 변경이 필요하면 반영한다.

**Step 3 — 라이브 검증 + 이슈 해결 루프**
1. E2E 와 testenv fixture/prerequisite support 검증을 실제 명령으로 실행하고, 실제 실행한 명령/작업 디렉터리/환경 전제조건을 기록한다.
2. **항목 1개씩** 설계 문서의 QA Checklist 에 결과를 기록한다. 이때 최종 checklist 에 기록할 수 있는 verdict 는 PASS 뿐이다. PASS 근거는 product-facing E2E/testenv 실행 증거여야 하며 unit/static/typecheck 결과만으로 대체하지 않는다.
3. PASS 가 아닌 항목 (FAIL / BLOCKED / SKIP / NOT RUN) 마다:
    - 원인 분석 (handler / setup / 백엔드 / 환경 / 시나리오 자체 어디가 문제인지)
    - 해당 위치에 fix 커밋 (이전 phase 브랜치로 돌아가서 수정 → 후행 브랜치 rebase 전파)
    - 설계 문서의 해당 QA 항목 `Fixes applied` 에 원인, 수정 커밋, 재실행 결과를 기록
    - 항목을 **개별 실행** 으로 fix 검증 — 전체 suite 반복 금지
4. 모든 시나리오가 PASS 될 때까지 (1)~(3) 반복
5. **마지막에만** 전체 suite 1회 실행해 회귀 없음 확인

**Step 4 — 사용자 escalate 검토 (마지막 단계)**
- 모든 자동 해결 가능한 이슈를 끝낸 뒤, 남은 항목이 정말로 사용자 결정 / 외부 작업이 필요한지 마지막에 한번 더 검토
- 정말 필요한 것만 PR 코멘트로 escalate (예: Slack app dashboard 수동 변경, AWS IAM 정책 추가 등 사용자만 할 수 있는 작업)
- escalate 된 항목이 있으면 verification phase 는 완료되지 않은 상태다. QA Checklist 에 `FAIL`, `BLOCKED`, `SKIP`, `NOT RUN`, `N/A` 를 남겨서 완료처럼 제출하지 않는다.

**Step 5 — PR 생성**
- E2E/testenv 변경 + QA Checklist 실행 기록이 채워진 design 문서 + 필요한 fix 커밋을 포함한다.
- PR body 에 실행 명령/환경, 항목별 PASS evidence 표, design 문서의 QA 기록 위치, 필요한 Slack 대화 링크 포함
- `/ship-pr` (base: 마지막 phase 브랜치)

**testenv가 없는 프로젝트**: 이 단계를 건너뛴다. cleanup PR 이 마지막 phase 바로 뒤에 온다. 단, 그 경우에도 구현 단계에서 unit / e2e 테스트로 동등한 커버리지를 확보해야 한다.

### 6. Spec Promotion PR

Spec Promotion은 design 문서와 실제 구현을 기준으로 `docs/azents/spec/` 를 현재 시스템 상태에 맞게 승격하는 단계다. 이 단계에서는 spec 을 **추가 / 제거 / 수정** 해서 최신화한다. 현재 시스템을 설명하지 않는 spec 은 남기지 않고 삭제하거나 현재 spec 에 통합한다.

목표:

- design 문서의 의도와 acceptance criteria를 실제 구현 diff와 대조한다.
- `/spec-review`로 영향 받는 기존 spec 후보를 식별한다.
- 구현된 현재 동작을 설명하도록 기존 spec 을 직접 수정한다.
- 새 도메인/플로우가 생겼으면 새 spec 파일을 추가한다.
- 더 이상 현재 시스템을 설명하지 않는 spec 은 삭제하거나 다른 spec 에 통합한다.
- spec promotion 시점에 feature design 문서 frontmatter 의 `implemented` 를 **현재 날짜**로 설정한다. 값이 이미 있더라도 이 단계 완료일로 맞춘다.
- feature design 문서는 같은 경로에 유지한 채 `implemented` 날짜만 확정한다.
- feature design 문서의 `## QA Checklist` 에 최종 실행 결과와 수정 기록이 남아 있는지 확인한다. `TBD` 가 남아 있으면 spec-promotion 전에 verification phase 로 되돌린다.
- 어떤 spec 을 추가/수정/삭제했는지 PR body에 요약한다.

진행:

1. design 문서와 모든 구현 phase의 누적 diff를 읽는다.
2. `/spec-review`로 기존 spec 의 `code_paths` 와 누적 diff를 매칭한다.
3. 기존 spec 에 반영할 변경을 직접 수정하고 `last_verified_at` 을 갱신한다.
4. 새 현재 동작이 기존 spec 어디에도 속하지 않으면 domain/flow spec 을 추가한다.
5. stale spec 이 발견되면 삭제하거나 현재 spec 에 통합한다.
6. feature design 문서 frontmatter 의 `implemented` 를 spec promotion 작업일(현재 날짜)로 설정한다.
7. PR body에 `Spec Added`, `Spec Updated`, `Spec Removed`, `Design Implemented`를 요약한다.
8. `/ship-pr`로 spec-promotion PR을 연다.

### 7. Cleanup PR

구현 완료 후 plan 문서를 제거한다. 설계 문서에 `implemented` 가 기록되고 실제 코드가 구현된 뒤에는 plan 문서를 유지할 필요가 없으며, source of truth 는 implemented design, spec, 실제 코드다. cleanup은 `docs/nointern/plans/` 의 해당 feature plan 문서를 단순 삭제하는 PR이며, 동작 변경이나 별도 리팩터링을 섞지 않는다.

대상:

- 해당 feature를 위해 `docs/nointern/plans/` 아래에 작성한 multi-phase plan 및 phase별 상세 plan 문서
- 더 이상 참조되지 않는 QA/spec sync report 원본
- 더 이상 참조되지 않는 design draft

완료 기준:

- code/spec/design 동작 변경 없음
- cleanup PR diff 는 plan 문서 삭제와 문서 인덱스 갱신으로 제한됨
- 문서 인덱스가 갱신됨
- `/ship-pr`로 cleanup PR 생성

### 8. 머지

사용자가 명시적으로 머지를 요청하면, stacked PR이므로 반드시 `/stacked-prs` 스킬을 사용하여 앞에서부터 순서대로 머지한다. 머지 요청 전에는 PR stack 준비와 상태 요약까지만 수행한다.

## 운영 원칙

### Scope Integrity

- 합의된 목표, non-goal, acceptance criteria를 사용자 승인 없이 축소하거나 제거하지 않는다.
- `must implement`, `must remove`, 완료 기준에 해당하는 항목을 임의로 follow-up/defer/skip 처리하지 않는다.
- 구현 중 더 나은 방식이 보여도, scope를 바꾸기 전에 design/plan과 충돌하는지 먼저 확인한다.

### Gap Handling

- missing prerequisite, architecture gap, acceptance criteria 충돌처럼 현재 phase를 계속하면 잘못된 구현이 될 때는 해당 작업을 멈춘다.
- 먼저 사실을 짧게 정리한다: 계획된 내용, 실제 코드/운영 구조, 깨지는 완료 기준, 가능한 선택지.
- 사용자 결정이 필요하거나 stack 진행이 막히면 GitHub Issue 또는 PR comment로 blocker를 남기고 사용자에게 결정을 요청한다.
- 합의 전에는 목표 축소, phase 삭제, irreversible cleanup을 진행하지 않는다.
- 합의 후에는 design, plan, PR body 중 실제 source of truth에만 변경을 반영하고 downstream branch에 전파한다.

### Stacked PR Flow

- PR 생성 후 리뷰/CI 완료를 기다리며 다음 phase를 멈추지 않는다.
- CI 실패나 review comment가 오면 원인 phase 브랜치에서 수정하고 downstream branch에 cascade rebase/전파한다.
- 앞 PR이 깨져 있어도 후행 PR은 draft로 계속 쌓을 수 있다. 단, ready/merge 전에는 모든 실패와 review comment를 해결한다.
- 모든 PR은 `/ship-pr`로 생성한다. 직접 `gh pr create` 하지 않는다.
- 사용자가 머지를 요청하기 전에는 PR stack 준비와 상태 요약까지만 수행한다.
- 사용자가 머지를 요청하면 `/stacked-prs`로 앞 PR부터 순서대로 처리한다.

### Verification

- 구현 phase마다 해당 phase에 필요한 unit/e2e/quality check를 실행한다.
- nointern 은 추가/변경 기능 전체를 E2E primary 로 검증하고, 필요한 경우 testenv fixture/prerequisite support 검증을 실행한다.
- spec-promotion 전에는 design, 실제 구현, spec이 서로 맞는지 확인한다.
- 작업이 blocker로 멈출 때는 마지막 성공 상태만 말하지 말고, blocker와 필요한 결정을 명확히 남긴다.
