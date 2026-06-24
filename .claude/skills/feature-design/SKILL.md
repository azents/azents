---
name: feature-design
description: "새 기능 설계 요청, 설계 문서 작성, 기술적 의사결정이 필요한 아키텍처 변경을 논의 → 초안 → 검증 → 최종안 순서로 진행하는 워크플로우."
---

# 기능 설계 워크플로우

새로운 기능을 설계할 때 따르는 4단계 프레임워크. 논의 → 초안 → 검증 → 최종안 순서로 진행하며, 각 단계에서 발견된 사실이 이전 단계의 결정을 뒤집을 수 있다.

**두 가지 모드**를 지원한다:
- **협업 모드**: 사용자와 논의포인트를 하나씩 리뷰하며 합의를 도출
- **자율 모드**: 에이전트가 독립적으로 전체 프로세스를 실행

## 사용 시점

- 새 기능 설계 요청 ("~기능 디자인해줘", "~설계 문서 작성해줘")
- 설계 문서 + PR까지 한번에 요청받았을 때
- 기술적 의사결정이 필요한 아키텍처 변경

## 모드 판별

| 사용자 발화 | 모드 |
|---|---|
| "~설계해줘", "디자인 문서 작성해줘" | **협업** (기본) |
| "너 혼자 진행해봐", "자율로 해줘", "알아서 해줘" | **자율** |

명시적 지시가 없으면 **협업 모드가 기본**이다. 설계는 사용자의 도메인 지식과 비즈니스 판단이 필요한 영역이므로 함께 결정하는 것이 기본값.

---

## 협업 모드

사용자와 함께 논의포인트를 하나씩 리뷰하며 설계를 진행한다.

### 실행 환경 판별

| 실행 환경 | 판별 기준 | Phase 1.5 동작 |
|---|---|---|
| **대화형 세션** | 터미널/IDE에서 직접 대화 중 | 한 포인트씩 순차 제시, 사용자 응답 대기 |
| **GitHub Discussion** | Discussion 코멘트에서 트리거됨 | **각 포인트를 별도 댓글로 작성** — 댓글 스레드에서 독립 논의 |
| **GitHub Issue/PR** | Issue/PR 코멘트에서 트리거됨 | 대화형 세션과 동일 (한 코멘트에 한 포인트씩) |

### Phase 1: 리서치 + 논의포인트 도출

1. **리서치**: 코드베이스 + 외부 기술을 병렬 Agent로 조사
2. **논의포인트 목록 제시**: 리서치 결과를 바탕으로 결정해야 할 항목 목록을 사용자에게 보여준다

```
리서치 완료. 다음 N개 논의포인트를 정리했습니다:

1. ToolkitType: 새 타입 추가 vs 기존 MCP 활용
2. MCP 서버 선정: 공식 vs 커뮤니티
3. 인증 방식: SA Key vs Workload Identity vs OAuth
4. 서비스 선택 단위: 전체 vs 서비스별
5. ...

하나씩 리뷰하겠습니다.
```

### Phase 1.5: 논의포인트 개별 리뷰 (핵심)

**각 포인트를 하나씩** 사용자에게 제시하고 합의를 구한다. 다음 포인트로 넘어가기 전에 현재 포인트의 결정을 확인한다.

각 포인트 제시 시 포함할 내용:

1. **배경 설명** — 이 결정이 왜 필요한지, 어떤 영향을 미치는지
2. **선택지** — 각 옵션의 장단점을 구체적으로 (코드 예시, 아키텍처 차이 포함)
3. **관련 데이터** — 리서치에서 발견한 구체적 수치, 사실 (도구 수, 지원 범위, 성숙도 등)
4. **추천안** — 에이전트의 추천과 그 이유
5. **트레이드오프** — 추천안의 약점도 솔직하게 제시

**예시 — 논의포인트 하나를 제시하는 방식:**

