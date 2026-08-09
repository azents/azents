#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CLUSTER_NAME="${AZENTS_KUBERNETES_CONTAINMENT_CLUSTER_NAME:-azents-phase5}"
NAMESPACE="azents-runtime"
REGISTRY_NAME="${CLUSTER_NAME}-registry"
REGISTRY_PORT="5001"
KIND_NODE_IMAGE="kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5"
APPARMOR_PARSER="$(command -v apparmor_parser)"
TMP_DIR="$(mktemp -d)"

cleanup() {
  local status=$?
  trap - EXIT
  set +e
  kubectl get pods,pvc,networkpolicy -A -o wide >"${TMP_DIR}/resources.txt" 2>&1
  kubectl get events -A --sort-by=.lastTimestamp \
    >"${TMP_DIR}/events.txt" 2>&1
  kubectl describe pods -n "${NAMESPACE}" >"${TMP_DIR}/pod-descriptions.txt" 2>&1
  sed -i -E \
    '/AZ_RUNTIME_RUNNER_AUTH_(TOKEN|CREDENTIAL_ID):/s/: .*/: <redacted>/' \
    "${TMP_DIR}/pod-descriptions.txt"
  for pod in $(kubectl get pods -n "${NAMESPACE}" -o name 2>/dev/null); do
    kubectl logs -n "${NAMESPACE}" "${pod}" --all-containers \
      >"${TMP_DIR}/$(basename "${pod}").log" 2>&1 || true
  done
  for node in $(kind get nodes --name "${CLUSTER_NAME}" 2>/dev/null); do
    docker logs "${node}" >"${TMP_DIR}/${node}.log" 2>&1 || true
    docker exec "${node}" journalctl -u kubelet --no-pager \
      >"${TMP_DIR}/${node}-kubelet.log" 2>&1 || true
    docker exec "${node}" journalctl -u containerd --no-pager \
      >"${TMP_DIR}/${node}-containerd.log" 2>&1 || true
  done
  if [[ "${status}" -eq 0 ]]; then
    cat >"${TMP_DIR}/junit.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="kubernetes-containment" tests="1" failures="0">
  <testcase classname="runtime.containment" name="disposable_cluster_conformance"/>
</testsuite>
EOF
  else
    cat >"${TMP_DIR}/junit.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="kubernetes-containment" tests="1" failures="1">
  <testcase classname="runtime.containment" name="disposable_cluster_conformance">
    <failure message="Disposable Kubernetes containment conformance failed"/>
  </testcase>
</testsuite>
EOF
  fi
  if [[ -n "${AZENTS_E2E_ARTIFACT_DIR:-}" ]]; then
    mkdir -p "${AZENTS_E2E_ARTIFACT_DIR}"
    cp -R "${TMP_DIR}/." "${AZENTS_E2E_ARTIFACT_DIR}/"
  fi
  kind delete cluster --name "${CLUSTER_NAME}" >/dev/null 2>&1 || true
  docker rm -f "${REGISTRY_NAME}" >/dev/null 2>&1 || true
  rm -rf "${TMP_DIR}"
  exit "${status}"
}
trap cleanup EXIT

for command in docker kind kubectl jq; do
  command -v "${command}" >/dev/null
done

docker run -d --restart=always \
  -p "127.0.0.1:${REGISTRY_PORT}:5000" \
  --name "${REGISTRY_NAME}" \
  registry:2.8.3 >/dev/null

cat >"${TMP_DIR}/kind.yaml" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
featureGates:
  UserNamespacesSupport: true
nodes:
  - role: control-plane
    extraMounts:
      # containerd loads its generated RuntimeDefault profile through securityfs.
      - hostPath: /sys/kernel/security
        containerPath: /sys/kernel/security
EOF

kind create cluster \
  --name "${CLUSTER_NAME}" \
  --image "${KIND_NODE_IMAGE}" \
  --retain \
  --config "${TMP_DIR}/kind.yaml"
docker network connect kind "${REGISTRY_NAME}" 2>/dev/null || true
for node in $(kind get nodes --name "${CLUSTER_NAME}"); do
  docker cp "${APPARMOR_PARSER}" "${node}:/usr/sbin/apparmor_parser"
  docker exec "${node}" \
    sh -ec '
      test "$(cat /sys/module/apparmor/parameters/enabled)" = "Y"
      test -r /sys/kernel/security/apparmor/profiles
      grep -Fq "azents-runtime-bwrap" /sys/kernel/security/apparmor/profiles
      test -x /sbin/apparmor_parser
      install -d /etc/systemd/system/containerd.service.d
      cat > /etc/systemd/system/containerd.service.d/azents-apparmor.conf <<EOF
