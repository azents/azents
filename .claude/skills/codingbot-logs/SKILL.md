---
name: codingbot-logs
description: |
  Codingbot 세션 로그 확인. 실행 중인 세션의 진행상황을 실시간으로 보거나, 완료된 세션의 로그를 확인.
  사용 시점: (1) 'codingbot 뭐하고있어?', (2) '세션 로그 보여줘', (3) '진행상황 확인해줘'.
---

# Codingbot 세션 로그 확인

## 워크플로우

### 1. 활성 세션 확인

```bash
cat .claude/codingbot/state/sessions.yaml
```

`running: true`인 세션의 `worktree` 경로를 확인한다.

### 2. 로그 확인

각 세션의 로그는 worktree 루트의 `claude-session.log`에 기록된다.

```bash
# 최근 로그 확인
tail -50 {worktree_path}/claude-session.log

# 실시간 모니터링 (사용자에게 안내)
# tail -f {worktree_path}/claude-session.log
```

실시간 모니터링이 필요하면 사용자에게 `tail -f` 명령어를 안내한다.

### 3. 세션 인수 (handover)

실행 중인 세션이 끝난 후 인터랙티브하게 이어가려면:

```bash
cd {worktree_path} && claude --resume {session_name}
```
