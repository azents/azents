---
title: "Slack/Discord Integration-Wide E2E Test Environment Historical Decision Reconstruction"
created: 2026-04-11
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: integrations-260411
historical_reconstruction: true
migration_source: "docs/azents/design/integrations-e2e.md"
---

# Slack/Discord Integration-Wide E2E Test Environment Historical Decision Reconstruction

- Snapshot: `integrations-260411`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/integrations-e2e.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### integrations-260411/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Discussion Points and Decisions

Decisions agreed in Discussion #2456. See each comment thread for pros/cons.

| ID | Decision | Rationale summary |
|----|------|----------|
| **D1** | scenario directory = `scenarios/integrations/` | Same level as existing `scenarios/{sandbox-isolation,shell-tool,mcp-toolkit,chat-streaming,browser}/`, accommodates Slack/Discord/future integrations |
| **D2** | PR split = foundation → stacked by Phase | Merge foundation (`.env`/credentials/browser helper) quickly, distribute review burden by phase. Detailed stack structure in [Implementation Plan](#implementation-plan) |
| **D3** | tunneling = **Tailscale Funnel** (runs on the internal QA host) | Existing production infra uses Tailscale (`infra/argocd/tailscale-operator/`). Caddy limited to closed network, unusable. FRP needs separate VM → adopt Tailscale Funnel with 0 additional infra |
| **D4** | test account = shared QA email + **AWS SSM Parameter Store** + pull script | Existing testenv `.env` pattern is plaintext; 1Password adds tool. AWS SSM is same infra as ExternalSecrets and protected by IAM policy + KMS. Variable names are kebab-case (`/testenv/{project}/slack-platform-app/client-id`, etc.) |
| **D5** | 2FA = optional (TOTP automation supported, skip if absent) | Forcing it increases secret management burden; disabling risks Slack policy changes. Automatable with `pyotp`, but skip if account has no 2FA configured |
| **D6** | data cleanup = Admin API helper (`seed/slack_discord_cleanup.py`) | Automation required, called in scenario beforeAll. Idempotent |

D7 (CI integration) is **excluded from this work scope** per user feedback.

### Explicit source section: IAM Policy

Single policy `testenv` introduced in PR #2462 (`infra/terragrunt/_modules/testenv/`):

```json
{
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath", "ssm:DescribeParameters"],
      "Resource": "arn:aws:ssm:*:*:parameter/testenv/*"
    },
    {
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "*",
      "Condition": {"StringLike": {"kms:ViaService": "ssm.*.amazonaws.com"}}
    }
  ]
}
```

If testenv needs additional AWS permissions later, add Statement to this policy (S3, CloudWatch, etc.).

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
