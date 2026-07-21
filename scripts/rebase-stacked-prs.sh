#!/usr/bin/env bash
# Rebase stacked PR branches from the first branch through the last.
# Stop immediately on conflict while preserving the active rebase state.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/rebase-stacked-prs.sh [--base <base>] [--push] <branch1> <branch2> [...]

Rebase a stacked PR chain in order:

  <base> <- branch1 <- branch2 <- ...

branch1 is rebased onto <base>. Each downstream branch is rebased with
`git rebase --onto <new-parent> <old-parent-tip> <branch>`.

Options:
  --base <base>  Base for the first branch. Defaults to origin/main.
  --push         Push rebased branches with --force-with-lease after success.
  -h, --help     Show this help.

On conflict, the script stops immediately and leaves the repository in the
conflicted rebase state so you can resolve or abort it.
EOF
}

base="origin/main"
push_after=0
branches=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --base)
            if [ "$#" -lt 2 ]; then
                printf 'error: --base requires a value\n' >&2
                exit 2
            fi
            base="$2"
            shift 2
            ;;
        --push)
            push_after=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            while [ "$#" -gt 0 ]; do
                branches+=("$1")
                shift
            done
            ;;
        -*)
            printf 'error: unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
        *)
            branches+=("$1")
            shift
            ;;
    esac
done

if [ "${#branches[@]}" -lt 1 ]; then
    usage >&2
    exit 2
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    printf 'error: working tree must be clean before rebasing stacked PRs\n' >&2
    exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
    printf 'error: working tree has untracked files; clean or ignore them before rebasing\n' >&2
    exit 1
fi

if [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; then
    printf 'error: a rebase is already in progress\n' >&2
    exit 1
fi

current_branch=$(git branch --show-current)
if [ -z "$current_branch" ]; then
    printf 'error: detached HEAD is not supported\n' >&2
    exit 1
fi

if [ "$base" = "origin/main" ]; then
    git fetch origin main:refs/remotes/origin/main
fi

if ! git rev-parse --verify --quiet "$base^{commit}" >/dev/null; then
    printf 'error: base is not a commit: %s\n' "$base" >&2
    exit 1
fi

declare -A old_tips

for branch in "${branches[@]}"; do
    if ! git rev-parse --verify --quiet "$branch^{commit}" >/dev/null; then
        printf 'error: branch is not a commit: %s\n' "$branch" >&2
        exit 1
    fi
    old_tips["$branch"]=$(git rev-parse "$branch")
done

printf 'Rebasing %s onto %s\n' "${branches[0]}" "$base"
if ! git switch "${branches[0]}" >/dev/null; then
    printf 'error: failed to switch to %s\n' "${branches[0]}" >&2
    exit 1
fi

if ! git rebase "$base"; then
    printf '\nerror: conflict while rebasing %s onto %s\n' "${branches[0]}" "$base" >&2
    printf 'Resolve conflicts and run `git rebase --continue`, or run `git rebase --abort`.\n' >&2
    exit 1
fi

for ((i = 1; i < ${#branches[@]}; i++)); do
    branch=${branches[$i]}
    parent=${branches[$((i - 1))]}
    old_parent_tip=${old_tips[$parent]}

    printf 'Rebasing %s onto %s from old parent tip %s\n' "$branch" "$parent" "$old_parent_tip"
    if ! git switch "$branch" >/dev/null; then
        printf 'error: failed to switch to %s\n' "$branch" >&2
        exit 1
    fi

    if ! git rebase --onto "$parent" "$old_parent_tip" "$branch"; then
        printf '\nerror: conflict while rebasing %s onto %s\n' "$branch" "$parent" >&2
        printf 'Old parent tip: %s\n' "$old_parent_tip" >&2
        printf 'Resolve conflicts and run `git rebase --continue`, or run `git rebase --abort`.\n' >&2
        exit 1
    fi
done

if [ "$push_after" -eq 1 ]; then
    for branch in "${branches[@]}"; do
        printf 'Pushing %s with --force-with-lease\n' "$branch"
        git push origin "$branch" --force-with-lease
    done
fi

git switch "$current_branch" >/dev/null
printf 'Rebased stacked PR branches successfully.\n'
