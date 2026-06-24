---
name: codingbot-setup
description: |
  Codingbot 초기 설정 가이드. GitHub App 생성, gh CLI 설치, config.yaml 작성, git config, Python 의존성까지 step-by-step으로 진행.
  사용 시점: (1) 새 머신에서 codingbot을 처음 설정할 때, (2) 새 레포에 codingbot을 추가할 때, (3) 설정이 깨져서 처음부터 다시 할 때.
---

# Codingbot Setup

새 환경에서 codingbot을 설정하는 step-by-step 가이드. 각 단계를 순서대로 진행하며, 각 단계 완료 후 검증한다.

**진행 방식**: 각 Phase를 사용자에게 안내하고, 사용자가 직접 수행해야 하는 단계(GitHub 웹 UI 등)는 명확히 구분한다. CLI로 자동화 가능한 단계는 직접 실행한다.

## Phase 1: 사전 요구사항 확인

아래 도구들이 설치되어 있는지 확인한다. 없으면 설치를 안내한다.

### 1-1. Python 3.14+

```bash
python3 --version
```

없으면: `uv python install 3.14` 안내.

### 1-2. uv

```bash
uv --version
```

없으면: `curl -LsSf https://astral.sh/uv/install.sh | sh` 안내.

### 1-3. gh CLI

```bash
gh --version
```

