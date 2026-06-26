---
title: "Write source-code comments and docstrings in English — applies to module/class/function docstrings and inline comments across every language."
---

# Comments and Docstrings in English

Git-tracked artifacts in Azents are written in English. Comments and docstrings are part of the maintained source artifact and should follow the same language rule as code-facing text.

- ALWAYS write comments and docstrings in English.
- Use clear technical terms consistently with surrounding code.
- Applies to: module docstrings, class docstrings, function docstrings, inline comments — in Python, TypeScript, Terraform, YAML, and all other languages.

## Bad

```python
def start_workflow(input: Input) -> Output:
    """<non-English docstring>"""
    # <non-English comment>
```

## Good

```python
def start_workflow(input: Input) -> Output:
    """Start a workflow with the given input."""
    # Validate the input first
```
