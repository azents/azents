---
name: stacked-prs
description: "Stacked PR 관리 — 순차적으로 쌓인 PR 브랜치들의 rebase, 머지, base 변경을 처리. 사용 시점: (1) stacked PR 머지 요청 (예: 'PR 머지해', '스택 머지해'), (2) 앞 브랜치 수정 후 뒤 브랜치 rebase 필요 (예: '뒤에 브랜치도 rebase해'), (3) stacked PR 상태 확인 (예: '스택 상태 확인해')."
---

# Stacked PR 관리

## Stacked PR이란

브랜치를 순차적으로 쌓아 각 PR이 이전 브랜치를 base로 하는 구조.

```
main ← branch-A ← branch-B ← branch-C
PR#1: A→main   PR#2: B→A   PR#3: C→B
```

머지는 앞에서부터 순서대로만 가능하다. 앞 브랜치를 수정하면 뒤 브랜치들을 모두 rebase해야 한다.

## 워크플로우

### 1. 앞 브랜치 수정 후 후행 rebase

앞 브랜치에 커밋을 추가/수정한 뒤, 뒤 브랜치들을 순차적으로 rebase한다.

```bash
# 수정 전 branch-A의 tip SHA를 기록해둔다
OLD_A_TIP=$(git rev-parse branch-A)

# branch-A에 변경사항 커밋 후...

# branch-B를 새 branch-A 위에 rebase
git rebase --onto branch-A $OLD_A_TIP branch-B

# branch-C를 새 branch-B 위에 rebase (OLD_B_TIP도 미리 기록)
git rebase --onto branch-B $OLD_B_TIP branch-C
```

**핵심**: squash merge 등으로 커밋 SHA가 바뀌면 `--onto`에 정확한 old tip SHA를 써야 한다. 단순 `git rebase branch-A`는 conflict이 발생할 수 있다.

### 2. 단일 PR 머지

스택에서 가장 앞의 PR 하나를 머지하는 절차:

1. **후행 PR base 변경**: 다음 PR의 base를 `main`으로 변경. 머지 시 `--delete-branch`로 base 브랜치가 삭제되는데, base가 삭제된 PR은 GitHub에서 reopen이 불가하고 자동으로 닫힌다. 머지 전에 base를 `main`으로 바꿔놓으면 이 문제를 방지한다.

   ```bash
   # GitHub API로 base 변경 (gh pr edit가 classic projects 에러 시 API 직접 사용)
   gh api repos/{owner}/{repo}/pulls/{next_pr_number} -X PATCH -f base=main
   ```

2. **머지**: squash merge + 브랜치 삭제

   ```bash
   gh pr merge {pr_number} --squash --delete-branch
   ```

3. **후행 브랜치 cherry-pick**: main 위에 후행 커밋들을 cherry-pick

   `git rebase --onto`는 squash merge 후 커밋이 동일 변경으로 인식되어 drop되는 문제가 있다.
   대신 cherry-pick을 사용한다.

   ```bash
   git fetch origin main
   # 후행 브랜치의 고유 커밋 SHA를 미리 기록해둔다
   git checkout next-branch
   git reset --hard origin/main
   git cherry-pick {commit1} {commit2} ...
   ```

   **반드시 결과 확인 후 push:**
   ```bash
   git log --oneline origin/main..next-branch   # 커밋 확인
   git diff --stat origin/main..next-branch      # 파일 변경 확인
   # 확인 후에만 push
   git push origin next-branch --force-with-lease
   ```

4. 다음 PR로 반복

### 3. 일괄 머지 (특정 PR까지 전부 머지)

사용자가 "PR #N까지 다 머지해"라고 요청할 때의 절차:

#### 사전 검증

1. **Conflict 확인**: 각 PR에 merge conflict이 없는지 확인. 있으면 rebase로 해소
2. **커밋 정합성**: 마지막 PR 브랜치가 앞의 모든 변경사항을 포함하는지 확인
   ```bash
   # branch-C가 branch-B의 모든 변경을 포함하는지 확인
   git log --oneline branch-B..branch-C  # branch-C에만 있는 커밋
   git merge-base --is-ancestor branch-B branch-C && echo "OK"
   ```
3. **CI 통과 대기**: 머지를 시작하기 전에 모든 대상 PR의 CI가 통과될 때까지 대기
   ```bash
   gh pr checks {pr_number}
   ```

이 단계에서 전체 대상 PR의 approval, mergeability, unresolved review thread=0, CI success 를 확인한다.
일괄 머지를 시작한 뒤에는 후행 브랜치 base 변경, reset, cherry-pick, force-with-lease push 때문에 GitHub 가 새 check run 을 만들 수 있다.
이 새 pending check 는 이미 검증된 동일 변경을 main 위에 재적용하면서 생기는 재검증 신호이므로 기다리지 않는다.

#### 연속 머지

사전 검증이 모두 통과하면, cherry-pick 후에도 코드 내용이 동일하므로 CI 재검토 없이 순차 머지한다:

```
for each PR in stack (앞→뒤 순서):
  1. 다음 PR base를 main으로 변경 (마지막 PR이면 생략)
  2. gh pr merge --squash --delete-branch
  3. git fetch origin main
  4. 후행 브랜치를 origin/main으로 reset + cherry-pick
  5. git log/diff로 결과 확인
  6. git push --force-with-lease
  7. 새로 생긴 pending CI를 기다리지 말고 다음 PR 머지를 계속 진행
```

**중요**: cherry-pick 후 CI가 동일한 이유 — squash merge 전에 이미 모든 PR이 CI 통과 상태이고, cherry-pick은 동일 변경을 적용할 뿐이므로 결과가 동일하다.

**금지**: 일괄 머지 중 후행 브랜치 push 로 `SUCCESS → PENDING` 이 된 check 를 기다리느라 멈추지 않는다. 사전 전체 CI 통과를 확인했다면, push 직후 PR 이 일시적으로 `PENDING`/`CONFLICTING`/`UNKNOWN` 으로 보이더라도 `git log`/`git diff --stat` 으로 cherry-pick 결과를 검증하고 다음 PR로 진행한다. 단, cherry-pick conflict 를 직접 해결한 경우에는 해결 결과를 확인한 뒤 push한다.

### 4. PR을 reopen할 수 없는 경우

base 브랜치가 삭제되면 GitHub에서 PR reopen이 불가하다. 이 경우:

```bash
# 새 PR 생성
gh pr create --base main --head {branch} --title "..." --body "..." --reviewer {reviewer}
```

## 주의사항

- **머지 순서**: 반드시 앞에서부터 순서대로. 뒤 PR을 먼저 머지하면 안 된다
- **force push**: 항상 `--force-with-lease` 사용. `--force`는 다른 사람 작업을 덮어쓸 위험
- **rebase 전 unstaged 변경**: rebase 전에 working tree가 clean한지 확인. 필요시 `git stash`
- **approve 확인**: 머지 전 PR이 approve 상태인지 확인. approve 없으면 머지하지 않는다
- **squash merge 후 old tip**: squash merge하면 원래 커밋들이 하나로 합쳐지므로, 후행 rebase 시 old tip은 squash 전의 원래 브랜치 tip SHA를 사용해야 한다
