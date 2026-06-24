#!/usr/bin/env bash

# devserver 포그라운드 실행 진입점.
#
# 이 스크립트는 IDE 디버거 attach나 실시간 로그 관찰용으로 유지된다.
# 에이전트/자동화용으로 백그라운드 기동·종료·상태 확인이 필요하면
# testenv wrapper를 사용하자 (cwd: testenv/azents):
#
#   cd testenv/azents
#   uv run devserver.py up
#   uv run devserver.py status
#   uv run devserver.py down
#
# 양쪽 모두 최종적으로 src/cli/devserver.py를 호출한다.

set -e

cd "$(dirname $0)/.."

alembic_cfg="db-schemas/rdb/alembic.ini"
revision_file="db-schemas/rdb/revision"

if [ -f "${revision_file}" ]; then
    if [ "$(cat "${revision_file}")" != "$(alembic -c "${alembic_cfg}" current 2> /dev/null | awk '{print $1}')" ]; then
        echo "Database schema does not match. Upgrading..."
        cat "${revision_file}" | xargs alembic -c "${alembic_cfg}" upgrade
    fi
fi

# shellcheck disable=SC2068
python src/cli/devserver.py $@
