---
name: python-dependency-management
description: Python 프로젝트에 의존성을 추가하는 방법을 안내합니다. uv 패키지 매니저를 사용하며, 프로젝트 타입(apps/libs)에 따라 버전 지정 방식이 다릅니다.
---

# Python Dependency Management

Python 프로젝트에 의존성을 올바르게 추가하는 방법을 안내합니다.

## 프로젝트 타입 확인

먼저 작업 중인 프로젝트가 어떤 타입인지 확인하세요:
- `python/apps/*`: 애플리케이션 프로젝트
- `python/libs/*`: 라이브러리 프로젝트

## 버전 지정 규칙

모든 프로젝트는 `lowest-direct` resolution 전략을 사용합니다.
지정된 버전은 **최소** 버전이므로, 항상 **최신 사용 가능한 버전**을 지정하세요.

### 애플리케이션 프로젝트 (`python/apps/*`)

| 의존성 타입 | 버전 지정자 | 예시 |
|------------|-----------|------|
| 일반 의존성 | 정확한 버전 (`==`) | `"fastapi==0.127.0"` |
| dev 의존성 | 최소 버전 (`>=`) | `"pytest>=9.0.1"` |

**이유**:
- 일반 의존성은 재현 가능한 빌드와 예측 가능한 배포를 위해 정확한 버전 사용
- dev 의존성은 프로덕션 빌드에 영향을 주지 않으므로 최소 버전 사용

### 라이브러리 프로젝트 (`python/libs/*`)

| 의존성 타입 | 버전 지정자 | 예시 |
|------------|-----------|------|
| 모든 의존성 | 최소 버전 (`>=`) | `"pydantic>=2.12"` |

**이유**:
- 라이브러리를 사용하는 앱이 호환 가능한 버전을 선택할 수 있도록 유연성 제공

## 의존성 추가 절차

### 1. pyproject.toml 파일 확인

**중요**: 의존성을 추가하기 전에 기존 `pyproject.toml` 파일을 읽어서:
- 의존성이 섹션별로 주석으로 구분되어 있는지 확인
- 예: `# Local dependencies`, `# External dependencies` 등
- 기존 그룹핑 패턴을 따라 새 의존성을 적절한 위치에 추가

### 2. 프로젝트 디렉토리로 이동

**중요**: `uv` 명령은 반드시 서브프로젝트 디렉토리에서 실행해야 합니다.

```bash
cd /path/to/azents/python/apps/{project-name}
# 또는
cd /path/to/azents/python/libs/{project-name}
```

### 3. 기존 버전 확인

**중요**: 같은 의존성을 다른 프로젝트에서 이미 사용하고 있는지 확인:
- Glob 도구로 다른 프로젝트의 pyproject.toml 파일 검색
- Grep 도구로 해당 패키지명 검색
- 이미 사용 중이면 **동일한 버전**을 사용해야 함 (monorepo 일관성 유지)

### 4. 최신 버전 확인 (새 의존성인 경우)

PyPI에서 패키지의 최신 버전을 확인하세요:
- WebSearch 사용: `"{package-name} pypi latest version 2026"`
- 또는 `uv pip index versions {package-name}` 실행

### 5. 의존성 추가

프로젝트 타입에 맞는 버전 지정자를 사용하세요:

**애플리케이션 - 일반 의존성:**
```bash
uv add "{package-name}=={latest-version}"
```

**애플리케이션 - dev 의존성:**
```bash
uv add --dev "{package-name}>={latest-version}"
```

**라이브러리 - 모든 의존성:**
```bash
uv add "{package-name}>={latest-version}"
```

### 6. pyproject.toml 정리

의존성 추가 후 `pyproject.toml` 파일을 확인하고:
- 새로 추가된 의존성이 적절한 섹션(주석 그룹)에 있는지 확인
- 필요시 수동으로 위치 조정 (예: local dependency 섹션으로 이동)

### 7. 검증

의존성이 올바르게 추가되었는지 확인:
```bash
uv pip list | grep {package-name}
```

## 예시

### pyproject.toml 구조 확인

```toml
[project]
dependencies = [
    # Local dependencies
    "az-common",

    # External dependencies
    "fastapi==0.127.0",
    "pydantic==2.12.4",
]
```

### 애플리케이션에 fastapi 추가

```bash
cd /path/to/azents/python/apps/azents
uv add "fastapi==0.127.0"
```

### 애플리케이션에 pytest (dev) 추가

```bash
cd /path/to/azents/python/apps/azents
uv add --dev "pytest>=9.0.1"
```

### 라이브러리에 pydantic 추가

```bash
cd /path/to/azents/python/libs/az-common
uv add "pydantic>=2.12"
```

## 주의사항

- ❌ 저장소 루트에서 `uv run` 실행 금지
- ✅ 항상 절대 경로로 서브프로젝트 디렉토리로 이동
- ✅ 상대 경로 사용 지양
- ✅ 최신 버전 확인 후 추가
- ✅ 프로젝트 타입에 맞는 버전 지정자 사용
- ✅ pyproject.toml의 주석 섹션 구분 유지
