#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
RUN_SUFFIX="${AZENTS_KUBERNETES_NIX_RUN_ID:-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$$}"
RUN_SUFFIX="$(
  printf '%s' "${RUN_SUFFIX}" |
    tr -cd '[:alnum:]-' |
    tr '[:upper:]' '[:lower:]' |
    sed -E 's/^-+//; s/-+$//' |
    cut -c1-30
)"
test -n "${RUN_SUFFIX}"
CLUSTER_NAME="azents-nix-${RUN_SUFFIX}"
NAMESPACE="nix-phase3"
REGISTRY_NAME="${CLUSTER_NAME}-registry"
REGISTRY_HOST="127.0.0.1"
REGISTRY_IMAGE="registry:2.8.3@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"
KIND_NODE_IMAGE="kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5"
CALICO_URL="https://raw.githubusercontent.com/projectcalico/calico/v3.30.3/manifests/calico.yaml"
CALICO_SHA256="9382d2b27a76f40c170454b408653e6d71e2205ef0aef069e942bb690e7381d0"
TMP_DIR="$(mktemp -d)"
export KUBECONFIG="${TMP_DIR}/kubeconfig"
RUNTIME_ID="nix-phase3"
RUNTIME_POD="azents-runtime-${RUNTIME_ID}"
WORKSPACE_PVC="${RUNTIME_POD}-workspace"
NIX_PVC="${RUNTIME_POD}-nix"
CLUSTER_CREATED=false
REGISTRY_CREATED=false
RUNNER_AUTH_TOKEN="$(
  printf '%s' "${CLUSTER_NAME}-runner-token" | sha256sum | cut -d' ' -f1
)"
RUNNER_AUTH_CREDENTIAL_ID="$(
  printf '%s' "${CLUSTER_NAME}-runner-credential" | sha256sum | cut -d' ' -f1
)"

redact_evidence() {
  PHASE3_REDACTION_VALUES="${RUNNER_AUTH_TOKEN}"$'\n'"${RUNNER_AUTH_CREDENTIAL_ID}" \
    python3 - "${TMP_DIR}/evidence" <<'PY'
import os
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
exact_values = tuple(
    value
    for value in os.environ.get("PHASE3_REDACTION_VALUES", "").splitlines()
    if value
)
patterns = (
    re.compile(
        r"(?i)(authorization\s*:\s*bearer\s+)"
        r"[a-z0-9._~+/=-]+"
    ),
    re.compile(
        r"(?i)(AZ_RUNTIME_RUNNER_AUTH_(?:TOKEN|CREDENTIAL_ID)"
        r"\s*[:=]\s*)[^\s,}\"']+"
    ),
    re.compile(
        r"""(?ix)
        (
          ["']?
          (?:runner_auth_token|runner_auth_credential_id|access_token|api_key|
             client_secret|password|secret|token)
          ["']?
          \s*[:=]\s*
          ["']?
        )
        [^"',\s}]+
        """
    ),
)

for path in root.rglob("*"):
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    for value in exact_values:
        text = text.replace(value, "<redacted>")
    for pattern in patterns:
        text = pattern.sub(r"\1<redacted>", text)
    path.write_text(text, encoding="utf-8")
PY
}

