---
title: "Treat load tests as one-time validation artifacts: preserve results, environment, commands, and reproduction steps in a test report."
---

# Preserve Load-Test Evidence as Reports

Load tests produce environment-sensitive evidence whose value comes from a reproducible report rather than permanent execution in routine suites.

- ALWAYS run a load test for one bounded feature, release, or incident validation and publish a test report.
- Record the purpose, date, commit or image identity, topology and resources, workload shape, exact commands, results, observed limits, and reproduction steps.
- Keep recurring automated suites focused on small deterministic protocol and behavior checks, and reference the load-test report when heavy-load evidence matters.
- When a later change requires fresh load evidence, execute a new bounded run and publish a new or explicitly updated report.