[Service]
Environment=container=
EOF
      systemctl daemon-reload
      systemctl restart containerd
      containerd_pid="$(systemctl show --property=MainPID --value containerd)"
      test "${containerd_pid}" -gt 0
      ! tr "\0" "\n" <"/proc/${containerd_pid}/environ" |
        grep -Eq "^container=.+$"
      mkdir -p /unmasked-sys
      mountpoint -q /unmasked-sys || mount -t sysfs none /unmasked-sys
    '
  registry_dir="/etc/containerd/certs.d/localhost:${REGISTRY_PORT}"
  docker exec "${node}" mkdir -p "${registry_dir}"
  cat <<EOF | docker exec -i "${node}" \
    sh -c "cat > '${registry_dir}/hosts.toml'"
[host."http://${REGISTRY_NAME}:5000"]
EOF
  docker exec "${node}" \
    install -d -m 0770 -o 1000 -g 1000 \
    /var/local/azents-phase5-workspace
done

for component in azents-runtime-runner azents-runtime-provider-kubernetes; do
  dockerfile="python/apps/${component}/Dockerfile"
  image="localhost:${REGISTRY_PORT}/${component}:phase5"
  docker build -f "${dockerfile}" -t "${image}" "${ROOT_DIR}"
  docker push "${image}"
done

RUNNER_IMAGE="$(
  docker image inspect \
    --format '{{range .RepoDigests}}{{println .}}{{end}}' \
    "localhost:${REGISTRY_PORT}/azents-runtime-runner:phase5" |
    grep "^localhost:${REGISTRY_PORT}/azents-runtime-runner@sha256:" |
    head -1
)"
PROVIDER_IMAGE="$(
  docker image inspect \
    --format '{{range .RepoDigests}}{{println .}}{{end}}' \
    "localhost:${REGISTRY_PORT}/azents-runtime-provider-kubernetes:phase5" |
    grep "^localhost:${REGISTRY_PORT}/azents-runtime-provider-kubernetes@sha256:" |
    head -1
)"
test -n "${RUNNER_IMAGE}"
test -n "${PROVIDER_IMAGE}"

kubectl create namespace "${NAMESPACE}"
kubectl run phase5-registry-pull-preflight -n "${NAMESPACE}" \
  --image="${RUNNER_IMAGE}" \
  --restart=Never \
  --command -- /usr/bin/true
kubectl wait -n "${NAMESPACE}" \
  --for=jsonpath='{.status.phase}'=Succeeded \
  pod/phase5-registry-pull-preflight \
  --timeout=120s
kubectl delete pod phase5-registry-pull-preflight -n "${NAMESPACE}" --wait=true
kubectl create configmap local-registry-hosting -n kube-public \
  --from-literal=localRegistryHosting.v1="host: \"localhost:${REGISTRY_PORT}\""
kubectl create configmap phase5-provider-driver -n "${NAMESPACE}" \
  --from-file=driver.py="${ROOT_DIR}/python/apps/azents-runtime-provider-kubernetes/tests/kubernetes_containment_conformance_driver.py"

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: phase5-provider
  namespace: ${NAMESPACE}
---
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: phase5-runc
handler: runc
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: phase5-provider
  namespace: ${NAMESPACE}
