---
name: python-dependency-update
description: Python 프로젝트의 의존성을 업데이트합니다. Dependabot 보안 알림 해결, 패키지 버전 업그레이드, transitive dependency 업데이트에 사용합니다. 사용 시점 - (1) Dependabot 보안 알림 해결 요청, (2) 특정 패키지 업데이트 요청, (3) 보안 취약점 패치.
---

# Python Dependency Update

Python 모노레포(uv workspace)에서 의존성을 업데이트하는 워크플로우.

## 사전 준비

uv 명령은 반드시 해당 서브프로젝트 디렉토리에서 실행한다.

```bash
cd /path/to/azents/python/apps/{project-name}
# 또는
cd /path/to/azents/python/libs/{project-name}
```

## 업데이트 플로우

### 1단계: 대상 파악

업데이트할 패키지가 direct dependency인지 transitive dependency인지 확인한다.

```bash
# pyproject.toml에 직접 명시되어 있는지 확인
grep -r "{package-name}" python/apps/*/pyproject.toml python/libs/*/pyproject.toml

# lockfile에서 현재 버전 확인
grep -A2 'name = "{package-name}"' python/apps/{project}/uv.lock
```

### 2단계: 업데이트 실행

#### Case A: Direct dependency (pyproject.toml에 있는 경우)

pyproject.toml의 버전을 목표 버전으로 수정한 뒤 lock을 갱신한다.

버전 지정 규칙 (python-dependency-management 스킬과 동일):
- **앱(`apps/*`)의 일반 의존성**: 정확한 버전 (`==`)
- **앱(`apps/*`)의 dev 의존성**: 최소 버전 (`>=`)
- **라이브러리(`libs/*`)의 모든 의존성**: 최소 버전 (`>=`)

```bash
# pyproject.toml에서 버전 직접 수정 (Edit 도구 사용)
# 앱 예: "aiohttp==3.9.0" → "aiohttp==3.11.12"
# 라이브러리 예: "aiohttp>=3.9.0" → "aiohttp>=3.11.12"

cd /path/to/azents/python/apps/{project-name}
uv lock
```

같은 패키지를 여러 프로젝트에서 사용하는 경우, 모든 프로젝트의 pyproject.toml을 함께 업데이트한다.

#### Case B: Transitive dependency (pyproject.toml에 없는 경우)

`lowest-direct` resolution은 transitive dependency에 영향을 주지 않는다. transitive는 일반적으로 최신 호환 버전으로 resolve된다. lockfile만 업데이트하면 된다:

```bash
cd /path/to/azents/python/apps/{project-name}
uv lock --upgrade-package {package-name}
```

lockfile에서 버전이 업데이트되었는지 확인:

```bash
grep -A2 'name = "{package-name}"' uv.lock
```

`--upgrade-package`를 했는데도 업데이트가 안 되는 경우, `lowest-direct` 때문이 아니라 다른 이유가 있다:

1. **lockfile preference**: uv는 기존 lockfile의 버전을 preference로 유지한다. 명시적 버전 제약을 추가하면 해결된다:
   ```bash
   uv lock --upgrade-package '{package-name}>={target-version}'
   ```
2. **상위 의존성의 버전 제한**: 다른 패키지가 `{package-name}<X.Y` 같은 상한을 설정한 경우
3. **호환성 충돌**: 여러 패키지가 요구하는 버전 범위가 교차하지 않는 경우

#### Case C: 다른 의존성에 의해 업데이트가 막힌 경우

상위 의존성이 오래된 버전을 고정하고 있으면 `uv lock --upgrade-package`로는 해결되지 않는다.

1. 어떤 패키지가 해당 의존성을 요구하는지 파악:

```bash
# uv.lock에서 해당 패키지를 dependencies로 가진 항목 찾기
grep -B10 '{package-name}' uv.lock
```

2. 상위 의존성을 먼저 업데이트 (Case A 또는 B 적용)

3. 그래도 해결되지 않으면 포기하고 이유를 명확히 설명한다:
   - 어떤 상위 패키지가 버전을 제한하는지
   - 해당 패키지의 최신 버전에서도 제한이 풀리지 않는지
   - 사용자가 직접 판단할 수 있도록 대안 제시 (예: 상위 패키지 교체, issue 등록)

### 3단계: 검증

```bash
# lockfile에서 목표 버전 확인
grep -A2 'name = "{package-name}"' uv.lock

# 타입 체크 확인
cd /path/to/azents/python/apps/{project-name}
uv run pyright
```

## Dependabot 보안 알림 일괄 처리

여러 알림을 한 번에 처리할 때의 워크플로우:

```bash
# 열린 알림 조회
gh api repos/{owner}/{repo}/dependabot/alerts \
  --jq '.[] | select(.state=="open") | {
    number,
    severity: .security_advisory.severity,
    package: .security_vulnerability.package.name,
    patched: .security_vulnerability.first_patched_version.identifier
  }'
```

같은 패키지의 알림은 하나로 묶어 처리한다. 패치 버전 중 가장 높은 것을 목표로 설정한다.

Python 패키지는 여러 서브프로젝트에서 동시에 사용될 수 있으므로, 모든 프로젝트의 lockfile을 확인한다.

## 주의사항

- `[tool.uv.override]`는 사용하지 않는다 — 의존성 관계와 무관한 강제 버전이 들어가 추적이 어려워진다
- lockfile(`uv.lock`)은 직접 편집하지 않는다 — 항상 uv 명령으로 갱신
- 저장소 루트에서 `uv` 명령 실행 금지 — 반드시 서브프로젝트 디렉토리에서 실행
- 업데이트 후 불필요한 파일이 변경되지 않았는지 `git diff --stat`으로 확인
- major 버전 업그레이드는 breaking change 가능성이 있으므로 사용자에게 알린다
