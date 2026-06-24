---
title: "Write all comments and docstrings in Korean (technical terms in English) — applies to module/class/function docstrings and inline comments across every language."
---

# Comments and Docstrings in Korean

Source-code comments are read by the team, and the team works in Korean. User-facing text is the opposite — see `user-facing-text-in-english.md`.

- ALWAYS write comments and docstrings in Korean (한글)
- Keep technical terms in English when the English term is clearer (workflow, activity, handler, session, commit, etc.)
- Applies to: module docstrings, class docstrings, function docstrings, inline comments — in Python, TypeScript, Terraform, YAML, all languages

## Bad

```python
def start_workflow(input: Input) -> Output:
    """Start a workflow with the given input."""
    # Validate the input first
```

## Good

```python
def start_workflow(input: Input) -> Output:
    """주어진 입력으로 workflow 를 시작한다."""
    # 먼저 입력을 검증한다
```