cleanup() {
  local status=$?
  local redaction_succeeded=false
  trap - EXIT
  set +e
  mkdir -p "${TMP_DIR}/evidence"
  kubectl get pods,pv,pvc,storageclass,networkpolicy,job -A -o wide \
    >"${TMP_DIR}/evidence/resources.txt" 2>&1
  kubectl describe pods -n "${NAMESPACE}" \
    >"${TMP_DIR}/evidence/pod-descriptions.txt" 2>&1
  for pod in $(kubectl get pods -n "${NAMESPACE}" -o name 2>/dev/null); do
    kubectl logs -n "${NAMESPACE}" "${pod}" --all-containers \
      >"${TMP_DIR}/evidence/$(basename "${pod}").log" 2>&1 || true
  done
  if [[ "${status}" -eq 0 ]]; then
    cat >"${TMP_DIR}/evidence/junit.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="kubernetes-nix" tests="2" failures="0">
  <testcase classname="runtime.nix" name="kubernetes_persistent_nix_lifecycle"/>
  <testcase classname="runtime.nix" name="docker_persistent_nix_parity"/>
</testsuite>
EOF
  else
    cat >"${TMP_DIR}/evidence/junit.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="kubernetes-nix" tests="2" failures="1">
  <testcase classname="runtime.nix" name="kubernetes_persistent_nix_lifecycle">
    <failure message="Disposable Kubernetes Nix conformance failed"/>
  </testcase>
  <testcase classname="runtime.nix" name="docker_persistent_nix_parity"/>
</testsuite>
EOF
  fi
  if redact_evidence; then
    redaction_succeeded=true
  else
    status=1
    printf '%s\n' \
      'Kubernetes Nix evidence sanitization failed; raw evidence was not published.' \
      >&2
  fi
  if [[ -n "${AZENTS_E2E_ARTIFACT_DIR:-}" ]]; then
    if ! mkdir -p "${AZENTS_E2E_ARTIFACT_DIR}"; then
      status=1
    elif [[ "${redaction_succeeded}" == true ]]; then
      if ! cp -R "${TMP_DIR}/evidence/." "${AZENTS_E2E_ARTIFACT_DIR}/"; then
        status=1
      fi
    else
      cat >"${AZENTS_E2E_ARTIFACT_DIR}/sanitization-failure.txt" <<'EOF'
Kubernetes Nix evidence sanitization failed.
Raw cluster resources and logs were not published.
EOF
    fi
  fi
  if [[ "${CLUSTER_CREATED}" == true ]]; then
    kind delete cluster \
      --name "${CLUSTER_NAME}" \
      --kubeconfig "${KUBECONFIG}" >/dev/null 2>&1 || true
  fi
  if [[ "${REGISTRY_CREATED}" == true ]]; then
    docker rm -f "${REGISTRY_NAME}" >/dev/null 2>&1 || true
  fi
  rm -rf "${TMP_DIR}"
  exit "${status}"
}
trap cleanup EXIT

for command in docker kind kubectl jq curl sha256sum python3; do
  command -v "${command}" >/dev/null
done

mkdir -p "${TMP_DIR}/evidence"

LOCAL_RUNNER_TAG="azents-runtime-runner:phase3-${RUN_SUFFIX}"
LOCAL_PROVIDER_TAG="azents-runtime-provider-kubernetes:phase3-${RUN_SUFFIX}"
docker build \
  -f python/apps/azents-runtime-runner/Dockerfile \
  -t "${LOCAL_RUNNER_TAG}" \
  "${ROOT_DIR}"
docker build \
  -f python/apps/azents-runtime-provider-kubernetes/Dockerfile \
  -t "${LOCAL_PROVIDER_TAG}" \
  "${ROOT_DIR}"

AZENTS_NIX_PARITY_RUNNER_IMAGE="${LOCAL_RUNNER_TAG}" \
  "${ROOT_DIR}/testenv/azents/e2e/scripts/run-docker-nix-parity.sh" |
  tee "${TMP_DIR}/evidence/docker-parity.json"

docker run -d --restart=always \
  -p "127.0.0.1::5000" \
  --name "${REGISTRY_NAME}" \
  "${REGISTRY_IMAGE}" >/dev/null
REGISTRY_CREATED=true
REGISTRY_PORT="$(
  docker inspect \
    --format '{{(index (index .NetworkSettings.Ports "5000/tcp") 0).HostPort}}' \
    "${REGISTRY_NAME}"
)"
test -n "${REGISTRY_PORT}"
for _ in $(seq 1 30); do
  if curl -fsS "http://${REGISTRY_HOST}:${REGISTRY_PORT}/v2/" >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS "http://${REGISTRY_HOST}:${REGISTRY_PORT}/v2/" >/dev/null