```
### 논의포인트 2/5: MCP 서버 선정

**배경:**
GCP 관련 MCP 서버가 여러 개 존재합니다. 어떤 서버를 사용하느냐에 따라
아키텍처(sidecar 필요 여부), 도구 커버리지, 유지보수 부담이 달라집니다.

**선택지:**

A) `@google-cloud/observability-mcp` (Google 공식, stdio)
   - 12 tools: Logging 6, Monitoring 3, Trace 2, Error Reporting 1
   - stdio → mcp-proxy sidecar 필요
   - preview 상태, Google Cloud ToS 적용 외
   - npx로 설치 가능

B) Google Hosted Remote MCP (Google 공식, HTTP)
   - 65+ tools: Logging 6, Monitoring 7(PromQL!), GKE 8, Compute 29, Cloud Run 4, Cloud SQL 11
   - HTTP 직접 연결 → sidecar 불필요, 인프라 변경 제로
   - Google 관리 인프라, 항상 최신
   - 서비스별 별도 URL → 다중 연결 필요

C) `google-cloud-mcp` (커뮤니티, stdio)
   - 40+ tools: Logging, Monitoring, Trace, Error Reporting, Profiler
   - v0.1.3, 빌드 필요
   - 장기 유지보수 불확실

**추천: B (Google Hosted Remote MCP)**
sidecar 불필요로 인프라 복잡도가 크게 줄고, 도구 수가 압도적입니다.
다중 연결이 필요하지만 Provider 내부에서 처리 가능합니다.

**트레이드오프:**
서비스별 별도 URL이므로 McpToolkitConfig(단일 server_url)를 직접 재사용할 수 없고,
Provider가 다중 연결을 자체 관리해야 합니다.

어떻게 생각하시나요?
```

**핵심 원칙:**
- **한 번에 한 포인트만** — 여러 포인트를 한꺼번에 던지면 사용자가 압도됨
- **추천안을 반드시 포함** — 사용자가 "추천대로" 라고만 해도 진행 가능하도록
- **사용자의 결정을 기다린다** — 결정 없이 다음 포인트로 넘어가지 않는다
- **사용자가 추가 질문하면 답변** — 각 포인트에서 사용자가 깊이 파고 싶으면 따라간다
- **결정이 이전 포인트에 영향을 주면 되돌아간다** — "아 그러면 1번도 다시 봐야겠네요"

#### GitHub Discussion에서의 Phase 1.5

GitHub Discussion에서 트리거된 경우, **각 논의포인트를 별도 댓글(comment)로 작성**한다. GitHub Discussion은 댓글마다 독립 reply 스레드를 지원하므로, 각 포인트별로 병렬 논의가 가능하다.

**동작:**
1. Discussion 본문에 개요 + 현재 구조 + 목표 구조를 작성 (Discussion 생성 시)
2. 각 논의포인트를 **별도 댓글**로 작성 — 모든 포인트를 한번에 올린다
3. 각 댓글에는 반드시 다음을 포함:
   - **배경 설명**
   - **선택지** (각 옵션의 장단점, 코드 예시)
   - **추천안 + 이유** — 에이전트가 왜 이 선택지를 추천하는지 근거 제시
   - **트레이드오프** — 추천안의 약점
4. 사용자는 각 댓글의 reply 스레드에서 의견을 남기고, 에이전트는 해당 스레드에서 답변
5. 논의 완료 후 결정 사항을 요약하는 댓글을 추가

**예시 — Discussion 댓글 구조:**
```
Discussion 본문: 개요 + 현재/목표 아키텍처 다이어그램

댓글 1: "## 1. executor 실행 모델"
  └─ reply: 사용자 의견
  └─ reply: 에이전트 답변

댓글 2: "## 2. sidecar 컨테이너 구성"
  └─ reply: 사용자 의견

댓글 3: "## 3. file API 경로 라우팅"
  └─ ...

댓글 N+1: "## 결정 요약" (모든 포인트 논의 완료 후)
```

**대화형 세션과의 차이:**
- 대화형: 한 포인트씩 순차 제시, 사용자 응답 대기 후 다음 포인트
- Discussion: **모든 포인트를 한번에 각각 별도 댓글로** — 사용자가 관심 있는 포인트부터 자유롭게 논의 가능

#### GitHub Discussion에서의 Phase 2~4

Discussion에서 트리거된 경우, **Phase 2~4는 Discussion 논의가 완료된 후에만 진행**한다. 에이전트가 자체적으로 최종안을 결정하지 않는다.

