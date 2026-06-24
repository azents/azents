---
title: "Always pin third-party GitHub Actions to a full 40-char commit SHA with the version as a trailing comment — never use `@v1` / `@main` / `@master`, which can move to malicious code on a tag retag."
---

# Pin GitHub Actions to Commit SHA

A floating `@v6` tag can be moved by the action's owner (or a compromised account) to point at malicious code. A 40-char SHA is immutable; the trailing comment makes the intended version readable.

- Format: `uses: owner/action@<full-sha-40>  # v<version>`
- Look up the SHA from the action's release page on GitHub when adding or upgrading
- Update Dependabot's `package-ecosystem: github-actions` to manage these bumps

## Bad

```yaml
- uses: actions/checkout@v6
- uses: actions/setup-python@main
```

## Good

```yaml
- uses: actions/checkout@8e8c483db84b4bee98b60c0593521ed34d9990e8 # v6.0.1
- uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
```
