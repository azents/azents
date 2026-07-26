---
name: typescript-dependency-tree-analysis
description: Analyze TypeScript dependency paths and version constraints in the Azents pnpm workspace. Use when a transitive npm dependency will not update, a security advisory requires finding the constraining parent, or an agent must determine whether a patched version is resolvable without pnpm overrides.
---

# TypeScript Dependency Tree Analysis

Run commands from `typescript/`.

## 1. Classify the dependency

```bash
grep -RIn --include='package.json' '"<package>"' .
pnpm why <package> --recursive --long
pnpm list <package> --recursive --depth Infinity
```

- A package in a workspace `package.json` is direct for that workspace.
- Otherwise, follow every `pnpm why` path upward until reaching a direct dependency.
- Distinguish runtime, development, optional, and peer paths before choosing a parent to update.

## 2. Try normal lock resolution

```bash
pnpm update <package> --recursive
pnpm why <package> --recursive --long
```

Confirm the resolved versions in `pnpm-lock.yaml` and with `pnpm why`. Do not add `overrides` unless the requester explicitly requires one.

## 3. Find the blocking parent

When the target remains below the required version:

```bash
pnpm outdated <direct-parent> --recursive --format json
pnpm view <parent>@<current-version> dependencies optionalDependencies peerDependencies --json
pnpm view <parent>@<candidate-version> dependencies optionalDependencies peerDependencies --json
```

For each reverse path:

1. Identify the nearest parent whose declared range excludes the target version.
2. Find the nearest direct workspace dependency that introduces that parent.
3. Check newer releases from the constraining parent upward until a release widens the range.
4. Update the direct dependency or parent through normal package resolution:

```bash
pnpm update <direct-parent>@<compatible-version> --recursive
```

Use `--latest` only when intentionally accepting a version outside the current manifest range. Review major-version release notes before doing so.

## 4. Stop when no compatible path exists

Do not edit `pnpm-lock.yaml` manually and do not force the target with an override. Stop and report:

- requested target and patched version
- every workspace-to-target dependency path
- the exact parent range that excludes the target
- parent and direct-dependency candidate versions checked
- why each candidate remains incompatible
- viable upstream options, such as waiting for a parent release, replacing the direct dependency, or accepting an explicit requester-approved override

## 5. Verify

```bash
pnpm install --frozen-lockfile
pnpm why <package> --recursive --long
pnpm run format
pnpm run lint
pnpm run typecheck
```

Run affected application tests or builds when the updated parent can change runtime behavior.
