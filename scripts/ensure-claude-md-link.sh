#!/usr/bin/env bash
# Ensure each AGENTS.md has a regular CLAUDE.md file beside it that mentions @AGENTS.md.
#
# Claude Code does not currently read AGENTS.md natively (issue #6235),
# but it follows @<path> mentions in CLAUDE.md. AGENTS.md is the source of truth,
# and CLAUDE.md either points to it or imports it before existing content.
#
# Behavior:
#   - If CLAUDE.md is a regular file containing "@AGENTS.md" -> pass
#   - If CLAUDE.md is a regular file without "@AGENTS.md" -> prepend it
#   - If CLAUDE.md does not exist -> create it with "@AGENTS.md"
#   - If CLAUDE.md is a symlink -> replace it with a regular file containing "@AGENTS.md"
#
# If anything changed, git-add the file, print a hint, and exit 1 (the commit fails and
# asks the user to commit again). This follows the pre-commit "hook fixes, stages, asks retry"
# pattern.

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
