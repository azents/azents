#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

alembic_cfg="db-schemas/rdb/alembic.ini"
revision_file="db-schemas/rdb/revision"

if [ -f "${revision_file}" ]; then
    if [ "$(cat "${revision_file}")" != "$(alembic -c "${alembic_cfg}" current 2> /dev/null | awk '{print $1}')" ]; then
        echo "Database schema does not match. Upgrading..."
        xargs alembic -c "${alembic_cfg}" upgrade < "${revision_file}"
    fi
fi

exec python src/cli/runtime_control_server.py "$@"
