---
title: "Write long multi-line prompt text as triple-quoted strings for readability; use `textwrap.dedent()` for inline/nested prompt definitions, while top-level constants may use plain triple quotes when no indentation needs stripping."
---

# Triple-Quoted Prompt Strings and `dedent()`

LLM prompts are model-visible source text, so their Python representation should stay readable in review and should not accidentally include indentation from surrounding code.

- ALWAYS write long multi-line prompt text with triple-quoted strings instead of string concatenation or `"\n".join(...)` lists.
- Use `textwrap.dedent(...)` for inline or nested prompt definitions where source indentation would otherwise be included in the prompt.
- Top-level prompt constants may use plain triple-quoted strings when they start at column 0 and do not need indentation stripped.
- If the prompt intentionally contains long natural-language lines, append `# noqa: E501` on the assignment line rather than splitting the prompt into unreadable fragments.

## Bad

```python
prompt = "\n".join(
    [
        "You are an assistant. Given the previous conversation and current state,",
        "produce a handoff summary that preserves next actions.",
    ]
)
```

## Good: top-level constant

```python
SUMMARY_PROMPT = """You are an assistant.
Given the previous conversation and current state, produce a handoff summary that preserves next actions.
"""  # noqa: E501
```

## Good: inline or nested prompt

```python
from textwrap import dedent

prompt = dedent(  # noqa: E501
    f"""\
    You are an assistant.
    Given {context}, produce a handoff summary that preserves next actions.
    """
)
```
