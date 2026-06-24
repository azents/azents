---
name: spec-review
description: "코드 diff 가 docs/azents/spec/**/*.md 업데이트를 필요로 하는지 확인한다. 사용 시점: '/spec-review', '/spec-review staged', '/spec-review last', '/spec-review PR #N', '스펙 영향 확인해줘'."
---

# /spec-review

코드 변경과 현재 spec 의 `code_paths` 를 대조해, 어떤 spec 을 업데이트해야 하는지 판단한다. spec 은 현재 시스템만 설명한다. stale 하거나 대체된 spec 은 상태를 바꾸지 말고 삭제한다.

## Workflow

1. 대상 diff 를 고른다.
   - 기본 또는 `staged`: `git diff --cached --name-only`, `git diff --cached`
   - `last`: `git diff HEAD~1 --name-only`, `git diff HEAD~1`
   - `PR #N`: `gh pr diff N --name-only`, `gh pr diff N`
2. 변경 파일이 없으면 `No changes to analyze` 로 종료한다.
3. `docs/azents/spec/**/*.md` 를 읽고 frontmatter 의 `code_paths` 와 변경 파일을 glob 매칭한다.
4. 매칭된 spec 마다 diff 와 본문을 비교해 실제 동작, API, 데이터 모델, 권한, 에러 케이스가 달라졌는지 판단한다.
5. 결과를 spec 별로 짧게 출력한다.

## Output

영향이 있으면:

```markdown
## Spec Impact

### docs/azents/spec/domain/agent.md
- Matched files: `python/apps/azents/src/azents/services/agent_service.py`
- Update: `## Behavior` 에 agent activation 조건 변경 반영
- Update: `last_verified_at` 갱신
```

영향이 없으면:

```markdown
## Spec Impact

No spec update needed.
```

## Notes

- spec 파일 자체가 같은 diff 에 포함되어 있으면 이미 갱신 중인 것으로 보고 별도 영향 제안에서 제외한다.
- 순수 리팩터링이면 본문 변경 없이 `code_paths` 또는 `last_verified_at` 만 갱신할 수 있다.
- spec 이 더 이상 현재 시스템을 설명하지 않으면 상태를 바꾸지 말고 삭제 또는 통합을 제안한다.
