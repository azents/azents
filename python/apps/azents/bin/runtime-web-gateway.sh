#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

exec python -c \
  'import asyncio; from azents.runtime_web_gateway.server import run_runtime_web_gateway; asyncio.run(run_runtime_web_gateway())'
