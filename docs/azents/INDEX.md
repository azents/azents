---
title: "Azents Documentation"
---
# Azents Documentation

Current-system knowledge lives in the LLM-maintained Spec Wiki. Reference
documents retain their separate development-snapshot lifecycles; they are not
another wiki or a generated catalog.

## Browse by Purpose

- [Documentation rules and structure](./AGENTS.md)
- [Spec Wiki](./spec/index.md) — current behavior, concepts and connected flows.
  - [Wiki maintenance](./spec/AGENTS.md) — ingest, query, semantic lint and evidence.
- Development snapshots:
  - [Requirements](./requirements/)
  - [Architecture Decision Records](./adr/)
  - [Design records](./design/)
- Working records:
  - [Plans](./plans/)
  - [Notes](./notes/)
  - [Issues](./issues/)

## Find and Verify Knowledge

Start with the wiki's question-led index and follow the owning concepts and their
connections. Use ordinary text, filename and symbol search when links are
insufficient. Find a reference snapshot by its shared basename under Requirements,
ADRs and Designs. Agents determine relevance from behavior, not file-path matches.

Mechanical validation remains independent from semantic discovery:

```console
python scripts/validate_docs.py
python -m unittest scripts.tests.test_validate_docs
```