RUNNER_TAG="${REGISTRY_HOST}:${REGISTRY_PORT}/azents-runtime-runner:phase3"
PROVIDER_TAG="${REGISTRY_HOST}:${REGISTRY_PORT}/azents-runtime-provider-kubernetes:phase3"
docker tag "${LOCAL_RUNNER_TAG}" "${RUNNER_TAG}"
docker tag "${LOCAL_PROVIDER_TAG}" "${PROVIDER_TAG}"
docker push "${RUNNER_TAG}"
docker push "${PROVIDER_TAG}"

RUNNER_IMAGE="$(
  docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' \
    "${RUNNER_TAG}" |
    grep "^${REGISTRY_HOST}:${REGISTRY_PORT}/azents-runtime-runner@sha256:" |
    head -1
)"
PROVIDER_IMAGE="$(
  docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' \
    "${PROVIDER_TAG}" |
    grep "^${REGISTRY_HOST}:${REGISTRY_PORT}/azents-runtime-provider-kubernetes@sha256:" |
    head -1
)"
test -n "${RUNNER_IMAGE}"
test -n "${PROVIDER_IMAGE}"
printf '%s\n' "${RUNNER_IMAGE}" >"${TMP_DIR}/evidence/runner-image.txt"
printf '%s\n' "${PROVIDER_IMAGE}" >"${TMP_DIR}/evidence/provider-image.txt"

cat >"${TMP_DIR}/kind.yaml" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
  podSubnet: 192.168.0.0/16
nodes:
  - role: control-plane
EOF

kind create cluster \
  --name "${CLUSTER_NAME}" \
  --image "${KIND_NODE_IMAGE}" \
  --config "${TMP_DIR}/kind.yaml" \
  --kubeconfig "${KUBECONFIG}"
CLUSTER_CREATED=true
docker network connect kind "${REGISTRY_NAME}" 2>/dev/null || true
NODE="$(kind get nodes --name "${CLUSTER_NAME}" | head -1)"
REGISTRY_DIR="/etc/containerd/certs.d/${REGISTRY_HOST}:${REGISTRY_PORT}"
docker exec "${NODE}" mkdir -p "${REGISTRY_DIR}"
cat <<EOF | docker exec -i "${NODE}" sh -c "cat > '${REGISTRY_DIR}/hosts.toml'"
[host."http://${REGISTRY_NAME}:5000"]
EOF

curl -fsSL "${CALICO_URL}" -o "${TMP_DIR}/calico.yaml"
printf '%s  %s\n' "${CALICO_SHA256}" "${TMP_DIR}/calico.yaml" | sha256sum --check
kubectl apply -f "${TMP_DIR}/calico.yaml"
kubectl wait --for=condition=Available deployment/calico-kube-controllers \
  -n kube-system --timeout=300s
kubectl wait --for=condition=Ready pods --all -n kube-system --timeout=300s

kubectl rollout status deployment/local-path-provisioner \
  -n local-path-storage --timeout=180s
kubectl get storageclass standard -o json |
  jq -e '
    .provisioner == "rancher.io/local-path"
    and .volumeBindingMode == "WaitForFirstConsumer"
    and .reclaimPolicy == "Delete"
  ' >/dev/null

