---
title: "AWS Toolkit — Managed MCP + Direct SigV4 Signing Historical Requirements Reconstruction"
created: 2026-03-26
implemented: 2026-03-26
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: aws-260326
historical_reconstruction: true
migration_source: "docs/azents/design/aws-toolkit.md"
---

# AWS Toolkit — Managed MCP + Direct SigV4 Signing Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `aws-260326`
- Source: `docs/azents/design/aws-260326-aws-toolkit.md`
- Historical source date basis: `2026-03-26`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

AWS Toolkit implementation that directly connects over HTTPS to AWS Managed MCP Server. It provides Observability, Cost, and Infrastructure as single Toolkit by accessing 15,000+ AWS APIs.

**User scenarios:**
1. "Show recent 1-hour error logs" → `aws___call_aws` (CloudWatch Logs `FilterLogEvents`)
2. "Analyze this month's cost" → `aws___call_aws` (Cost Explorer `GetCostAndUsage`)
3. "Check EKS cluster status" → `aws___call_aws` (EKS `DescribeCluster`)
4. "Show EC2 instance list" → `aws___call_aws` (EC2 `DescribeInstances`)
5. "Tell me how to use this API" → `aws___search_documentation` + `aws___suggest_aws_commands`

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
