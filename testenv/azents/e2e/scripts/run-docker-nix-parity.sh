#!/usr/bin/env bash
set -euo pipefail

RUNNER_IMAGE="${AZENTS_NIX_PARITY_RUNNER_IMAGE:?AZENTS_NIX_PARITY_RUNNER_IMAGE is required}"
ROOT_DIR="$(mktemp -d)"
CONTAINER_PREFIX="azents-nix-parity-${RANDOM}-$$"
CURRENT_CONTAINER=""

cleanup() {
  local status=$?
  trap - EXIT
  set +e
  if [[ -n "${CURRENT_CONTAINER}" ]]; then
    docker rm -f "${CURRENT_CONTAINER}" >/dev/null 2>&1 || true
  fi
  docker run --rm --user root \
    -v "${ROOT_DIR}:/runtime-data:rw" \
    "${RUNNER_IMAGE}" \
    /bin/sh -ec 'find /runtime-data -mindepth 1 -delete' \
    >/dev/null 2>&1 || true
  rmdir "${ROOT_DIR}" >/dev/null 2>&1 || true
  exit "${status}"
}
trap cleanup EXIT

mkdir -p "${ROOT_DIR}/workspace" "${ROOT_DIR}/nix"
chmod 0777 "${ROOT_DIR}/workspace" "${ROOT_DIR}/nix"

runner_args=(
  --detach
  --user 1000:1000
  --workdir /workspace/agent
  --volume "${ROOT_DIR}/workspace:/workspace/agent:rw"
  --volume "${ROOT_DIR}/nix:/nix:rw"
  --env AZ_RUNTIME_CONTROL_ENDPOINT=127.0.0.1:9
  --env AZ_RUNTIME_TRANSFER_ENDPOINT=127.0.0.1:9
  --env AZ_RUNTIME_CONTROL_ALLOW_INSECURE=true
  --env AZ_RUNTIME_ID=11111111111111111111111111111111
  --env AZ_AGENT_ID=22222222222222222222222222222222
  --env AZ_WORKSPACE_ID=33333333333333333333333333333333
  --env AZ_RUNTIME_PROVIDER_ID=nix-phase3-docker
  --env AZ_RUNTIME_PROVIDER_GENERATION=1
  --env AZ_RUNTIME_DESIRED_GENERATION=1
  --env AZ_RUNTIME_RUNNER_AUTH_TOKEN=nix-phase3-token
  --env AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID=nix-phase3-credential
  --env AZ_RUNTIME_CONFIGURATION_SEQUENCE=1
  --env AZ_RUNTIME_CONFIGURATION_DIGEST=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  --env AZ_RUNTIME_CONFIGURATION_DESIRED_GENERATION=1
  --env HOME=/workspace/agent
)
nix_env=(
  --env NIX_STORE_DIR=/nix/store
  --env NIX_STATE_DIR=/nix/var/nix
  --env NIX_LOG_DIR=/nix/var/log/nix
  --env NIX_CONF_DIR=/nix/etc/nix
  --env NIX_CACHE_HOME=/nix/var/cache/azents-agent
  --env NIX_CONFIG_HOME=/nix/var/config/azents-agent
  --env NIX_PROFILE=/nix/var/state/azents-agent/profiles/profile
  --env NIX_SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
  --env NIX_STATE_HOME=/nix/var/state/azents-agent
  --env PATH=/nix/var/state/azents-agent/profiles/profile/bin:/nix/var/nix/profiles/azents-release/bin:/usr/local/bin:/usr/bin:/bin
)

start_runner() {
  local suffix="$1"
  local network_mode="$2"
  CURRENT_CONTAINER="${CONTAINER_PREFIX}-${suffix}"
  local extra_args=()
  if [[ "${network_mode}" == "none" ]]; then
    extra_args+=(--network none)
  fi
  docker run --name "${CURRENT_CONTAINER}" \
    "${runner_args[@]}" \
    "${extra_args[@]}" \
    "${RUNNER_IMAGE}" >/dev/null
  for _ in $(seq 1 120); do
    if docker logs "${CURRENT_CONTAINER}" 2>&1 |
      grep -Eq 'Runtime Runner initialized Nix store|Runtime Runner Nix seed already applied'; then
      return
    fi
    if [[ "$(docker inspect "${CURRENT_CONTAINER}" --format '{{.State.Running}}')" != "true" ]]; then
      docker logs "${CURRENT_CONTAINER}" >&2
      return 1
    fi
    sleep 1
  done
  docker logs "${CURRENT_CONTAINER}" >&2
  return 1
}

remove_runner() {
  docker rm -f "${CURRENT_CONTAINER}" >/dev/null
  CURRENT_CONTAINER=""
}

nix_exec() {
  docker exec "${nix_env[@]}" "${CURRENT_CONTAINER}" "$@"
}

start_runner initial bridge
nix_exec \
  nix profile add \
  --option connect-timeout 10 \
  --option stalled-download-timeout 10 \
  --option download-attempts 2 \
  nixpkgs#hello
nix_exec /bin/sh -ec 'hello'
remove_runner

start_runner replacement none
nix_exec /bin/sh -ec 'hello'
nix_exec \
  nix search --offline nixpkgs '^hello$' >/dev/null 2>&1
remove_runner

docker run --rm --user root \
  -v "${ROOT_DIR}/nix:/nix:rw" \
  "${RUNNER_IMAGE}" \
  /bin/sh -ec 'find /nix -mindepth 1 -delete'

start_runner reset none
if nix_exec /bin/sh -ec 'command -v hello'; then
  echo 'hello remained available after explicit Docker parity reset' >&2
  exit 1
fi
nix_exec \
  nix search --offline nixpkgs '^hello$' >/dev/null 2>&1
remove_runner

printf '%s\n' '{"docker_parity":"passed","package":"hello"}'
