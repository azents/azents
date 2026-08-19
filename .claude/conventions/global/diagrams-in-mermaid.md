---
title: "Use Mermaid for architecture, flow, sequence, and relationship diagrams in Markdown; keep ASCII directory trees as text."
---

# Diagrams in Mermaid

ASCII boxes look fine in a terminal but rot the moment fonts shift, columns drift, or someone renders the doc in a non-monospace context. Mermaid renders the same everywhere.

- ALWAYS use Mermaid code blocks for architecture diagrams, flowcharts, sequence diagrams, ERDs in `*.md` files
- KEEP directory trees as fenced text using tree characters such as `├──` and `└──`
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
