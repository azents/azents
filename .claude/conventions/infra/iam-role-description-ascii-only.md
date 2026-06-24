---
title: "AWS IAM Role `description` field accepts only ASCII plus Latin-1 punctuation — no Korean, no em-dash (`—` U+2014), no smart quotes. Same rule applies to ACK-managed IAM Roles in Kubernetes."
---

# IAM Role `description` is ASCII + Latin-1 Only

The AWS IAM API rejects characters outside Latin-1 with a confusing 400 error that does not name the offending field. Korean text and em-dashes are the most common cause.

- ALWAYS write IAM Role descriptions in ASCII (or Latin-1 punctuation)
- AVOID Korean characters, em-dash `—` (U+2014), smart quotes `“ ”`, ellipsis `…`
- Use plain ASCII alternatives: hyphen `-`, straight quotes `"`, three dots `...`

## Bad

```yaml
spec:
  description: "azents-prd 워크로드용 — Bedrock 호출 권한"
```

## Good

```yaml
spec:
  description: "azents-prd workload role - Bedrock invocation permissions"
```
