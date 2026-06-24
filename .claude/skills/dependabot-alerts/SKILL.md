---
name: dependabot-alerts
description: Inspect Dependabot alerts for the Azents repository and summarize actionable vulnerabilities.
---

# Dependabot Alerts

Use the Azents repository name when querying GitHub alerts.

```bash
gh api 'repos/azents/azents/dependabot/alerts?state=open&per_page=100' \
  --jq '.[] | {number, state, package: .dependency.package.name, ecosystem: .dependency.package.ecosystem, severity: .security_advisory.severity, summary: .security_advisory.summary}'
```

Summarize:

- affected package and ecosystem
- severity
- vulnerable range and patched version
- affected subproject when inferable
- recommended update command

Do not dismiss alerts unless the user explicitly asks.
