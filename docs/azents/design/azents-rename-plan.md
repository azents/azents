---
title: "Azents rename plan"
created: 2026-05-26
tags: [architecture, infra, backend, frontend, documentation]
document_role: supporting
document_type: supporting-plan
migration_source: "docs/azents/design/azents-rename-plan.md"
---

# Azents rename plan

## Context

NoIntern is being renamed to Azents across code, UI, infrastructure, test
environments, generated clients, and documentation. Backward compatibility for
old code identifiers, API client package names, environment variable names, and
deployment resource names is not required.

Durable data resources are the exception to the ordering rule. Database and
object-storage resources must keep using the existing NoIntern resources until
the final cutover step. The final data rename will happen through database
snapshot/restore and object-storage copy/sync.

Tracking issue: <https://github.com/azents/azents/issues/4079>

## Naming contract

| Current | Target |
| --- | --- |
| `NoIntern` | `Azents` |
| `nointern` | `azents` |
| `NOINTERN_` | `AZ_` |
| `NI_` | `AZ_` |
| `nointern-*` | `azents-*` |
| `nointern.runtime_control.v1` | `azents.runtime_control.v1` |
| `azents.io/*` Kubernetes label domain | `azents.io/*` |
| `https://nointern.com` | `https://azents.io` |
| `https://api.nointern.com` | `https://api.azents.io` |
| `/nointern` Slack slash command | `/azents` |

New environment variables must not keep compatibility aliases for the old
prefixes. Before durable data cutover, the new `AZ_*` variables may still point
to the existing NoIntern RDS and object-storage resources.

The credential encryption key value must be preserved exactly when moving from
`NI_CREDENTIAL_ENCRYPTION_KEY` to `AZ_CREDENTIAL_ENCRYPTION_KEY`, otherwise
encrypted credentials stored in the existing database cannot be decrypted.

## Phase order

### 1. Rename contract and scope registration

- Add this rename plan.
- Update path-scoped convention indexes and docs tooling only when the
  corresponding paths move from `nointern` to `azents`.
- Keep historical ADR handling explicit: either rename historical references as
  part of the full-brand sweep or intentionally leave documented historical
  references with an allowlist.

### 2. Code, package, and protocol rename

- Rename Python apps and libs from `nointern*` to `azents*`.
- Rename Python modules and imports from `nointern` / `nointern_runtime_*` to
  Azents equivalents.
- Rename TypeScript apps and packages from `@azents/nointern-*` to
  `@azents/*`.
- Rename Dart app package and native bundle identifiers.
- Rename protobuf paths and package names, then regenerate generated Python
  code from proto sources.

### 3. UI, API, and generated client rename

- Replace user-visible product text with Azents.
- Rename browser storage keys, cookie names, and `postMessage` event types.
- Update OpenAPI titles and descriptions.
- Regenerate Python and TypeScript clients instead of editing generated code.
- Rename Slack and Discord user-facing integration names and callback config.

### 4. Non-durable infrastructure rename

- Rename Dockerfiles, image names, ECR paths, GitHub Actions inputs/jobs, and
  deployment scripts.
- Rename ArgoCD apps, Kubernetes namespaces, services, workloads, labels, and
  Helm chart helpers.
- Route `azents.io` and `api.azents.io` to the Azents workloads.
- Keep database and object-storage endpoint values pointed at existing NoIntern
  durable resources through the new `AZ_*` variables.

### 5. Test environment, docs, and conventions rename

- Move `docs/nointern` to `docs/azents`.
- Move `testenv/nointern` to `testenv/azents`.
- Rename path-scoped convention scopes from NoIntern to Azents.
- Regenerate docs and convention indexes.

### 6. Verification against existing durable data

- Run Python lint, typecheck, and tests for affected subprojects.
- Run TypeScript generate, typecheck, lint, and build for affected workspaces.
- Validate protobuf and generated-client outputs.
- Build Docker images for server, web, admin web, runtime runner, and runtime
  providers.
- Run `kustomize build`, `helm template`, chart tests, and relevant Terragrunt
  plans.
- Smoke test auth, OAuth callbacks, agent runtime create/resume, file
  upload/download, and Slack/Discord callbacks.

### 7. Final durable data cutover

- Enter maintenance mode and freeze writes.
- Create an RDS snapshot from the existing NoIntern database.
- Restore the snapshot into Azents-named RDS resources.
- Create Azents object-storage buckets and perform full copy plus final delta
  sync.
- Scan and migrate database-stored bucket names, URLs, and product-name
  references where needed.
- Point `AZ_RDB_*` and `AZ_WORKSPACE_S3_*` to the new durable resources.
- Restart Azents workloads and rerun smoke/E2E tests.

### 8. Old resource retirement

- Keep old NoIntern RDS and object-storage resources read-only for the agreed
  retention period.
- Remove old NoIntern ArgoCD, Terragrunt, Secrets Manager, ECR, DNS, and CI
  leftovers.
- Run a final repository scan for `NoIntern`, `nointern`, `NOINTERN_`, `NI_`,
  and related variants.

## Feasibility notes from latest main

- Latest `main` includes runtime provider reconciliation changes and additional
  `NOINTERN_RUNTIME_RUNNER_*` environment variables. These are in rename scope.
- ArgoCD and Helm RuntimeClass templates were removed before this plan, so
  RuntimeClass resource rename is not in scope.
- Route53 hosted zones for `azents.io` and `azents.net` already exist in the
  Terragrunt domains module.
- The main risk is not code compatibility. The main risk is sequencing:
  non-durable rename must be validated while still pointing at old durable
  data, and durable data rename must be isolated to the final cutover.
