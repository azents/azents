---
title: "When overriding the Fluent Bit Helm chart's `config.filters`, you must explicitly include the default kubernetes filter — overriding `config.filters` REPLACES the chart default, dropping the kubernetes metadata filter entirely."
---

# Fluent Bit `config.filters` Override Drops Defaults

Helm's value override is a full replacement for list/string fields, not a deep merge. Setting `config.filters` to your additions wipes the chart's built-in `[FILTER] Name kubernetes` block, which is what enriches log records with pod/container/namespace.

- ALWAYS copy the chart's default kubernetes filter into your override
- Verify the rendered ConfigMap (`helm template` locally) before applying

## Bad

```yaml
# values.yaml — only adds custom filter, kubernetes filter silently dropped
config:
  filters: |
    [FILTER]
        Name modify
        Match *
        Add cluster ${CLUSTER_NAME}
```

## Good

```yaml
config:
  filters: |
    [FILTER]
        Name                kubernetes
        Match               kube.*
        Merge_Log           On
        Keep_Log            Off
        K8S-Logging.Parser  On
        K8S-Logging.Exclude On

    [FILTER]
        Name modify
        Match *
        Add cluster ${CLUSTER_NAME}
```
