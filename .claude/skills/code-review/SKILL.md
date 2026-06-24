---
name: code-review
description: "코드 리뷰 수행. 사용 시점: (1) '/code-review'로 현재 브랜치 변경사항 리뷰, (2) '/code-review PR #123'으로 특정 PR 리뷰, (3) '/code-review staged'로 staged changes 리뷰, (4) '코드 리뷰해줘', '리뷰 부탁'."
---

# 코드 리뷰 (/code-review)

변경된 코드를 리뷰하고, 문제점과 개선사항을 심각도별로 리포트한다.

**별도의 지시가 없으면 리뷰 결과를 항상 코드에 반영한다.** Critical/Warning은 즉시 수정하고, Suggestion/Consistency는 합리적이면 반영한다.

## 워크플로우

### 1. 리뷰 대상 결정

인자에 따라 diff 대상을 결정한다:

| 인자         | 대상                                   |
| ------------ | -------------------------------------- |
| (없음)       | 상위 브랜치 대비 현재 브랜치 전체 diff |
| `staged`     | staged changes (`git diff --cached`)   |
| `last`       | 마지막 커밋 (`git diff HEAD~1`)        |
| `PR #N`      | 해당 PR의 diff (`gh pr diff N`)        |
| `<file ...>` | 지정된 파일만 상위 브랜치 대비 diff    |

상위 브랜치는 다음 순서로 결정:

1. `gh pr view --json baseRefName`으로 PR의 base branch 확인
2. PR이 없으면 `git log --oneline --merges -1` 등으로 분기점 추정
3. 그래도 불명확하면 `main` 사용

### 2. 컨텍스트 수집

리뷰 전에 다음을 수집한다:

**a. 프로젝트 규칙**

- 변경된 파일 경로에서 프로젝트 루트까지 거슬러 올라가며 모든 `CLAUDE.md`, `AGENTS.md`, `.claude/CLAUDE.md`를 읽는다
- 예: `python/apps/azents/src/handler.py` 변경 시 →
  1. `python/apps/azents/CLAUDE.md` (또는 `AGENTS.md`, `.claude/CLAUDE.md`)
  2. `python/apps/CLAUDE.md`
  3. `python/CLAUDE.md`
  4. 루트 `CLAUDE.md`
- 하위 규칙이 상위 규칙보다 우선하되, 모든 레벨의 규칙을 리뷰 기준에 반영

**b. 기존 패턴 (일관성 검사용)**

- 변경된 파일이 속한 앱을 식별 (예: `python/apps/azents/`, `typescript/apps/azents-web/`)
- 해당 앱 내에서 변경 내용과 유사한 기존 구현을 탐색:
  - API 엔드포인트 추가 → 기존 엔드포인트 패턴
  - 서비스 추가 → 기존 서비스 클래스 패턴
  - 리포지토리 추가 → 기존 리포지토리 패턴
  - 테스트 추가 → 기존 테스트 패턴
  - 등등
- 네이밍 컨벤션, import 스타일, 에러 처리 방식, 디렉토리 구조 등을 파악

### 3. 리뷰 실행

repo-level OpenCode 설정이 있는 환경에서는 **`code-review` subagent 프로필**을 우선 사용한다.

- 정의 위치: `.opencode/agents/code-review.md`
- 기본 모델: `openai/gpt-5.4`

spawn 시 전달할 내용:

```
Agent(subagent_type="code-review"):
  - diff 내용 전달
  - 프로젝트 규칙 전달
  - 기존 패턴 참조 파일 경로 전달
  - 아래 리뷰 기준과 출력 형식을 프롬프트에 포함
  - grounding rules: 실제 코드에 근거한 지적만, 추측 금지
  - dig deeper: second-order 실패, edge case, 롤백 위험 체크
```

해당 프로필이 없는 런타임에서는 `general-purpose` 를 fallback 으로 사용하되, 위 제약을
프롬프트로 직접 전달한다.

### 4. 리뷰 기준

우선순위 순으로 검토한다:

| 우선순위 | 카테고리          | 검토 내용                                                 |
| -------- | ----------------- | --------------------------------------------------------- |
| 1        | **정확성**        | 로직 오류, off-by-one, null/undefined 미처리, 타입 불일치 |
| 2        | **보안**          | injection, auth 우회, 데이터 노출, OWASP top 10           |
| 3        | **데이터 무결성** | race condition, 트랜잭션 경계, migration 안전성           |
| 4        | **에러 처리**     | 실패 모드, 복구 경로, 에러 메시지 품질                    |
| 5        | **성능**          | N+1 쿼리, 불필요한 연산, 메모리 누수                      |
| 6        | **설계**          | 결합도, 책임 분리, 테스트 용이성                          |
| 7        | **일관성**        | 같은 앱 내 기존 패턴과의 일치 여부                        |
| 8        | **프로젝트 규칙** | CLAUDE.md/AGENTS.md 규칙 준수 (한글 주석, 영어 로그 등)   |

**리뷰하지 않는 것:**

- 포매팅/스타일 (linter 영역)
- 근거 없는 취향 차이
- 타입체커/린터가 잡는 문제
- 변경되지 않은 기존 코드의 문제

### 5. 출력 형식

심각도별로 그룹핑하여 출력한다. 발견사항이 없는 심각도는 생략.

```
## 코드 리뷰 결과

리뷰 대상: `feat/my-feature` vs `main` (15 files changed)

### Critical
- **file.py:42** — DB 트랜잭션 밖에서 외부 API 호출 후 commit
  데이터 불일치 위험. API 호출을 트랜잭션 이후로 이동 필요.

### Warning
- **service.ts:15** — catch 블록에서 에러를 삼키고 있음
  디버깅 시 원인 추적 불가. logger.error 추가 권장.

### Suggestion
- **handler.py:88** — 동일 쿼리가 루프 안에서 반복 실행
  N+1 쿼리 패턴. prefetch/batch 쿼리로 변경 권장.

### Consistency
- **new_service.py:1** — 기존 서비스는 `BaseService` 상속 패턴 사용 (참고: `user_service.py`)
  새 서비스도 동일 패턴 적용 권장.
```

발견사항이 없으면:

```
## 코드 리뷰 결과

리뷰 대상: `feat/my-feature` vs `main` (3 files changed)

발견된 문제 없음.
```