**흐름:**
1. Phase 1~1.5: Discussion 댓글 스레드에서 논의 진행
2. 사용자가 각 논의포인트에 결정을 내림 (댓글 reply로)
3. 모든 포인트의 결정이 확정되면 → 결정 요약 댓글 작성
4. 사용자가 "최종안 작성해" 또는 "진행해" 등 명시적으로 지시하면 → Phase 2~4 진행
5. Phase 2~4 산출물(설계 문서)을 PR로 제출

**하지 않는 것:**
- 논의가 진행 중인데 에이전트가 임의로 최종안을 작성하여 PR하지 않는다
- 일부 포인트만 결정된 상태에서 전체 설계를 진행하지 않는다

### Phase 2~4: 협업 모드

논의포인트 합의 완료 후:
- **Phase 1.6 (ADR)**: 합의된 결정을 먼저 ADR로 기록한다. 설계 문서는 ADR 작성 후에만 작성한다.
- **Phase 2 (초안)**: ADR decision을 근거로 설계 문서 초안 작성
- **Phase 3 (검증)**: 사용자에게 검증 결과 보고, 초안 변경 필요 시 관련 포인트 재논의
- **Phase 4 (최종안)**: 최종 문서 작성 후 사용자에게 리뷰 요청

설계 문서의 Requirements는 ADR decision을 참조해야 한다. ADR decision을 참조하지 않는 요구사항이나, 요구사항에 매핑되지 않은 ADR decision이 있으면 설계 문서는 완료된 것으로 보지 않는다.

Phase 3에서 대안이 발견되면 사용자에게 보고하고 해당 포인트를 다시 리뷰한다:

```
Feasibility 체크 중 새로운 발견이 있습니다.

논의포인트 2 (MCP 서버 선정)에서 B안으로 결정했는데,
Google Hosted Remote MCP가 Streamable HTTP를 지원하여
기존 MCP 인프라와 바로 호환됩니다.

다만 추가로 발견된 사실:
- tools/list는 인증 없이 호출 가능 (discovery 용이)
- x-goog-user-project 헤더 필수 (billing attribution)
- readOnlyHint annotation으로 write 도구 필터링 가능

기존 결정 유지할까요, 아니면 재검토할까요?
```

---

## 자율 모드

에이전트가 독립적으로 전체 프로세스를 실행한다. 사용자 확인 없이 논의포인트를 스스로 결정하고, 완성된 설계 문서를 PR로 제출한다.

### Phase 1: 논의포인트 도출

**목표**: 설계 공간에서 결정해야 할 핵심 질문들을 식별한다.

1. **기존 코드베이스 조사**: 유사 기능이 어떻게 구현되어 있는지 Explore agent로 파악
2. **외부 리서치**: 관련 기술·서비스·API를 WebFetch/WebSearch로 조사
3. **논의포인트 정리**: 각 포인트에 대해:
   - 선택지 나열 (최소 2개)
   - 각 선택지의 장단점
   - **결정과 근거** 명시

**핵심 원칙:**
- 리서치는 **병렬로** 수행한다 — 코드베이스 탐색과 외부 조사를 동시에 Agent로 실행
- 선택지가 1개뿐이면 논의포인트가 아니다 — 결정할 게 없는 것은 적지 않는다
- **모든 선택지를 기록한다** — 나중에 왜 그 결정을 했는지 추적 가능해야 한다

**경험에서 배운 것:**
> GCP Toolkit 설계 시, 초기 리서치에서 커뮤니티 MCP 서버만 발견하고 설계를 시작했다.
> 이후 추가 리서치에서 Google 공식 서버를 발견하여 설계를 처음부터 다시 작성했다.
> **교훈: 리서치를 한 번에 끝내려 하지 말고, 여러 관점에서 병렬로 조사하라.**
> 특히 공식 문서, 커뮤니티 프로젝트, 블로그 포스트를 모두 확인해야 한다.

### Phase 2: 디자인 초안 작성

**목표**: Phase 1의 결정을 바탕으로 구체적인 설계 문서를 작성한다.

