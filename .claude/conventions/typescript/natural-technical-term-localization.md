---
title: Natural technical-term localization
impact: MEDIUM
tags: typescript, i18n, localization, ux
---

## Rule

Translate user-facing messages for natural meaning in each locale, not by mechanically translating every English word. Keep established product and industry terms such as Runtime, Profile, Kubernetes, Docker, Pod, PVC, Requests, Limits, CIDR, CPU, and memory in their recognizable form when a localized substitute would be less precise or less familiar.

Translate the surrounding sentence, explanation, and action into idiomatic language so the retained technical term is clear in context. Do not expose internal enum values, field paths, or reason codes as a substitute for localized product copy; render a human-readable label and explanation, with the raw value available only as secondary technical detail when useful.

Keep translation keys structurally synchronized across every supported locale.

## Examples

- Prefer Korean `Kubernetes Pod의 CPU Requests와 Limits` over a forced word-for-word translation that hides the Kubernetes concepts.
- Prefer Korean `Docker 이미지 빌드` over translating the Docker product name.
- Render `provider_module_unsupported` as an explanation of what the current Runtime Provider cannot support, rather than showing the enum as the primary error message.
