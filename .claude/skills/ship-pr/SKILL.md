---
name: ship-pr
description: "PR 출하 플로우를 실행한다. 사용 시점: (1) '/ship-pr', (2) 'PR 만들고 모니터링해' 를 거쳐 PR을 만들 때. PR 생성 자체는 /create-pr에 위임한다."
---

# PR 출하 (/ship-pr)

현재 브랜치를 review 가능한 상태로 점검한 뒤 `/create-pr`로 PR을 만든다. 이 스킬은
품질·스펙 게이트를 담당하고, 실제 PR 생성 절차는 `/create-pr`에 위임한다.

## 워크플로우

### 1. 코드 리뷰 (필수)

PR 생성 전 반드시 `/code-review` 스킬로 셀프 리뷰를 수행한다. 생략하지 않는다.

코드 리뷰와 수정은 한 번만 수행한다. `/code-review` → 필요한 수정 반영 → 커밋까지
진행한 뒤에는 같은 `/ship-pr` 실행 안에서 재리뷰 루프를 돌리지 않고 다음 단계로 간다.

- Critical/Warning 발견 시 → 수정 후 커밋하고 다음 단계 진행
- Suggestion/Consistency만 있거나 발견 없으면 → 바로 다음 단계 진행

### 2. 필요한 수정 반영

`/code-review`  결과로 필요한 코드/문서 수정이 있으면 같은 브랜치에 반영한다.

이 단계는 1회만 수행한다. 수정 후 새 Critical/Warning을 찾기 위해 `/code-review`를
다시 호출하지 않는다. 추가 리뷰가 필요하면 PR 생성 후 일반 리뷰 과정에서 처리한다.

- Critical/Warning 발견 시 → 수정 후 진행
- Suggestion/Consistency만 있거나 발견 없으면 → 바로 다음 단계 진행

### 3. `/create-pr` 호출

검증 결과를 바탕으로 `/create-pr`를 호출한다. `/create-pr`는 PR 생성만 담당하므로,
아래 정보를 넘길 수 있게 대화 맥락에 남긴다.

- 실행한 test/quality check와 결과
- PR 본문에 `## Spec Impact`를 넣어야 하는지에 대한 판단

`/create-pr`의 규칙을 따른다.

### 4. 결과 보고

- 생성된 PR URL
- `/code-review` 결과
