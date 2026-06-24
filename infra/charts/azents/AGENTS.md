# Azents Helm Chart

This directory owns the single Azents Helm chart.

- Source of truth: `docs/azents/design/helm-packaging.md`
- Existing Kubernetes source reference: `infra/argocd/azents-*`
- Production infrastructure source reference: `infra/terragrunt/production/azents-server-infra/`, `infra/terragrunt/_modules/azents-server-infra/`
- `server`, `web`, `adminWeb`, and `runtimeProviderKubernetes` are service-runtime profiles.
- Keep `mcpEgressProxy` and AWS/EKS/ALB integrations default-off and opt-in.
- Do not put secret literals in default values. Represent credentials only through `existingSecret` references.
- Bundled object storage must use RustFS only.
- ArgoCD `valuesObject` overlay patches replace the whole object instead of deep-merging it. Document consumer values so overlays do not accidentally drop base values.
