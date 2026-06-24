#!/bin/sh
# git credential helper — responds to the git credential protocol using
# GitHub tokens provided by GitHubToolkit.expose_env().
#
# A single installation uses GH_TOKEN/GITHUB_TOKEN. Multi-installation
# credentials select the owner-specific token from GITHUB_INSTALLATION_MAP and
# GITHUB_TOKEN_INSTALLATION_<id>.

case "$1" in
    get)
        ;;
    *)
        exit 0
        ;;
esac

protocol=""
host=""
path=""
while IFS='=' read -r key value; do
    case "$key" in
        protocol) protocol="$value" ;;
        host) host="$value" ;;
        path) path="$value" ;;
    esac
done

if [ "$host" != "github.com" ]; then
    exit 0
fi

owner="${path%%/*}"
owner_lc=$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]')
token=""

if [ -n "${GITHUB_INSTALLATION_MAP:-}" ] && [ -n "$owner_lc" ] && command -v python3 >/dev/null 2>&1; then
    token=$(python3 - "$owner_lc" <<'PY'
import json
import os
import sys

owner = sys.argv[1]
try:
    mapping = json.loads(os.environ.get("GITHUB_INSTALLATION_MAP", "{}"))
except json.JSONDecodeError:
    mapping = {}
entry = mapping.get(owner)
if isinstance(entry, dict):
    env_name = entry.get("env")
    if isinstance(env_name, str):
        print(os.environ.get(env_name, ""))
PY
)
fi

if [ -z "$token" ]; then
    token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
fi

if [ -z "$token" ]; then
    exit 0
fi

echo "protocol=${protocol:-https}"
echo "host=github.com"
echo "username=x-access-token"
echo "password=$token"
