---
title: "Use Mermaid for explanatory diagrams of relationships, topology, flow, time, state, or ER structure; keep compact notation and literal shapes in text."
---

# Mermaid for Diagrams, Text for Notation

Choose the representation by the block's communicative role, not by graph complexity or the mere presence of arrows.

- USE Mermaid when a block is an explanatory architecture, topology, process, sequence, state, or ER diagram
- KEEP compact stage chains, precedence summaries, stacked branch lists, directory or file trees, UI/CLI/output examples, and record or data shapes in text, lists, tables, or tree notation
- A simple relationship diagram may still be Mermaid; complexity is not a requirement
- DO NOT expand compact notation into a one-node-per-label flowchart unless the visual layout adds meaning such as branching, grouping, concurrency, cycles, or distinct actors

## Examples

- Diagram: a Client-to-Server architecture relationship belongs in Mermaid
- Notation: `research → requirements → design → implementation` belongs in compact text
