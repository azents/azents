# Azents Helm Chart

This chart deploys Azents as a single Helm release.

## Scope

The chart renders the `server`, `web`, `adminWeb`, and Agent Runtime provider profiles. It also supports default-off optional components and ArgoCD drift tracking against the legacy Kustomize manifests.

## Source Of Truth

- Design document: `docs/azents/design/helm-packaging.md`
- Kustomize source reference: `infra/argocd/azents-*`

## Default Profile

Default-on service runtime components:

- `server.apiserver`
- `server.adminserver`
- `server.worker`
- `server.scheduler`
- `web`
- `adminWeb`

Default-off optional components:

- `server.mcpEgressProxy`
- `server.runtimeControl`
- `runtimeProviderKubernetes`

## Secret Policy

The chart does not put secret literals in default values and does not render secret delivery CRDs. Consumers create Kubernetes Secrets through their own platform layer and reference those names through `secrets.existingSecrets.*`.

### Existing Secret Contract

Chart consumers create Kubernetes Secrets with the keys below and reference their names through `secrets.existingSecrets.*`.

| Values key | Required Secret keys | Used by |
| --- | --- | --- |
| `secrets.existingSecrets.auth` | `jwt-secret-key`, `credential-encryption-key`, `sentry-dsn`, `oauth-secret-key` | `apiserver`, `adminserver`, `worker`, `scheduler` |
| `secrets.existingSecrets.adminAuth` | `AUTH_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, or any admin web env keys required by the selected auth mode | `adminWeb` `envFrom` |

`adminAuth` injects the whole Secret into the `adminWeb` container environment. Installations that do not use GitHub OAuth only need to provide the keys required by their admin web settings.

## External Service Policy

The chart does not render PostgreSQL, Redis/Valkey, object storage, or other external service resources. Consumers provide those services through their own platform layer and configure this chart with endpoints and existing Kubernetes Secrets.

## Render Surface

The chart currently renders:

- `server` ServiceAccount, Role/RoleBinding, shared env ConfigMap, and core auth Secret references
- `server.apiserver`, `server.adminserver`, `server.worker`, `server.scheduler`, and `server.runtimeControl` Deployments
- `apiserver`, `adminserver`, and `runtime-control` Services
- `web` ServiceAccount, Role/RoleBinding, ConfigMap, Deployment, Service, and opt-in Ingress
- `adminWeb` ServiceAccount, Role/RoleBinding, ConfigMap, Deployment, Service, and opt-in Ingress
- `runtimeProviderKubernetes` Deployment, ServiceAccount, PDB, workload namespace, and split leader/workload RBAC
- Opt-in `server.mcpEgressProxy`

Ingress is disabled by default. Use `server.apiserver.ingress`, `web.ingress`, and `adminWeb.ingress` for component-specific host, class, and TLS settings.

By default, application resources render into the Helm release namespace. Use `helm install --namespace ... --create-namespace` or the ArgoCD Application destination namespace to choose it. Component-specific namespace overrides exist only for deployments that intentionally split components across namespaces. `runtimeProviderKubernetes.workloadNamespace.name` remains separate for Runtime Pods and PVCs, and that namespace must be created by the consumer-owned deployment layer.

Container resource requirements follow the standard Helm chart pattern: defaults are `{}`, and the chart renders a container `resources` stanza only when the consumer sets component-specific `*.resources` values. Runtime runner Pods are the exception: `runtimeProviderKubernetes.runnerResources` defaults to CPU `1` and memory `2Gi` requests with no limits so interactive tool operations have reserved capacity while remaining burstable.

## Agent Runtime Provider Contract

`runtimeProviderKubernetes` is default-off. When enabled, the provider Pod runs in the server namespace and creates Runtime Pods and PVCs in `runtimeProviderKubernetes.workloadNamespace.name`.

- Server ConfigMap: `AZ_RUNTIME_DEFAULT_PROVIDER_ID`, `AZ_RUNTIME_RUNNER_IMAGE`, `AZ_RUNTIME_RUNNER_CONTROL_ENDPOINT`
- Provider Deployment: `AZ_RUNTIME_PROVIDER_LEASE_NAMESPACE`, `AZ_RUNTIME_PROVIDER_WORKLOAD_NAMESPACE`, `AZ_RUNTIME_PROVIDER_WORKSPACE_PATH`, `AZ_RUNTIME_PROVIDER_STORAGE_CLASS`, `AZ_RUNTIME_PROVIDER_POD_IMAGE_PULL_SECRETS`
- Provider RBAC: leader election Lease permissions are scoped to the provider namespace, while Runtime Pod/PVC permissions are scoped to the workload namespace
- Runtime Pod image pulls: by default, Runtime Pods inherit `global.imagePullSecrets`. Consumers may override with `runtimeProviderKubernetes.runtimePod.imagePullSecrets`. Referenced pull secrets must already exist in the workload namespace.
- Runtime Pod resources: `runtimeProviderKubernetes.runnerResources` is passed to the Provider as Kubernetes `ResourceRequirements`. Defaults set requests to CPU `1` and memory `2Gi`; limits are intentionally omitted unless consumers set them.
- Persistence: Kubernetes Provider v1 uses PVCs in the workload namespace as canonical persistence
- Runtime NetworkPolicy: `runtimeProviderKubernetes.networkPolicy.deniedCidrs`
  defines the CIDRs excluded from the default public egress rule,
  `allowedCidrs` adds explicit CIDR egress rules, and `extraEgress` appends raw
  Kubernetes NetworkPolicy egress rules for service-specific exceptions. NetworkPolicy
  rules are additive, so explicit egress entries remain allowed even when a broader
  CIDR appears in `deniedCidrs`.

## External Service And Credential Modes

`database.mode`, `redis.mode`, and `objectStorage.mode` are external service configuration gates.

- `external`: use consumer-provided endpoints and Secrets.
- `objectStorage.external.credentialMode=ambientAws`: do not inject explicit S3 credential env vars. EKS Pod Identity, IAM Roles, or another ambient credential provider must be configured outside this chart.

Secret delivery is outside this chart. External Secrets Operator, Infisical, SOPS, Sealed Secrets, cloud secret managers, and manual Secrets must be wired by the consumer-owned deployment layer.

## Optional Component Prerequisites

- `server.mcpEgressProxy.enabled=true`: renders the Squid proxy Deployment/Service/NetworkPolicy in the server namespace and injects `AZ_MCP_PROXY_URL` into the server ConfigMap.
- `runtimeProviderKubernetes.enabled=true`: requires `runtimeProviderKubernetes.image.*`, `runtimeProviderKubernetes.runnerImage.*`, and `server.runtimeControl.enabled=true`.

## Kustomize Label Differences

The legacy Kustomize manifests use component app names in `app.kubernetes.io/name`.

- `infra/argocd/azents-server`: `app.kubernetes.io/name=azents-server`
- `infra/argocd/azents-web`: `app.kubernetes.io/name=azents-web`
- `infra/argocd/azents-admin-web`: `app.kubernetes.io/name=azents-admin-web`

The Helm chart uses common chart/release labels plus `app.kubernetes.io/component`. Service selectors and Pod labels are generated from shared helpers, but byte-for-byte label parity with the Kustomize source is not a goal.

## ArgoCD Drift Tracking

The chart tracks whether it preserves the same component contracts as the Kustomize source.

The chart does not own consumer-specific values or ArgoCD Application values. Each consumer owns its deployment values.

Warning: ArgoCD `Application.spec.source.helm.valuesObject` is opaque to Kustomize Strategic Merge Patch. Overlay patches replace the whole object instead of deep-merging it. Consumers that patch `valuesObject` must copy all base values into the patch, or make each environment Application own one complete `valuesObject`.

## Kustomize To Helm Mapping

| Legacy Kustomize source | Helm values/templates | Main difference |
| --- | --- | --- |
| `infra/argocd/azents-server/base/*` | `server.*`, `templates/server/*` | Secret handling is normalized through `existingSecret` references. |
| `infra/argocd/azents-web/base/*` | `web.*`, `templates/web/*` | Labels use common chart labels plus component labels. |
| `infra/argocd/azents-admin-web/base/*` | `adminWeb.*`, `templates/admin-web/*` | Production env Secret injection is represented by `secrets.existingSecrets.adminAuth`. |
| `infra/argocd/azents-runtime-provider-kubernetes/base/*` | `runtimeProviderKubernetes.*`, `templates/runtime-provider-kubernetes/*` | Provider and workload namespace RBAC are split. |
| `infra/argocd/azents-server/base/mcp-egress-proxy-*` | `server.mcpEgressProxy.*`, `templates/server/mcp-egress-proxy.yaml.tpl` | The proxy is represented as a server-level opt-in feature gate. |

## Drift Check

When Helm is available:

1. Prepare consumer-owned values in a separate file and run `helm template azents infra/charts/azents --values <consumer-values.yaml> > /tmp/azents-helm.yaml`.
2. Run `kustomize build infra/argocd/azents-server/base > /tmp/azents-server-kustomize.yaml`.
3. Render the other component Kustomize bases in the same way.
4. Compare resource kind/name/namespace, container command/port/probe/resource contracts, Service ports, Secret key contracts, NetworkPolicy peers, and NetworkPolicy ports.
5. If a component is added to or removed from Kustomize, update the chart values/templates to preserve the same component contract.
6. Classify intended differences as known differences below. Unclassified differences are chart or Kustomize source drift.

Known differences:

- The chart uses component-specific values under one release.
- The chart label set does not aim for byte-for-byte parity with Kustomize labels.
- The chart references existing Kubernetes Secrets; secret delivery resources are owned by consumer deployment manifests.
- Production AWS/EKS/ALB/Pod Identity integration is the responsibility of consumer-owned values and resources.
- PostgreSQL, Valkey, and object storage resources are owned by the consumer deployment layer, not this chart.
