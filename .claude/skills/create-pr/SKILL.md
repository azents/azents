---
name: create-pr
description: "현재 브랜치에서 GitHub PR을 생성한다. Proactively use when: (1) '/create-pr', (2) 'PR 만들어줘', 'PR 올려줘', 'open/create/submit a PR', (3) 이미 준비된 브랜치를 PR로 열 때. 코드 리뷰나 spec-review는 실행하지 않고 PR 생성에만 집중한다."
---

# PR 생성 (/create-pr)

현재 브랜치를 GitHub PR로 만든다. 이 스킬은 PR 생성만 담당한다. 품질 게이트(`/code-review`)나 nointern living spec 게이트(`/spec-review`)가 필요한 출하 플로우에서는 `/ship-pr`이 이 스킬을 호출한다.

## 실행 순서

### 1. 상태 확인

- 현재 브랜치를 확인한다: `git branch --show-current`.
- 열린 PR이 이미 있는지 확인한다: `gh pr list --head "$(git branch --show-current)" --state open --json number,url`.
- 열린 PR이 있으면 새 PR을 만들지 말고 기존 PR URL만 보고한다.
- base branch는 기본 `main`으로 둔다. branch가 명확히 다른 base에서 갈라졌다면 upstream 또는 사용자 지시를 따른다.
- `git log <base>..HEAD`와 `git status --short`가 모두 비어 있으면 PR 대상 변경이 없으므로 중단한다.

### 2. 미커밋 변경 정리

`git status --short`가 비어 있으면 이 단계는 건너뛴다. 변경이 있으면 관련 파일만 stage해서 한 커밋으로 정리한다.

- `git add -A` 대신 PR에 포함할 파일 경로를 명시한다.
- `.env`, credential, 큰 바이너리, 임시 scratch 파일처럼 보이는 파일은 stage 전에 사용자에게 확인한다.
- 명확히 무관한 변경이 섞여 있으면 커밋 분리 여부를 사용자에게 묻는다.
- 최근 커밋 스타일을 확인한다: `git log --oneline -5`.
- 커밋 메시지는 conventional style을 기본으로 한다: `<type>(<scope>): <summary>`.
- hook 실패 시 원인을 고치고 새 커밋을 만든다.

### 3. Push

- remote tracking이 없으면 `git push -u origin <branch>`를 사용한다.
- fast-forward 가능한 일반 push는 자동으로 수행한다.
- remote가 diverged되어 history rewrite가 필요한 경우 사용자 확인을 받는다.
- 사용자의 요청 자체가 amend, rebase, squash, 커밋 정리처럼 history rewrite를 전제로 한 작업이면 `--force-with-lease`를 사용할 수 있다.
- `--force`는 사용하지 않는다.

### 4. PR 제목 작성

PR title은 최근 commit/PR 스타일을 참고하되, 기본은 conventional style이다.

예:

```text
fix(nointern): stabilize chat session event ordering
chore(opencode): tune DCP context nudges
```

### 5. PR 본문 작성

PR body는 파일로 작성하고 `--body-file`로 전달한다. inline heredoc을 `gh pr create` 인자에 직접 넣지 않는다.

PR title과 body의 언어는 현재 대화 언어를 따른다. 한국어로 대화하고 있었다면 한국어로, 영어로 대화하고 있었다면 영어로 쓴다. 사용자가 특정 언어를 요청하면 그 언어를 따른다.

#### Summary 원칙

- PR body는 `## Summary`로 시작한다.
- 첫 문장은 이 PR의 정체를 바로 식별한다.
- 배경, 동기, 구현 히스토리로 시작하지 않는다.
- 파일 목록이나 diff 해설을 쓰지 않는다. Files changed 탭이 이미 그 역할을 한다.
- 변경을 동작, 기능, 정책 단위로 설명한다.
- 간단한 PR은 한 문장 또는 1-3개 bullet로 끝낸다.
- 긴 `so ...`, `which ...` 문장은 action과 effect를 나눠서 쓴다.

Bad:

```markdown
## Summary

기존 흐름에 문제가 있어서 필요했습니다.

- engine_adapter.py를 변경함
- model_factory.py를 변경함
- 파일을 S3에 저장해서 parent agent가 나중에 읽을 수 있음
```

Good:

```markdown
## Summary

nointern agent run에서 SDK builtin tool routing을 복구합니다.

- builtin tool 요청을 provider별 adapter로 routing합니다.
- 생성 이미지를 event history에 base64로 저장하지 않고 attachment로 보존합니다.
- 생성 파일을 S3에 저장합니다. parent agent가 나중에 읽을 수 있습니다.
```

#### 선택적 block

복잡한 PR에서만 필요한 block을 추가한다. block 이름은 제목처럼 단독 줄에 두고, 설명은 다음 문단이나 bullet에 쓴다.

- `**Background**`: 구현 히스토리가 아니라 왜 필요한지, 어떤 사용자/운영상 문제를 줄이는지, 어떤 판단 맥락이 있는지를 설명한다.
- `**What changed**`: 파일별 목록이 아니라 동작, 기능, 정책 단위로 묶는다.
- `**Review focus**`: 특히 확인해야 할 리스크, 경계조건, 의도적으로 하지 않은 일을 적는다.
- `**Screenshots**`: UI/UX 변경이 있을 때만 넣는다.
- `## Test Plan`: 검증 내용을 남기는 것이 PR 이해에 도움이 될 때만 넣는다.
- `## Spec Impact`: spec 영향이 명확할 때만 넣는다. 확실하지 않으면 생략하거나 사용자에게 짧게 확인한다.

예:

```markdown
## Summary

중단된 nointern agent run의 shutdown recovery를 복구합니다.

**Background**

shutdown이 terminal failure로 기록되어 중단된 run을 resume할 수 없었습니다.

**What changed**

- shutdown으로 중단된 run을 recovery 대상으로 보존합니다.
- 명시적인 실패는 계속 terminal 상태로 유지합니다.

**Review focus**

- shutdown 경로와 실제 실패 경로가 계속 올바르게 분리되는지 확인합니다.
```

### 6. PR 생성

본문 파일 내용을 확인한 뒤 PR을 만든다.

```bash
gh pr create --base <base> --head <branch> --title "<title>" --body-file <body-file>
```

### 7. 결과 보고

- PR URL
- 새 커밋을 만들었는지 여부
- push 방식: normal / upstream set / force-with-lease
- 실행한 검증 또는 미실행 사유
- `Spec Impact` 섹션을 넣었는지 여부

## 안전장치

- 기존 PR이 있으면 새 PR을 만들지 않는다.
- secret, credential, 큰 바이너리 의심 파일은 사용자 확인 없이 commit하지 않는다.
- destructive git 명령을 사용하지 않는다.
