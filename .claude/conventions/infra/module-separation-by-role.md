---
title: "Keep compute (ECS) modules separate from data (RDS, S3) modules; place cross-environment shared resources under `terragrunt/common/`. A module that mixes compute + data couples deploy lifecycles that should be independent."
---

# Module Separation by Role

A module that creates ECS + RDS together forces you to redeploy the database to change a task definition, and vice versa. Separating compute from stateful resources keeps blast radius small.

- ECS / Lambda / Step Functions → compute module
- RDS / S3 / DynamoDB → data module
- Cross-environment IAM, VPC, shared KMS → `terragrunt/common/`
- Per-environment wiring → `terragrunt/<env>/<module>/`

## Bad

```
terragrunt/_modules/payment-service/
└── main.tf  (ECS + RDS + S3 in one module)
```

## Good

```
terragrunt/_modules/
├── payment-compute/   # ECS task + service
├── payment-data/      # RDS cluster
└── payment-storage/   # S3 buckets
```
