---
title: "Azents Documentation"
---
# Azents Documentation

Document frontmatter is the source of truth for validation and discovery. This
landing page is intentionally stable and does not contain a generated list of
individual documents.

## Browse by Purpose

- [Documentation rules and structure](./AGENTS.md)
- Current behavior:
  - [Domain Specs](./spec/domain/)
  - [Flow Specs](./spec/flow/)
- Development snapshots:
  - [Requirements](./requirements/)
  - [Architecture Decision Records](./adr/)
  - [Design records](./design/)
- Working records:
  - [Plans](./plans/)
  - [Notes](./notes/)
  - [Issues](./issues/)

## Query the Catalog

Use the frontmatter-backed catalog instead of editing or reading a generated
repository-wide index:

```console
python scripts/docs_catalog.py search external-channel
python scripts/docs_catalog.py related --code-path python/apps/azents/src/azents/engine
python scripts/docs_catalog.py snapshot channel-260831
python scripts/docs_catalog.py list --type spec --spec-type flow
python scripts/docs_catalog.py list --tag external-channel
python scripts/docs_catalog.py stale --before 2026-09-01
python scripts/docs_catalog.py validate
```
