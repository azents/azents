---
title: Put Toolkit usage guidance in tool descriptions and schemas; reserve static prompts for pre-discovery rules and dynamic prompts for unavoidable changing state.
---

# Keep Toolkit Prompts Minimal

- PREFER tool descriptions and schemas, tool results or query tools, typed turn context or compaction, then Tool Search.
- Use a static prompt only for information required before tool discovery or an immutable session-wide judgment or safety boundary.
- Use a dynamic prompt only when changing state must be noticed automatically and no tool, typed context, transcript, or compaction path can provide it.
- Keep unavoidable prompts minimal and stable; exclude duplicated tool documentation and non-actionable operational diagnostics.