rules:
  - apiGroups: [""]
    resources: ["pods", "persistentvolumeclaims"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["get", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: phase5-provider
  namespace: ${NAMESPACE}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: phase5-provider
subjects:
  - kind: ServiceAccount
    name: phase5-provider
    namespace: ${NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: phase5-provider-runtime-class
rules:
  - apiGroups: ["node.k8s.io"]
    resources: ["runtimeclasses"]
    resourceNames: ["phase5-runc"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: phase5-provider-runtime-class
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: phase5-provider-runtime-class
subjects:
  - kind: ServiceAccount
    name: phase5-provider
    namespace: ${NAMESPACE}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: phase5-workspace
spec:
  capacity:
    storage: 256Mi
  accessModes: ["ReadWriteOnce"]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: manual
  hostPath:
    path: /var/local/azents-phase5-workspace
    type: DirectoryOrCreate
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
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: denied-echo
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: denied-echo
  template:
    metadata:
      labels:
        app: denied-echo
    spec:
      containers:
        - name: echo
          image: ${RUNNER_IMAGE}
          command: ["/usr/local/bin/python", "-m", "http.server", "8031"]
          ports:
            - containerPort: 8031
---
apiVersion: v1
kind: Service
metadata:
  name: denied-echo
  namespace: ${NAMESPACE}
spec:
  selector:
    app: denied-echo
  ports:
    - port: 8031
      targetPort: 8031
EOF

kubectl rollout status deployment/runtime-control -n "${NAMESPACE}" --timeout=120s
kubectl rollout status deployment/denied-echo -n "${NAMESPACE}" --timeout=120s

run_provider() {
  local job_name="$1"
  local profile_mode="$2"
  cat <<EOF | kubectl apply -f -
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
      serviceAccountName: phase5-provider
      containers:
        - name: provider
          image: ${PROVIDER_IMAGE}
          command:
            - /workspace/python/apps/azents-runtime-provider-kubernetes/.venv/bin/python
            - /conformance/driver.py
          env:
            - name: PHASE5_RUNNER_IMAGE
              value: ${RUNNER_IMAGE}
            - name: PHASE5_PROFILE_MODE
              value: ${profile_mode}
            - name: AZ_RUNTIME_CONTROL_ENDPOINT
              value: runtime-control:8030
            - name: AZ_RUNTIME_CONTROL_ALLOW_INSECURE
              value: "true"
            - name: AZ_RUNTIME_PROVIDER_READINESS_FILE
              value: /tmp/phase5-provider-ready
            - name: AZ_RUNTIME_PROVIDER_SERVICE_ACCOUNT_TOKEN_FILE
              value: /var/run/secrets/kubernetes.io/serviceaccount/token
            - name: AZ_RUNTIME_PROVIDER_ID
              value: phase5-kubernetes
            - name: AZ_RUNTIME_PROVIDER_LEASE_NAMESPACE
              value: ${NAMESPACE}
            - name: AZ_RUNTIME_PROVIDER_WORKLOAD_NAMESPACE
              value: ${NAMESPACE}
            - name: AZ_RUNTIME_PROVIDER_LEASE_NAME
              value: phase5-provider
            - name: AZ_RUNTIME_PROVIDER_LEASE_DURATION_SECONDS
              value: "15"
            - name: AZ_RUNTIME_PROVIDER_WORKSPACE_PATH
              value: /runtime/home
            - name: AZ_RUNTIME_PROVIDER_ENGINE_IMAGE
              value: ${RUNNER_IMAGE}
            - name: AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_NAMESPACE
              value: ${NAMESPACE}
            - name: AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_LABELS
              value: '{"app":"runtime-control"}'
            - name: AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_PORT
              value: "8030"
            - name: AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_ALLOWED_CIDRS
              value: '[]'
            - name: AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_DENIED_CIDRS
              value: '["0.0.0.0/0"]'
            - name: AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_EXTRA_EGRESS
              value: '[]'
            - name: AZ_RUNTIME_PROVIDER_POD_IMAGE_PULL_SECRETS
              value: '[]'
            - name: AZ_RUNTIME_PROVIDER_POD_ANNOTATIONS
              value: '{}'
            - name: AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_BACKEND
              value: bwrap
            - name: AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_SECURITY_PROFILE
              value: azents-runtime-bwrap
            - name: AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_QUALIFICATION_TIMEOUT_SECONDS
              value: "30"
            - name: AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_RUNTIME_CLASS_NAME
              value: phase5-runc
          volumeMounts:
            - name: driver
              mountPath: /conformance
              readOnly: true
      volumes:
        - name: driver
          configMap:
            name: phase5-provider-driver
EOF
  kubectl wait -n "${NAMESPACE}" \
    --for=condition=complete "job/${job_name}" --timeout=120s
  kubectl logs -n "${NAMESPACE}" "job/${job_name}"
}

runtime_pod() {
  kubectl get pods -n "${NAMESPACE}" \
    -l azents/runtime-id=phase5 \
    -o jsonpath='{.items[0].metadata.name}'
}

wait_for_qualification() {
  local pod
  pod="$(runtime_pod)"
  kubectl wait -n "${NAMESPACE}" --for=condition=Ready "pod/${pod}" --timeout=120s
  for _ in $(seq 1 120); do
    if kubectl logs -n "${NAMESPACE}" "${pod}" -c runner 2>&1 |
      grep -Fq "Runtime Runner execution backend qualification succeeded"; then
      printf '%s\n' "${pod}"
      return
    fi
    sleep 1
  done
  kubectl logs -n "${NAMESPACE}" "${pod}" -c runner
  return 1
}

run_provider phase5-contained-start contained
POD="$(wait_for_qualification)"
POD_JSON="$(kubectl get pod -n "${NAMESPACE}" "${POD}" -o json)"
jq -e '
  .spec.hostUsers == false
  and .spec.automountServiceAccountToken == false
  and .spec.runtimeClassName == "phase5-runc"
  and (.spec.containers | length == 1)
  and .spec.containers[0].securityContext.privileged == false
  and .spec.containers[0].securityContext.allowPrivilegeEscalation == true
  and .spec.containers[0].securityContext.runAsNonRoot == true
  and .spec.containers[0].securityContext.runAsUser == 1000
  and .spec.containers[0].securityContext.runAsGroup == 1000
  and .spec.containers[0].securityContext.procMount == "Unmasked"
  and .spec.containers[0].securityContext.seccompProfile.type == "Unconfined"
  and .spec.containers[0].securityContext.appArmorProfile.type == "Localhost"
  and .spec.containers[0].securityContext.appArmorProfile.localhostProfile == "azents-runtime-bwrap"
  and (.spec.containers[0].securityContext.capabilities.drop == ["ALL"])
  and ((.spec.containers[0].securityContext.capabilities.add | sort) == (["SYS_ADMIN","SYS_CHROOT","NET_ADMIN","SETUID","SETGID","SYS_PTRACE","SETPCAP"] | sort))
  and ((.spec.volumes | map(.name) | sort) == (["agent-workspace","agent-temporary","runner-private"] | sort))
  and ([.spec.volumes[] | select(.projected != null or .secret != null)] | length == 0)
' <<<"${POD_JSON}" >/dev/null

kubectl cp \
  "${ROOT_DIR}/python/apps/azents-runtime-runner/tests/kubernetes_containment_conformance_probe.py" \
  "${NAMESPACE}/${POD}:/runtime/home/conformance_probe.py" \
  -c runner
kubectl exec -n "${NAMESPACE}" "${POD}" -c runner -- \
  /workspace/python/apps/azents-runtime-runner/.venv/bin/python \
  /runtime/home/conformance_probe.py \
  runtime-control 8030 denied-echo 8031
kubectl exec -n "${NAMESPACE}" "${POD}" -c runner -- \
  touch /run/azents/runner-private/private-marker

kubectl delete pod -n "${NAMESPACE}" "${POD}" --wait=true
run_provider phase5-contained-recreate contained
POD="$(wait_for_qualification)"
kubectl exec -n "${NAMESPACE}" "${POD}" -c runner -- \
  test -f /runtime/home/workspace-marker
kubectl exec -n "${NAMESPACE}" "${POD}" -c runner -- \
  test ! -e /run/azents/agent-tmp/temporary-marker
kubectl exec -n "${NAMESPACE}" "${POD}" -c runner -- \
  test ! -e /run/azents/runner-private/private-marker

kubectl delete pod -n "${NAMESPACE}" "${POD}" --wait=true
run_provider phase5-direct-rollback direct
POD="$(runtime_pod)"
kubectl wait -n "${NAMESPACE}" --for=condition=Ready "pod/${POD}" --timeout=120s
POD_JSON="$(kubectl get pod -n "${NAMESPACE}" "${POD}" -o json)"
jq -e '
  .spec.hostUsers == null
  and .spec.automountServiceAccountToken == false
  and (.spec.volumes | map(.name) == ["agent-workspace"])
  and .spec.containers[0].securityContext.allowPrivilegeEscalation == false
  and .spec.containers[0].securityContext.procMount == null
  and .spec.containers[0].securityContext.seccompProfile == null
  and .spec.containers[0].securityContext.appArmorProfile == null
  and ([.spec.containers[0].env[] | select(.name == "AZ_RUNTIME_PROCESS_CONTAINMENT_CONFIG")] | length == 0)
' <<<"${POD_JSON}" >/dev/null
kubectl exec -n "${NAMESPACE}" "${POD}" -c runner -- \
  test -f /runtime/home/workspace-marker
