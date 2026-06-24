---
title: "Use Mermaid code blocks for all diagrams in markdown documents (architecture, flow, sequence) — never ASCII art."
---

# Diagrams in Mermaid

ASCII boxes look fine in a terminal but rot the moment fonts shift, columns drift, or someone renders the doc in a non-monospace context. Mermaid renders the same everywhere.

- ALWAYS use Mermaid code blocks for architecture diagrams, flowcharts, sequence diagrams, ERDs in `*.md` files
- AVOID ASCII art for diagrams (boxes drawn with `|`, `+`, `-`, `→`)

## Bad

````markdown
```
┌──────────┐     ┌──────────┐
│  Client  │ ──> │  Server  │
└──────────┘     └──────────┘
```
````

## Good

````markdown
```mermaid
flowchart LR
    Client --> Server
```
````
