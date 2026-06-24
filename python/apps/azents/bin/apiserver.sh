#!/usr/bin/env bash

set -e

cd "$(dirname $0)/.."

port=${AZ_PORT:-8010}
ws=${AZ_WS:-websockets-sansio}
ws_ping_interval=${AZ_WS_PING_INTERVAL:-30}
ws_ping_timeout=${AZ_WS_PING_TIMEOUT:-60}
alembic_cfg="db-schemas/rdb/alembic.ini"
revision_file="db-schemas/rdb/revision"

if [ -f "${revision_file}" ]; then
    if [ "$(cat "${revision_file}")" != "$(alembic -c "${alembic_cfg}" current 2> /dev/null | awk '{print $1}')" ]; then
        echo "Database schema does not match. Upgrading..."
        cat "${revision_file}" | xargs alembic -c "${alembic_cfg}" upgrade
    fi
fi

exec uvicorn apiserver:app \
    --host 0.0.0.0 \
    --port "${port}" \
    --ws "${ws}" \
    --ws-ping-interval "${ws_ping_interval}" \
    --ws-ping-timeout "${ws_ping_timeout}" \
    "$@"
