---
title: "AWS Toolkit — Managed MCP + Direct SigV4 Signing Historical Decision Reconstruction"
created: 2026-03-26
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: aws-260326
historical_reconstruction: true
migration_source: "docs/azents/design/aws-toolkit.md"
---

# AWS Toolkit — Managed MCP + Direct SigV4 Signing Historical Decision Reconstruction

- Snapshot: `aws-260326`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/aws-toolkit.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### aws-260326/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: IAM Policy Guide

Dynamically provide IAM policy example depending on selection:

**Read-only (default):**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "aws-mcp:InvokeMcp",
        "aws-mcp:CallReadOnlyTool"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricData",
        "cloudwatch:DescribeAlarms",
        "logs:FilterLogEvents",
        "ce:GetCostAndUsage",
        "ec2:Describe*",
        "ecs:Describe*",
        "eks:Describe*"
      ],
      "Resource": "*"
    }
  ]
}
```

**Read+Write:**
Add `aws-mcp:CallReadWriteTool` above + necessary service-specific write permissions.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
