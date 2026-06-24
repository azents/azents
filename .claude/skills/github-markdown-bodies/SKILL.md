---
name: github-markdown-bodies
description: "GitHub PR description / 이슈/리뷰/discussion 코멘트의 멀티라인 markdown 본문을 `gh` CLI 로 작성할 때 사용. 사용 시점: (1) 'PR description 길게', (2) '이슈 코멘트', (3) '리뷰 본문', (4) `\\n` 이 raw 노출되거나 escape 가 망가지는 증상."
---

# GitHub Markdown 본문 작성 (`gh` CLI)

`gh` 의 `-m` / `--body` 인라인 인자에 멀티라인 markdown 을 넣으면 bash escape
규칙 때문에 자주 깨진다. 흔한 증상:

- 불필요한 escape (`\\`, `\` 가 본문에 그대로 노출)
- `\n` 이 줄바꿈으로 안 풀리고 raw 문자열로 보임
- backtick 이 command substitution 으로 해석되어 사라지거나 에러
- `$variable` 이 의도와 다르게 치환 / 또는 빈 문자열로

아래 패턴을 **반드시** 사용한다. 인라인 `--body "..."` 는 단 한 줄 + 특수문자
없을 때만.

## 패턴 A: heredoc → `--body-file -` (가장 흔히 사용)

```bash
gh pr comment 1234 --body-file - <<'EOF'
## 작업 요약

- bullet 1
- bullet 2 (코드 인용은 `gh api` 처럼 그대로)

```bash
echo "예시"
```

@user 멘션도 OK. $VAR 도 그대로 (확장 안 됨).
EOF
```

핵심:

- `<<'EOF'` (홑따옴표 EOF) — shell expansion 비활성화. backtick / `$` / `\` 모두
  literal.
- `--body-file -` — heredoc 출력을 stdin 으로 받음.
- 본문 안 backtick / triple backtick 자유롭게 사용 가능. escape 불요.

## 패턴 B: 임시 파일 → `--body-file <path>`

긴 본문 / 여러 단계로 조립 / 여러 명령에 같은 본문 재사용 시:

```bash
cat > /tmp/body.md <<'EOF'
... 긴 markdown ...
EOF

gh pr edit 1234 --body-file /tmp/body.md
# 또는
gh issue comment 5678 --body-file /tmp/body.md
rm /tmp/body.md
```

## 패턴 C (fallback): `gh api` 로 직접 호출

`gh pr edit --body-file` 이 silent fail 하는 경우 (일부 markdown edge case 에서
변경 안 적용되고 종료 코드만 0). REST API 로 직접 PATCH:

```bash
gh api --method PATCH /repos/{owner}/{repo}/pulls/{N} \
  -F body=@/tmp/body.md
```

이슈 코멘트도 동일:

```bash
gh api /repos/{owner}/{repo}/issues/{N}/comments \
  -F body=@/tmp/body.md
```

Discussion 은 GraphQL 만 가능. 본문은 `-F body=@file` 로:

```bash
gh api graphql \
  -f query='mutation($id:ID!,$body:String!){
    addDiscussionComment(input:{discussionId:$id,body:$body}){comment{id}}
  }' \
  -F id="<discussion_node_id>" \
  -F body=@/tmp/body.md
```

## 절대 사용 금지

```bash
# ❌ 줄바꿈을 \n 으로 박아넣은 인라인
gh pr comment 1234 -b "## Title\n\n- bullet"

# ❌ 멀티라인 인라인 — escape 지옥
gh pr comment 1234 -b "## Title

- bullet"

# ❌ unquoted heredoc — backtick / $ 가 shell 해석됨
gh pr comment 1234 --body-file - <<EOF
$variable expanded! `command substituted!`
EOF
```

## 디버그 체크리스트

본문이 이상하게 들어갔을 때:

1. `gh pr view <N> --json body --jq .body` 로 실제 저장된 본문 확인
2. `\n` literal 보이면 → 인라인 `--body "..."` + `\n` 으로 만든 것. heredoc 패턴
   으로 다시 작성 후 `gh pr edit --body-file -` 로 갱신
3. backtick 이 사라졌으면 → unquoted heredoc 사용. `<<'EOF'` 로 다시
4. `$VAR` 가 빈 문자열로 → 동상

## 한 줄 인용 가능 케이스

본문이 진짜 한 줄 + 특수문자 없으면 `-b "..."` 도 OK:

```bash
gh issue comment 1234 -b "수정 완료. PR #5678 에 자세한 내용."
```

이게 아니면 무조건 heredoc 또는 파일.
