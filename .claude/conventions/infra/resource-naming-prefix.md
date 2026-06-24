---
title: "Name AWS resources `{project_name}-{environment}-{service}` (e.g. `azents-prd-api`); for resources with length-limited names, use `short_name_prefix` (e.g. `mfprd-`)."
---

# Resource Naming Convention

Consistent prefixing makes it possible to identify owner / environment from any resource name in a console search.

- Default: `{project_name}-{environment}-{service}` → `azents-prd-api`, `azents-stg-worker`
- Length-limited (RDS cluster, IAM role, S3 bucket prefix, etc.): use `short_name_prefix` → `mfprd-`, `niprd-`
- Modules accept both `name_prefix` and `short_name_prefix` and choose internally based on AWS API limits

## Bad

```hcl
resource "aws_iam_role" "this" {
  name = "my-role"
}
```

## Good

```hcl
resource "aws_iam_role" "this" {
  name = "${var.short_name_prefix}-task-execution"
}
```
