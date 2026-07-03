# Conventions Area

This directory manages convention body files.

## Index Generation

- You may add or edit body files under `.claude/conventions/**`.
- The pre-commit hook generates `.claude/rules/*-conventions.md` index files.
- Do not manually run `python scripts/generate-conventions-index.py` to generate indexes.
- Do not install `python-frontmatter` in the repository root or an ad hoc Python environment to run the generator directly. The pre-commit hook's isolated environment owns this dependency.
- After writing a convention body, commit it and let pre-commit regenerate the index. Accept the generated index diff from the pre-commit result.
