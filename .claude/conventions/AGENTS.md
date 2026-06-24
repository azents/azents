# Conventions Area

이 디렉터리는 convention body를 관리합니다.

## Index Generation

- `.claude/conventions/**` 아래 body 파일을 추가하거나 수정할 수 있습니다.
- `.claude/rules/*-conventions.md` index 파일은 pre-commit hook이 생성합니다.
- Index 생성을 위해 `python scripts/generate-conventions-index.py`를 수동 실행하지 않습니다.
- `python-frontmatter`를 루트나 임의 Python 환경에 설치해서 generator를 직접 돌리지 않습니다. 이 의존성은 pre-commit hook의 isolated environment가 소유합니다.
- Convention body를 작성한 뒤 커밋하면 pre-commit이 index를 갱신합니다. 갱신된 index diff는 pre-commit 결과로 받아들입니다.