kubectl create namespace "${NAMESPACE}"
kubectl create configmap phase3-provider-driver -n "${NAMESPACE}" \
  --from-file=driver.py="${ROOT_DIR}/python/apps/azents-runtime-provider-kubernetes/tests/kubernetes_nix_conformance_driver.py"

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: phase3-provider
  namespace: ${NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: phase3-provider
  namespace: ${NAMESPACE}
rules:
  - apiGroups: [""]
    resources: ["pods", "persistentvolumeclaims", "services", "configmaps", "secrets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: phase3-provider
  namespace: ${NAMESPACE}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: phase3-provider
subjects:
  - kind: ServiceAccount
    name: phase3-provider
    namespace: ${NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: phase3-provider-cluster
rules:
  - apiGroups: [""]
    resources: ["namespaces"]
    resourceNames: ["${NAMESPACE}"]
    verbs: ["get"]
  - apiGroups: ["authorization.k8s.io"]
    resources: ["selfsubjectaccessreviews"]
    verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: phase3-provider-cluster
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: phase3-provider-cluster
subjects:
  - kind: ServiceAccount
    name: phase3-provider
    namespace: ${NAMESPACE}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: runtime-control
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: runtime-control
  template:
    metadata:
      labels:
        app: runtime-control
    spec:
      containers:
        - name: echo
          image: ${RUNNER_IMAGE}
          command: ["/usr/local/bin/python", "-m", "http.server", "8030"]
          ports:
            - containerPort: 8030
---
apiVersion: v1
kind: Service
metadata:
  name: runtime-control
  namespace: ${NAMESPACE}
spec:
  selector:
    app: runtime-control
  ports:
    - port: 8030
      targetPort: 8030
EOF
kubectl rollout status deployment/runtime-control -n "${NAMESPACE}" --timeout=180s

provider_job_manifest() {
  local job_name="$1"
  local action="$2"
  cat <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
  namespace: ${NAMESPACE}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: phase3-provider
      containers:
        - name: provider
          image: ${PROVIDER_IMAGE}
          command:
            - /workspace/python/apps/azents-runtime-provider-kubernetes/.venv/bin/python
            - /conformance/driver.py
          env:
            - name: PHASE3_RUNNER_IMAGE
              value: ${RUNNER_IMAGE}
            - name: PHASE3_ACTION
              value: ${action}
            - name: PHASE3_RUNNER_AUTH_TOKEN
              value: ${RUNNER_AUTH_TOKEN}
            - name: PHASE3_RUNNER_AUTH_CREDENTIAL_ID
              value: ${RUNNER_AUTH_CREDENTIAL_ID}
            - name: AZ_RUNTIME_CONTROL_ENDPOINT
              value: runtime-control:8030
            - name: AZ_RUNTIME_CONTROL_ALLOW_INSECURE
              value: "true"
            - name: AZ_RUNTIME_PROVIDER_READINESS_FILE
              value: /tmp/phase3-provider-ready
            - name: AZ_RUNTIME_PROVIDER_SERVICE_ACCOUNT_TOKEN_FILE
              value: /var/run/secrets/kubernetes.io/serviceaccount/token
            - name: AZ_RUNTIME_PROVIDER_ID
              value: nix-phase3-kubernetes
            - name: AZ_RUNTIME_PROVIDER_LEASE_NAMESPACE
              value: ${NAMESPACE}
            - name: AZ_RUNTIME_PROVIDER_WORKLOAD_NAMESPACE
              value: ${NAMESPACE}
            - name: AZ_RUNTIME_PROVIDER_DEFAULT_DENY_LABELS
              value: '{"azents/network-policy-role":"runtime-execution-default-deny"}'
            - name: AZ_RUNTIME_PROVIDER_LEASE_NAME
              value: phase3-provider
            - name: AZ_RUNTIME_PROVIDER_LEASE_DURATION_SECONDS
              value: "15"
            - name: AZ_RUNTIME_PROVIDER_WORKSPACE_PATH
              value: /workspace/agent
            - name: AZ_RUNTIME_PROVIDER_NIX_STORE_STORAGE_CLASS
              value: standard
            - name: AZ_RUNTIME_PROVIDER_NIX_STORE_SIZE
              value: 4Gi
            - name: AZ_RUNTIME_PROVIDER_ENGINE_IMAGE
              value: ${RUNNER_IMAGE}
            - name: AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_NAMESPACE
              value: ${NAMESPACE}
            - name: AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_LABELS
              value: '{"app":"runtime-control"}'
            - name: AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_PORT
              value: "8030"
            - name: AZ_RUNTIME_PROVIDER_ATTEST_PROXY_REQUIRED
              value: "false"
            - name: AZ_RUNTIME_PROVIDER_ATTEST_NO_NETWORK
              value: "true"
            - name: AZ_RUNTIME_PROVIDER_MANDATORY_SERVICES
              value: '[{"role":"runtime_control","namespace":"${NAMESPACE}","name":"runtime-control","endpoint_hostnames":["runtime-control","runtime-control.${NAMESPACE}","runtime-control.${NAMESPACE}.svc","runtime-control.${NAMESPACE}.svc.cluster.local"],"ports":[8030]},{"role":"runtime_transfer","namespace":"${NAMESPACE}","name":"runtime-control","endpoint_hostnames":["runtime-control","runtime-control.${NAMESPACE}","runtime-control.${NAMESPACE}.svc","runtime-control.${NAMESPACE}.svc.cluster.local"],"ports":[8030]}]'
            - name: AZ_RUNTIME_PROVIDER_PROXY_PORT
              value: "8080"
            - name: AZ_RUNTIME_PROVIDER_PROXY_READINESS_PORT
              value: "8081"
            - name: AZ_RUNTIME_PROVIDER_DIAGNOSTIC_REFRESH_INTERVAL_SECONDS
              value: "30"
            - name: AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_ALLOWED_CIDRS
              value: '[]'
            - name: AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_DENIED_CIDRS
              value: '[]'
            - name: AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_EXTRA_EGRESS
              value: '[]'
            - name: AZ_RUNTIME_PROVIDER_POD_IMAGE_PULL_SECRETS
              value: '[]'
            - name: AZ_RUNTIME_PROVIDER_POD_ANNOTATIONS
              value: '{}'
          volumeMounts:
            - name: driver
              mountPath: /conformance
              readOnly: true
      volumes:
        - name: driver
          configMap:
            name: phase3-provider-driver
EOF
}

run_provider() {
  local job_name="$1"
  local action="$2"
  provider_job_manifest "${job_name}" "${action}" | kubectl apply -f -
  kubectl wait -n "${NAMESPACE}" --for=condition=complete \
    "job/${job_name}" --timeout=300s
  kubectl logs -n "${NAMESPACE}" "job/${job_name}" |
    tee "${TMP_DIR}/evidence/${job_name}.json"
}

wait_for_runner() {
  kubectl wait -n "${NAMESPACE}" --for=condition=Ready \
    "pod/${RUNTIME_POD}" --timeout=300s
  for _ in $(seq 1 180); do
    if kubectl logs -n "${NAMESPACE}" "${RUNTIME_POD}" -c runner 2>&1 |
      grep -Eq 'Runtime Runner initialized Nix store|Runtime Runner Nix seed already applied'; then
      return
    fi
    sleep 1
  done
  kubectl logs -n "${NAMESPACE}" "${RUNTIME_POD}" -c runner >&2
  return 1
}

nix_exec() {
  local command=(
    kubectl exec -n "${NAMESPACE}" "${RUNTIME_POD}" -c runner --
    /usr/bin/env
    NIX_STORE_DIR=/nix/store
    NIX_STATE_DIR=/nix/var/nix
    NIX_LOG_DIR=/nix/var/log/nix
    NIX_CONF_DIR=/nix/etc/nix
    NIX_CACHE_HOME=/nix/var/cache/azents-agent
    NIX_CONFIG_HOME=/nix/var/config/azents-agent
    NIX_PROFILE=/nix/var/state/azents-agent/profiles/profile
    NIX_SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
    NIX_STATE_HOME=/nix/var/state/azents-agent
    PATH=/nix/var/state/azents-agent/profiles/profile/bin:/nix/var/nix/profiles/azents-release/bin:/usr/local/bin:/usr/bin:/bin
  )
  if [[ -n "${NIX_EXEC_TIMEOUT_SECONDS:-}" ]]; then
    timeout "${NIX_EXEC_TIMEOUT_SECONDS}s" "${command[@]}" "$@"
    return
  fi
  "${command[@]}" "$@"
}

dynamic_pv_name() {
  local pvc="$1"
  local pv_name
  pv_name="$(
    kubectl get pvc -n "${NAMESPACE}" "${pvc}" -o jsonpath='{.spec.volumeName}'
  )"
  test -n "${pv_name}"
  kubectl get pvc -n "${NAMESPACE}" "${pvc}" -o json |
    jq -e '
      .spec.storageClassName == "standard"
      and .status.phase == "Bound"
    ' >/dev/null
  kubectl get pv "${pv_name}" -o json |
    jq -e --arg namespace "${NAMESPACE}" --arg pvc "${pvc}" '
      .spec.storageClassName == "standard"
      and .spec.claimRef.namespace == $namespace
      and .spec.claimRef.name == $pvc
      and .metadata.annotations["pv.kubernetes.io/provisioned-by"]
        == "rancher.io/local-path"
    ' >/dev/null
  printf '%s\n' "${pv_name}"
}

wait_for_pv_deletion() {
  local pv_name="$1"
  if kubectl get pv "${pv_name}" >/dev/null 2>&1; then
    kubectl wait --for=delete "pv/${pv_name}" --timeout=180s
  fi
}

run_provider phase3-start start
wait_for_runner

POD_JSON="$(kubectl get pod -n "${NAMESPACE}" "${RUNTIME_POD}" -o json)"
jq -e '
  ([.spec.volumes[] | select(.name == "agent-workspace") | .persistentVolumeClaim.claimName] == ["azents-runtime-nix-phase3-workspace"])
  and ([.spec.volumes[] | select(.name == "nix-store") | .persistentVolumeClaim.claimName] == ["azents-runtime-nix-phase3-nix"])
  and ([.spec.containers[] | select(.name == "runner") | .volumeMounts[] | select(.name == "agent-workspace") | .mountPath] == ["/workspace/agent"])
  and ([.spec.containers[] | select(.name == "runner") | .volumeMounts[] | select(.name == "nix-store") | .mountPath] == ["/nix"])
' <<<"${POD_JSON}" >/dev/null
kubectl get pvc -n "${NAMESPACE}" "${WORKSPACE_PVC}" -o json |
  jq -e '
    .metadata.labels["azents/resource-role"] == "workspace-pvc"
  ' >/dev/null
kubectl get pvc -n "${NAMESPACE}" "${NIX_PVC}" -o json |
  jq -e '
    .metadata.labels["azents/resource-role"] == "nix-store-pvc"
  ' >/dev/null
WORKSPACE_PV="$(dynamic_pv_name "${WORKSPACE_PVC}")"
NIX_PV="$(dynamic_pv_name "${NIX_PVC}")"

nix_exec \
  nix profile add \
  --option connect-timeout 10 \
  --option stalled-download-timeout 10 \
  --option download-attempts 2 \
  nixpkgs#hello
nix_exec /bin/sh -ec 'hello'
kubectl exec -n "${NAMESPACE}" "${RUNTIME_POD}" -c runner -- \
  /bin/sh -ec 'printf workspace > /workspace/agent/persistence-marker'

kubectl delete pod -n "${NAMESPACE}" "${RUNTIME_POD}" --wait=true
run_provider phase3-recreate recreate
wait_for_runner
nix_exec /bin/sh -ec 'hello'
kubectl exec -n "${NAMESPACE}" "${RUNTIME_POD}" -c runner -- \
  test -f /workspace/agent/persistence-marker

run_provider phase3-no-network-delete no_network_delete
kubectl wait -n "${NAMESPACE}" --for=delete \
  "pod/${RUNTIME_POD}" --timeout=180s
run_provider phase3-no-network-start no_network_start
wait_for_runner
nix_exec /bin/sh -ec 'hello'
if NIX_EXEC_TIMEOUT_SECONDS=90 nix_exec \
  nix profile add \
  --option connect-timeout 5 \
  --option stalled-download-timeout 5 \
  --option download-attempts 1 \
  nixpkgs#cowsay \
  >"${TMP_DIR}/evidence/no-network-install.txt" 2>&1; then
  echo 'uncached install unexpectedly succeeded under no_network' >&2
  exit 1
fi
nix_exec /bin/sh -ec 'hello'
kubectl get pod -n "${NAMESPACE}" "${RUNTIME_POD}" -o json |
  jq -e '.metadata.annotations["azents/runtime-network-mode"] == "no_network"' >/dev/null
kubectl get networkpolicy -n "${NAMESPACE}" "${RUNTIME_POD}-execution" >/dev/null

OLD_WORKSPACE_UID="$(kubectl get pvc -n "${NAMESPACE}" "${WORKSPACE_PVC}" -o jsonpath='{.metadata.uid}')"
OLD_NIX_UID="$(kubectl get pvc -n "${NAMESPACE}" "${NIX_PVC}" -o jsonpath='{.metadata.uid}')"
run_provider phase3-reset reset
workspace_uid="$(kubectl get pvc -n "${NAMESPACE}" "${WORKSPACE_PVC}" -o jsonpath='{.metadata.uid}')"
nix_uid="$(kubectl get pvc -n "${NAMESPACE}" "${NIX_PVC}" -o jsonpath='{.metadata.uid}')"
test "${workspace_uid}" != "${OLD_WORKSPACE_UID}"
test "${nix_uid}" != "${OLD_NIX_UID}"
wait_for_runner
RESET_WORKSPACE_PV="$(dynamic_pv_name "${WORKSPACE_PVC}")"
RESET_NIX_PV="$(dynamic_pv_name "${NIX_PVC}")"
test "${RESET_WORKSPACE_PV}" != "${WORKSPACE_PV}"
test "${RESET_NIX_PV}" != "${NIX_PV}"
wait_for_pv_deletion "${WORKSPACE_PV}"
wait_for_pv_deletion "${NIX_PV}"
if nix_exec /bin/sh -ec 'command -v hello'; then
  echo 'hello remained available after Kubernetes Runtime reset' >&2
  exit 1
fi
if kubectl exec -n "${NAMESPACE}" "${RUNTIME_POD}" -c runner -- \
  test -e /workspace/agent/persistence-marker; then
  echo 'Workspace marker remained available after Kubernetes Runtime reset' >&2
  exit 1
fi
nix_exec \
  nix search --offline nixpkgs '^hello$' >/dev/null 2>&1

run_provider phase3-delete delete
if kubectl get pod -n "${NAMESPACE}" "${RUNTIME_POD}" >/dev/null 2>&1; then
  echo 'Runtime Pod remained after terminal delete' >&2
  exit 1
fi
if kubectl get pvc -n "${NAMESPACE}" "${WORKSPACE_PVC}" >/dev/null 2>&1 \
  || kubectl get pvc -n "${NAMESPACE}" "${NIX_PVC}" >/dev/null 2>&1; then
  echo 'Runtime PVC remained after terminal delete' >&2
  exit 1
fi
wait_for_pv_deletion "${RESET_WORKSPACE_PV}"
wait_for_pv_deletion "${RESET_NIX_PV}"

printf '%s\n' \
  '{"kubernetes_conformance":"passed","storage_provisioning":"dynamic","package":"hello","blocked_package":"cowsay"}' |
  tee "${TMP_DIR}/evidence/kubernetes-conformance.json"
