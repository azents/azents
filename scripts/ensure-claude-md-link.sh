#!/usr/bin/env bash
# 각 AGENTS.md 옆에 @AGENTS.md mention 을 가진 regular CLAUDE.md 파일이 있도록 보장한다.
#
# Claude Code 는 현재 AGENTS.md 를 native 로 읽지 않지만 (issue #6235),
# CLAUDE.md 안의 @<path> mention 은 따라간다. AGENTS.md 가 truth source 이고
# CLAUDE.md 는 그것을 가리키거나, 기존 내용 앞에서 AGENTS.md 를 import 한다.
#
# 동작:
#   - CLAUDE.md 가 regular file 이고 "@AGENTS.md" 가 있으면 -> pass
#   - CLAUDE.md 가 regular file 이고 "@AGENTS.md" 가 없으면 -> 맨 앞에 prepend
#   - CLAUDE.md 가 없으면 -> "@AGENTS.md" 내용으로 만든다
#   - CLAUDE.md 가 symlink 면 -> regular file 로 바꾼 뒤 "@AGENTS.md" 내용으로 만든다
#
# 변경이 있었으면 파일을 git add 하고 hint 출력 후 exit 1 (commit 실패 → 다시 commit
# 하라고 사용자에게 요청). pre-commit "hook fixes the issue, stages, asks retry"
# 패턴.

set -e

modified=0

for agents_md in "$@"; do
    dir=$(dirname "$agents_md")
    claude_md="$dir/CLAUDE.md"

    if [ -L "$claude_md" ]; then
        printf 'Replacing symlink with regular CLAUDE.md: %s\n' "$claude_md"
        rm "$claude_md"
        printf '@AGENTS.md\n' > "$claude_md"
        git add "$claude_md"
        modified=1
        continue
    fi

    if [ ! -e "$claude_md" ]; then
        printf 'Creating %s\n' "$claude_md"
        printf '@AGENTS.md\n' > "$claude_md"
        git add "$claude_md"
        modified=1
        continue
    fi

    if ! grep -qF '@AGENTS.md' "$claude_md"; then
        printf 'Prepending @AGENTS.md mention to %s\n' "$claude_md"
        tmp_file=$(mktemp)
        printf '@AGENTS.md\n\n' > "$tmp_file"
        tee -a "$tmp_file" < "$claude_md" > /dev/null
        mv "$tmp_file" "$claude_md"
        git add "$claude_md"
        modified=1
    fi
done

if [ "$modified" -eq 1 ]; then
    printf 'CLAUDE.md file(s) updated and staged. Please commit again.\n'
    exit 1
fi

exit 0
