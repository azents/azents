#!/usr/bin/env bash

# Entry point for running devserver in the foreground.
#
# Keep this script for attaching an IDE debugger or observing live logs.
# For agent or automation workflows that need background startup, shutdown, or status checks,
# use the testenv wrapper (cwd: testenv/azents):
#
#   cd testenv/azents
#   uv run devserver.py up
#   uv run devserver.py status
#   uv run devserver.py down
#
# Both paths ultimately invoke src/cli/devserver.py.

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