없으면 OS별 설치 안내:
- **Ubuntu/Debian**: `sudo apt install gh` 또는 [공식 설치 가이드](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
- **macOS**: `brew install gh`

gh CLI는 사용자 본인의 인증용이 아니라, **codingbot의 gh 래퍼가 실제 바이너리를 찾기 위해** 필요하다. 래퍼(`.claude/codingbot/bin/gh`)가 PATH에서 실제 gh를 찾아 GitHub App 토큰을 주입한다.

### 1-4. Claude Code CLI

```bash
claude --version
```

없으면: `npm install -g @anthropic-ai/claude-code` 안내.

## Phase 2: GitHub App 생성

**이 단계는 사용자가 GitHub 웹 UI에서 직접 수행한다.**

### 2-1. GitHub App 생성 페이지 이동

사용자에게 안내:

> GitHub → Settings → Developer settings → GitHub Apps → **New GitHub App**
>
> 또는 Organization이면: Organization Settings → Developer settings → GitHub Apps → New GitHub App

### 2-2. 기본 정보 입력

| 필드 | 값 |
|------|-----|
| GitHub App name | `{원하는 이름}` (예: `geonu-coding-bot`) |
| Homepage URL | 레포 URL |
| Webhook | **Active 체크 해제** (polling 방식이므로 webhook 불필요) |

### 2-3. Repository Permissions 설정

| Permission | Access |
|-----------|--------|
| **Actions** | Read-only |
| **Checks** | Read-only |
| **Contents** | Read and write |
| **Discussions** | Read and write |
| **Issues** | Read and write |
| **Metadata** | Read-only (자동 선택됨) |
| **Pull requests** | Read and write |

Account permissions은 기본값(None) 유지.

### 2-4. 생성 완료 후 정보 수집

App 생성 후 General 페이지에서:

1. **App ID** 기록 — 페이지 상단 "App ID" 필드
2. **Private key 생성** — "Generate a private key" 클릭 → `.pem` 파일 다운로드

사용자에게 App ID와 private key 파일 경로를 물어본다.

### 2-5. App 설치

> GitHub App 페이지 → Install App → 대상 레포 선택 → Install

설치 후 URL에서 **Installation ID** 확인:
- URL 패턴: `https://github.com/settings/installations/{installation_id}`
- 또는 `gh api /repos/{owner}/{repo}/installation --jq '.id'` (gh 인증된 상태에서)

사용자에게 Installation ID를 물어본다.

## Phase 3: Private Key 배치

사용자에게 private key 파일을 안전한 위치에 복사하도록 안내한다.

```bash
# 권장 위치
mkdir -p ~/.config/codingbot
cp ~/Downloads/{downloaded-key}.pem ~/.config/codingbot/private-key.pem
chmod 600 ~/.config/codingbot/private-key.pem
```

경로는 사용자가 다른 곳을 선호하면 그에 맞춘다. 절대 경로로 기록한다.

## Phase 4: config.yaml 작성

Phase 2-3에서 수집한 정보로 `python/apps/codingbot/config.yaml`을 작성한다. `.gitignore`에 이미 포함되어야 한다.

```yaml
github_app:
  app_id: {수집한 App ID}
  private_key_path: {Phase 3의 private key 절대 경로}
  installation_id: {수집한 Installation ID}
repo: {owner}/{repo}
repo_local_path: {레포 절대 경로}
allowed_users:
  - {GitHub username}
poll_interval_sec: 5
worktree_base_dir: .claude/worktrees
max_concurrent_sessions: 5
permission_mode: auto
```

작성 후 `.gitignore`에 `python/apps/codingbot/config.yaml`이 있는지 확인한다. 없으면 추가한다 (private key 경로가 포함되므로).

작성 후 본 repo에서도 `git push`가 자동으로 되도록 credential helper를 설정한다 (스크립트가 자동으로 config.yaml을 찾으므로 경로 지정 불필요):

```bash
cd {repo_root}
SCRIPT_DIR="{repo_root}/.claude/codingbot/bin"
git config credential.helper "!f() { echo \"protocol=https\"; echo \"host=github.com\"; echo \"username=x-access-token\"; echo \"password=\$($SCRIPT_DIR/gh-app-token)\"; }; f"
```

## Phase 5: Python 의존성 설치

```bash
cd {repo_root}/python/apps/codingbot && uv sync
```

## Phase 6: 검증

### 6-1. GitHub App 인증 테스트

```bash
cd {repo_root}
.claude/codingbot/bin/gh-app-token
```

토큰 문자열이 출력되면 성공. 에러 시 `python/apps/codingbot/config.yaml`의 app_id, private_key_path, installation_id 확인.

### 6-2. gh 래퍼 테스트

```bash
cd {repo_root}
PATH=".claude/codingbot/bin:$PATH" gh api /repos/{owner}/{repo} --jq '.full_name'
```

`{owner}/{repo}`가 출력되면 성공.

### 6-3. Bot identity 확인

`/app` endpoint는 JWT Bearer 인증이 필요하므로 gh 래퍼가 아닌 `--jwt` 플래그를 사용한다.

```bash
cd {repo_root}
JWT=$(.claude/codingbot/bin/gh-app-token --jwt)
curl -sS --fail -H "Authorization: Bearer $JWT" -H "Accept: application/vnd.github+json" https://api.github.com/app | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{d[\"slug\"]} (id: {d[\"id\"]})')"
```

App slug과 ID가 출력되면 성공.

### 6-4. setup-git 테스트 (임시 디렉토리)

```bash
cd /tmp && git init codingbot-test && cd codingbot-test
CODINGBOT_CONFIG={repo_root}/python/apps/codingbot/config.yaml PATH="{repo_root}/.claude/codingbot/bin:$PATH" {repo_root}/.claude/codingbot/bin/setup-git
git config user.name   # → {slug}[bot]
git config user.email  # → {app_id}+{slug}[bot]@users.noreply.github.com
cd /tmp && rm -rf codingbot-test
```

### 6-5. Runner 시작 테스트

```bash
cd {repo_root}/python/apps/codingbot
uv run python src/cli/runner.py --config config.yaml
```

Ctrl+C로 종료. 에러 없이 polling이 시작되면 설정 완료.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `gh CLI not found outside of runner wrapper` | 시스템에 gh가 미설치 | Phase 1-3 참조 |
| `401 Unauthorized` (gh-app-token) | App ID/Installation ID 불일치 또는 private key 오류 | config.yaml 값 재확인, private key 재생성 |
| `403 Resource not accessible` | App에 해당 permission이 없음 | GitHub App → Permissions 재설정 |
| `jwt.exceptions.DecodeError` | private key 파일 형식 오류 | `.pem` 파일이 맞는지, 권한(600)이 맞는지 확인 |
| `FileNotFoundError: config.yaml` | CODINGBOT_CONFIG 환경변수 미설정 또는 경로 오류 | 절대 경로로 CODINGBOT_CONFIG 지정 |
| `ModuleNotFoundError` | Python 의존성 미설치 | Phase 5 재실행 |
