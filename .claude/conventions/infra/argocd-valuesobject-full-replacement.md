---
title: "ArgoCD `Application.spec.source.helm.valuesObject` is opaque to Kustomize — SMP patches REPLACE the entire object, not deep-merge. A production-overlay patch on `valuesObject` must include every value from the base."
---

# `valuesObject` Full Replacement on Patch

Most YAML keys deep-merge under SMP. `valuesObject` is opaque (it's an `extension` field), so patching it replaces the whole map. The result is silent dropping of base values.

- When patching `spec.source.helm.valuesObject` in an overlay, copy all base values into the patch
- Or split per-environment values into a separate `valuesObject` block (and accept that the base then has none)
- Symptom: deployed Helm release has only the keys from the overlay, base values vanished

## Bad

```yaml
# overlays/production/patch.yaml
spec:
  source:
    helm:
      valuesObject:
        replicas: 5    # only this — base's image, resources, etc. are dropped
```

## Good

```yaml
# overlays/production/patch.yaml — copy ALL base values
spec:
  source:
    helm:
      valuesObject:
        image: ghcr.io/.../api:abc
        resources:
          limits: { cpu: "1", memory: "2Gi" }
        replicas: 5
```