문서 구조:
```markdown
---
title: "{기능명} 설계"
tags: [backend, engine, ...]
created: {날짜}
---

# {기능명} 설계

## 개요
해결하는 문제와 사용자 시나리오

## Requirements
요구사항을 `REQ-{번호}` 형식으로 정리한다. 각 요구사항은 다음을 포함한다:
- 설명
- Related decisions: 이 요구사항이 충족하는 ADR decision ID 목록
- Acceptance criteria: 충족 여부를 판단할 수 있는 관찰 가능한 기준

## Decision Table
ADR decision → requirements 역방향 매핑을 기록한다.
모든 ADR decision은 최소 하나 이상의 requirement에 매핑되어야 한다.

## 논의 포인트 및 결정
Phase 1에서 도출한 각 포인트 + 선택지 + 결정 + 근거.
최종 결정은 ADR에 기록된 decision ID를 참조한다.

## 아키텍처
Mermaid 다이어그램 + 런타임 연결 구조

## 데이터 모델
Config, Secrets, DB 저장 구조

## Provider/Service 구현
핵심 클래스 구조 + resolve/create 흐름 (의사코드)

## API
기존 API 재사용 가능 여부 + 요청/응답 예시

## Frontend (UI/UX)
와이어프레임 (ASCII) + UI 상세 설계

## 인프라
필요한 인프라 변경 (없으면 "변경 없음" 명시)

## Feasibility 검증
검증 항목 표 + 리스크 표

## Test Strategy
azents 기능 설계에서는 제품 동작 검증을 E2E primary 로 둔다.

QA로 인정되는 검증은 실제 서비스를 구동하는 `testenv`/E2E/agentic test 경로뿐이다.
unit test, integration test, static check, docs validation은 보조 품질 체크로만 기록하고,
QA Checklist의 통과 근거로 쓰지 않는다.

필수로 명시할 항목:
- 동작별 E2E primary 검증 매트릭스
- E2E primary 검증 계획
- seed/fixture 요구사항
- credential/prerequisite snapshot 요구사항
- evidence 형식
- CI 실행 정책
- optional/live 테스트의 skip/fail 기준

예시:
1. E2E: pytest fixture 로 user/workspace/agent 생성 → public API/WS 호출 → response/event assertion

## QA Checklist
설계 단계에서 검증해야 할 항목을 미리 정의한다. 이 섹션은 구현 후
E2E/testenv verification phase 에서 채워지는 실행 기록의 원본 자리다.

QA Checklist의 `How to check`는 반드시 실제 서비스 구동 경로를 사용한다:
- azents E2E (`testenv/azents/e2e`)에서 public/admin API, WebSocket, worker, sandbox 등 실제 경로 검증
- testenv 기반 agentic test에서 runner/fixture가 실제 server/runtime을 띄우고 사용자 경로로 검증
- 외부 credential이 필요한 live path는 optional/live로 분리하고 skip/fail 기준을 명시

unit test나 static check만으로는 어떤 QA 항목도 PASS 처리하지 않는다.

각 체크 항목은 다음 하위 섹션을 가진다:

### QA-{번호}. {체크 항목 이름}

#### What to check
무엇을 확인할지 사용자 동작 / API 계약 / 데이터 상태 / 실패 모드 기준으로 쓴다.

#### Why it matters
이 체크가 어떤 사용자 가치, 회귀 위험, 운영 안정성, 데이터 무결성을 보장하는지 쓴다.

#### How to check
E2E primary 명령, 필요한 fixture/seed/prerequisite, 필요 시 testenv diagnostic 명령을 쓴다.

#### Expected result
통과 조건을 관찰 가능한 assertion / 응답 / UI 상태 / 로그 / DB read 모델 기준으로 쓴다.

#### Execution result
TBD — E2E/testenv verification phase 에서 PASS/FAIL/SKIP/BLOCKED, 실행 명령,
작업 디렉터리, 환경 전제조건, evidence 링크/요약을 채운다.

#### Fixes applied
TBD — verification phase 에서 실패를 발견하면 원인, 수정 커밋, 재실행 결과를 채운다.

원칙:
- 설계 PR 에서는 `Execution result` 와 `Fixes applied` 를 반드시 `TBD` 로 둔다.
- verification phase 는 이 TBD 를 채워 모든 필수 QA 항목을 PASS 시키는 것을 목표로 한다.
- 체크만 하는 것이 아니라, 자동 수정 가능한 실패는 코드 수정까지 수행한다.
- 최종 archived/implemented design 문서에는 QA 수행 기록이 남아야 한다.
- unit test는 구현 보조 검증으로만 사용하고, QA Checklist에는 E2E/testenv evidence만 남긴다.

## 구현 계획
Phase별 분류

## 검토한 대안들
탈락한 대안과 탈락 사유
```

