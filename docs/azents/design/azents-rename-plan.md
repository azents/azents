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

The product, codebase, UI, infrastructure, test environments, generated clients,
and current documentation use the Azents brand. Backward compatibility for
superseded code identifiers, API client package names, environment-variable
names, and non-durable deployment resource names is not required.

Durable data resources are the exception to the ordering rule. Existing database
and object-storage resource identifiers may remain behind Azents configuration
until an explicitly planned data cutover. Their identifiers must not leak into
current user-facing product text or new code contracts.

## Naming contract

| Surface | Canonical form |
| --- | --- |
| Product name | `Azents` |
| Code and resource prefix | `azents` |
| Environment-variable prefix | `AZ_` |
| Python modules and packages | `azents*` |
| TypeScript packages | `@azents/*` |
| Protocol package | `azents.runtime_control.v1` |
| Kubernetes label domain | `azents.io/*` |
| Product URL | `https://azents.io` |
| API URL | `https://api.azents.io` |
| Slack slash command | `/azents` |

New identifiers must not add compatibility aliases for superseded brand
prefixes. Before durable data cutover, `AZ_*` variables may still reference
existing durable resources.

Credential encryption key values must be preserved exactly when configuration
keys are renamed; changing the value would make credentials stored in the
existing database unreadable.

## Completed rename scope

- Python apps, libraries, modules, imports, and generated clients use Azents
  identifiers.
- TypeScript apps and packages use the `@azents/*` namespace.
- Runtime-control protocol sources and generated bindings use the Azents package.
- User-visible product text, browser storage contracts, cookies, integration
  names, and callback configuration use Azents naming.
- Docker images, CI jobs, deployment scripts, Kubernetes workloads, labels, and
  Helm helpers use Azents naming.
- Documentation, test environments, and path-scoped convention directories use
  Azents paths.

## Durable data cutover

A future cutover of durable resource identifiers must be isolated from ordinary
branding cleanup:

1. Enter maintenance mode and freeze writes.
2. Snapshot and restore the relational database into canonical resources.
3. Copy object-storage data and perform a final delta synchronization.
4. Scan stored bucket names, URLs, and product-name values that require data
   migration.
5. Point `AZ_RDB_*` and `AZ_WORKSPACE_S3_*` configuration to the new resources.
6. Restart workloads and rerun auth, OAuth, runtime, file, and integration smoke
   tests.
7. Retain old resources read-only for the agreed recovery period before removal.

## Historical documentation boundary

Accepted ADRs and implemented Requirements and Design snapshots are immutable
historical authority. They retain the terminology and canonical identifiers that
were recorded when adopted. Migration-provenance records also retain exact source
identifiers. Current specs, mutable plans, notes, code, tests, and user-facing
surfaces must use Azents naming.

## Verification

- Scan tracked files case-insensitively for superseded brand variants.
- Treat a remaining match as valid only when it is inside an accepted ADR, an
  implemented snapshot, a canonical historical filename, or explicit migration
  provenance.
- Run Python and test-environment lint, format, type, and focused test checks.
- Validate documentation frontmatter and generated indexes.
- Keep all current and mutable surfaces free of superseded branding.
