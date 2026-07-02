---
name: github-markdown-bodies
description: "Use when writing multiline Markdown bodies for GitHub PR descriptions, issue comments, review comments, or discussion comments with the `gh` CLI. Use for: (1) long PR descriptions, (2) issue comments, (3) review bodies, (4) cases where raw `\\n` appears or escaping breaks."
---

# Writing GitHub Markdown Bodies with the `gh` CLI

Putting multiline Markdown directly into `gh` inline `-m` / `--body` arguments often breaks because of shell escaping rules. Common symptoms:

- Unwanted escapes such as `\\` or `\` appear literally in the body.
- `\n` appears as raw text instead of a newline.
- Backticks are interpreted as command substitution and disappear or cause errors.
- `$variable` is expanded unexpectedly or becomes an empty string.

Use the patterns below **always**. Inline `--body "..."` is allowed only for single-line bodies without special characters.

## Pattern A: heredoc → `--body-file -` (most common)

```bash
gh pr comment 1234 --body-file - <<'EOF'
## Work Summary

- bullet 1
- bullet 2 (code references such as `gh api` stay literal)

```bash
echo "example"
```

@user mentions are OK. $VAR also stays literal because it is not expanded.
EOF
```

Key points:

- `<<'EOF'` (single-quoted EOF) disables shell expansion. Backticks, `$`, and `\` all stay literal.
- `--body-file -` reads the heredoc output from stdin.
- Backticks and triple backticks can be used freely in the body. No escaping is required.

## Pattern B: temporary file → `--body-file <path>`

Use this for long bodies, bodies assembled in multiple steps, or when reusing the same body across commands:

```bash
cat > /tmp/body.md <<'EOF'
... long Markdown ...
EOF

gh pr edit 1234 --body-file /tmp/body.md
# or
gh issue comment 5678 --body-file /tmp/body.md
rm /tmp/body.md
```

## Pattern C (fallback): call `gh api` directly

If `gh pr edit --body-file` silently fails, which can happen for some Markdown edge cases where the command exits 0 but the body is not updated, PATCH through the REST API:

```bash
gh api --method PATCH /repos/{owner}/{repo}/pulls/{N} \
  -F body=@/tmp/body.md
```

Issue comments use the same approach:

```bash
gh api /repos/{owner}/{repo}/issues/{N}/comments \
  -F body=@/tmp/body.md
```

Discussions require GraphQL. Pass the body with `-F body=@file`:

```bash
gh api graphql \
  -f query='mutation($id:ID!,$body:String!){
    addDiscussionComment(input:{discussionId:$id,body:$body}){comment{id}}
  }' \
  -F id="<discussion_node_id>" \
  -F body=@/tmp/body.md
```

## Never use these patterns

```bash
# ❌ Inline body with literal \n newlines
gh pr comment 1234 -b "## Title\n\n- bullet"

# ❌ Multiline inline body — escaping becomes fragile
gh pr comment 1234 -b "## Title

- bullet"

# ❌ Unquoted heredoc — backticks and $ are interpreted by the shell
gh pr comment 1234 --body-file - <<EOF
$variable expanded! `command substituted!`
EOF
```

## Debug checklist

When the body is malformed:

1. Inspect the stored body: `gh pr view <N> --json body --jq .body`.
2. If literal `\n` appears, the body was probably built with inline `--body "..."` plus `\n`. Rewrite it with the heredoc pattern and update with `gh pr edit --body-file -`.
3. If backticks disappeared, an unquoted heredoc was used. Rewrite with `<<'EOF'`.
4. If `$VAR` became empty, shell expansion occurred. Use a single-quoted heredoc or a file.

## Valid single-line case

If the body is truly one line and has no special characters, `-b "..."` is OK:

```bash
gh issue comment 1234 -b "Fixed. See PR #5678 for details."
```

Otherwise, always use a heredoc or a file.