**핵심 원칙:**
- **의사코드는 실제 코드베이스 패턴을 따른다** — 기존 유사 구현체의 클래스명, 메서드명, 패턴을 그대로 참조
- **"변경 없음"도 명시한다** — 인프라 변경이 없다는 것 자체가 중요한 설계 결정
- **사용자 시나리오를 먼저 쓴다** — "에이전트가 X를 할 수 있게 한다" 식의 구체적 시나리오

**경험에서 배운 것:**
> 초안 작성 시 stdio MCP + sidecar 아키텍처로 설계했으나,
> Phase 3에서 Google Hosted HTTP MCP를 발견하여 **sidecar가 필요 없는** 완전히 다른 아키텍처로 전환했다.
> **교훈: 초안은 말 그대로 초안이다. Phase 3에서 뒤집힐 수 있음을 전제하고 작성하라.**
> 초안에 과도하게 시간을 투자하지 말 것.

### Phase 3: 구현 Feasibility 체크

**목표**: 초안의 기술적 실현 가능성을 검증하고, 더 나은 대안이 없는지 확인한다.

검증 항목:
1. **핵심 의존성 존재 여부** — 사용하려는 라이브러리/서비스가 실제로 존재하고 동작하는가?
2. **API 호환성** — 기존 API와 충돌 없이 통합 가능한가?
3. **인증/보안** — 인증 플로우가 실제로 동작하는가? (직접 API 호출 테스트 권장)
4. **인프라 변경** — 필요한 인프라 변경의 규모와 복잡도
5. **기존 코드 재사용** — 새로 만들어야 하는 것 vs 재사용 가능한 것
6. **대안 탐색** — 초안의 접근 방식보다 더 나은 대안이 있는가?

**실행 검증 방법:**

문서/코드 읽기만으로 끝내지 말고, 가능한 가장 실제에 가까운 실행 경로로 확인한다.

확인 대상:
- "이 API endpoint가 존재하는가?" → 직접 호출
- "이 DB 필드가 있는가?" → seed 후 조회
- "이 흐름이 end-to-end로 동작하는가?" → seed → 호출 → 결과 검증
- "기존 기능이 깨지지 않는가?" → 기존 시나리오 재실행

**핵심 원칙:**
- **대안 탐색을 반드시 수행한다** — 초안에 확증 편향되지 않도록
- **발견한 대안이 더 낫다면 초안을 버린다** — 매몰비용 오류를 경계
- **"동작하는가?"를 직접 검증한다** — 문서만 읽지 말고, API 호출이나 tools/list 등 실제 실행 경로로 확인

**경험에서 배운 것:**
> Feasibility 체크 중 Google Managed Remote MCP 서버의 존재를 발견했다:
> - `https://logging.googleapis.com/mcp` — HTTP 직접 연결, sidecar 불필요
> - 6개 서비스, 65+ tools, Google 관리 인프라
> - 인프라 변경 제로 (Pod, ConfigMap, Secret, 이미지 모두 불필요)
>
> 이 발견으로 초안 (stdio + sidecar)을 완전히 폐기하고 재설계했다.
> **교훈: Feasibility 체크는 "초안이 가능한가?"만 확인하는 게 아니다.
> "더 나은 방법이 있는가?"를 적극적으로 탐색하는 단계다.**

### Phase 4: 최종안 작성

**목표**: Phase 3의 검증 결과를 반영하여 최종 설계 문서를 작성한다.

Phase 2와 동일한 구조를 따르되:
- Phase 3에서 발견된 대안이 채택되었다면 **전면 재작성**
- 초안이 유효하다면 **Feasibility 검증 결과 반영 + 보강**

