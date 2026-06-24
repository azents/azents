---
title: "Kustomize Strategic Merge Patch (SMP) namespace MUST match the base resource exactly — base has no namespace then patch must have none either; base has one then patch must repeat it. Mismatch raises `no resource matches strategic merge patch`."
---

# Kustomize SMP Namespace Must Match Base

`kustomize` matches a patch to a base by `(group, version, kind, name, namespace)`. A patch that adds or omits the namespace doesn't find its target and fails the build with a confusing error.

- ALWAYS check the base manifest's `metadata.namespace` and replicate it (or its absence) in the SMP patch
- This applies to all ArgoCD Applications, Deployments, ConfigMaps, Secrets

## Bad

```yaml
# base/deployment.yaml has no metadata.namespace
# overlays/production/patch.yaml adds one — kustomize cannot match
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: production   # base has no namespace → mismatch
```

## Good

```yaml
# base has no namespace → patch has no namespace
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 5
```
