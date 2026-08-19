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

```mermaid
flowchart TD
    PaymentService["terragrunt/_modules/payment-service/"] --> Main["main.tf<br/>ECS + RDS + S3 in one module"]
```

## Good

```mermaid
flowchart TD
    Modules["terragrunt/_modules/"]
    Modules --> Compute["payment-compute/<br/>ECS task + service"]
    Modules --> Data["payment-data/<br/>RDS cluster"]
    Modules --> Storage["payment-storage/<br/>S3 buckets"]
```