**최종안 체크리스트:**
- [ ] 모든 논의포인트에 결정 + 근거가 있는가?
- [ ] 합의된 결정이 설계 문서 작성 전에 ADR로 기록되어 있는가?
- [ ] ADR decision이 안정적인 ID로 참조 가능한가? (예: `ADR-0012-D1`)
- [ ] `Requirements` 섹션이 있고, 각 requirement에 related decisions와 acceptance criteria가 있는가?
- [ ] `Decision Table` 이 있고, 모든 ADR decision이 최소 하나 이상의 requirement에 매핑되어 있는가?
- [ ] 검토한 대안들이 탈락 사유와 함께 기록되어 있는가?
- [ ] 구현 계획이 Phase별로 분류되어 있는가?
- [ ] 리스크와 완화 방안이 있는가?
- [ ] 와이어프레임/다이어그램이 포함되어 있는가?
- [ ] Test Strategy 가 E2E primary 검증 기준을 명확히 하는가?
- [ ] fixture, credential, prerequisite snapshot, evidence, CI 정책이 명시되어 있는가?
- [ ] QA Checklist 에 각 항목별 What / Why / How / Expected result 가 구체적으로 작성되어 있는가?
- [ ] QA Checklist 의 Execution result / Fixes applied 는 설계 단계에서 `TBD` 로 남아 있는가?

**경험에서 배운 것:**
> 최종안 작성 후에도 사용자 피드백으로 추가 논의포인트가 생길 수 있다.
> GCP Toolkit에서는 최종안 이후에:
> - "Read/Write 권한 분리 옵션 검토해줘" → readOnlyHint 기반 필터링 추가
> - "BigQuery 필수" → 서비스 목록에 BigQuery 추가
> - "서비스 선택하면 어떤 권한 줘야되는지 가이드해줘" → IAM 역할 동적 안내 UI 추가
>
> **교훈: 최종안은 "완성"이 아니라 "리뷰 가능한 상태"다.
> 사용자 피드백을 받아 즉시 반영할 준비를 하라.**

---

## 공통 요소

### 반복 패턴

이 워크플로우는 선형이 아니라 **반복적**이다:

```
Phase 1 → Phase 2 → Phase 3 ──→ Phase 4
                       │              │
                       │ 대안 발견    │ 사용자 피드백
                       ↓              ↓
                    Phase 1로       Phase 1로
                    돌아감          부분 반복
```

- Phase 3에서 더 나은 대안 발견 → Phase 1부터 재시작 (논의포인트 재정리)
- Phase 4에서 사용자 피드백 → 해당 논의포인트만 Phase 1~4 부분 반복

### 리서치 전략

**병렬 리서치:**
```
Agent 1: 코드베이스 탐색 (기존 패턴, 유사 구현)
Agent 2: 외부 기술 조사 (공식 문서, API 스펙)
Agent 3: 커뮤니티/대안 조사 (GitHub, npm, PyPI)
```

최소 2개 에이전트를 병렬로 실행하여 리서치 시간을 단축한다.

**조사 깊이:**

| 단계 | 깊이 | 예시 |
|------|------|------|
| Phase 1 | 넓고 얕게 | "어떤 GCP MCP 서버가 있는가?" |
| Phase 3 | 좁고 깊게 | "이 서버의 tools/list 응답에 readOnlyHint가 있는가?" |

Phase 1에서는 선택지를 넓히고, Phase 3에서는 선택한 방향을 깊이 검증한다.

**공식 vs 커뮤니티:**

**항상 공식 솔루션을 우선 탐색한다.** 커뮤니티 프로젝트만 발견하고 멈추지 말 것.

체크리스트:
- [ ] 공식 문서 사이트 (docs.*.com)
- [ ] 공식 GitHub org
- [ ] 공식 블로그/발표
- [ ] npm/PyPI에서 공식 scope (@google-cloud/, @aws/ 등)
- [ ] 커뮤니티 프로젝트 (GitHub search)
- [ ] 블로그 포스트, 튜토리얼

### 문서 저장 위치

각 Phase의 산출물은 다음과 같이 저장한다 (Living Spec 시스템 반영):

| Phase | 산출물 | 저장 위치 | 설명 |
|---|---|---|---|
| Phase 1~1.5 | 논의 기록 | `design/{feature}.md` 내 "Alternatives Considered" 섹션 | 단일 문서에 모든 논의 통합. discussion/ 폴더 사용 안 함 |
| Phase 1.6 (신규) | 합의된 결정 | `adr/NNNN-{slug}.md` | 설계 문서 작성 전에 ADR로 먼저 기록 |
| Phase 2~4 | 확정 설계 | `design/{feature}.md` | Requirements, Decision Table, Alternatives Considered 필수 |
| 구현 계획 | GitHub Issue/Project | (파일 없음) | plans/ 폴더 사용 안 함. 작업 분해는 Issue 로 |

- feature-design 에서 합의한 결정은 설계 문서 작성 전에 ADR로 먼저 기록한다.
- 설계 문서는 ADR decision을 근거로 requirements를 정의하는 소스 오브 트루스다.
- "Alternatives Considered" 섹션에 탈락한 선택지와 그 사유를 남겨야 "왜 이렇게 결정했는지" 추적 가능하다.
- 구현 작업 분해는 파일이 아니라 GitHub Issue / Project 로 관리한다.

## ADR 작성 기준 (Phase 1.6)

feature-design 에서 합의한 결정은 설계 문서 작성 전에 ADR로 기록한다. 하나의 ADR에 여러 decision을 담을 수 있지만, 각 decision은 설계 문서에서 안정적으로 참조할 수 있는 ID를 가져야 한다.

ADR 형식:
- 파일명: `docs/nointern/adr/NNNN-{slug}.md` (NNNN 은 기존 최대 번호 + 1)
- 섹션: Context / Decision / Consequences / Alternatives
- Decision 섹션의 각 결정에는 안정적인 decision ID를 부여한다. 예: `ADR-0012-D1`, `ADR-0012-D2`
- **append-only**: 결정이 바뀌면 **새 ADR** 로 supersede (기존 수정 X)

### 문서 PR 워크플로우

1. `docs/{feature-name}` 브랜치 생성
2. Phase 1~1.5: `docs/nointern/design/{feature-name}.md` 에 "Alternatives Considered" 섹션으로 논의 기록
3. Phase 1.6: ADR 분기 기준에 해당하면 `docs/nointern/adr/NNNN-{slug}.md` 추가
4. Phase 2~4: 같은 `docs/nointern/design/{feature-name}.md` 를 최종 설계로 확장
5. `/ship-pr`로 PR 생성 (리뷰어 지정)
6. 리뷰 피드백 반영 → 문서 업데이트

구현까지 요청받았으면 `/ship-feature` 스킬로 전환하여 stacked PR로 설계 문서 → phase별 구현을 진행한다. 구현 작업 분해는 GitHub Issue / Project 로 관리한다 (plans/ 폴더 사용 안 함).

### 안티패턴

**1. 리서치 없이 설계 시작**
> "이미 알고 있으니까" → 공식 서버가 출시되어 있었는데 커뮤니티 서버로 설계

항상 리서치부터. 기술은 빠르게 변한다.

**2. 초안에 집착**
> "이미 다 썼는데 바꾸기 아깝다" → 더 나은 대안이 있는데 기존 설계를 고수

초안은 버릴 수 있다는 전제로 작성한다.

**3. Feasibility 체크 생략**
> "코드만 짜보면 되지" → 인증 플로우가 동작하지 않아 구현 중반에 설계 변경

구현 전에 핵심 가정을 검증한다.

**4. 대안 미기록**
> "어차피 이걸로 결정했으니까" → 6개월 후 누군가 "왜 이 방식?"이라고 물으면 답할 수 없음

탈락한 대안도 탈락 사유와 함께 기록한다.

**5. 단일 관점 리서치**
> Agent 1개로 순차 검색 → 시간 오래 걸리고, 한쪽 방향으로만 탐색

최소 2개 Agent를 병렬로 실행하여 다양한 관점에서 동시에 조사한다.

**6. 협업 모드에서 한번에 모든 포인트 제시**
> 10개 논의포인트를 한 메시지에 다 담음 → 사용자가 압도되어 "알아서 해"로 전환

한 번에 한 포인트씩. 사용자의 집중을 존중한다.

## Spec 연동

설계 완료 후 `/ship-feature` 로 구현 진입한다. 구현 완료 후 spec-promotion 단계에서 design 을 archive 하고, 현재 구현을 설명하는 spec 만 남긴다.
