---
name: python-dependency-update
description: "Update dependencies in Python projects. Use for Dependabot security alerts, package upgrades, and transitive dependency updates. Use when: (1) resolving Dependabot security alerts, (2) updating a specific package, (3) patching a security vulnerability."
---

# Python Dependency Update

Workflow for updating dependencies in the Python monorepo, which uses uv workspaces.

## Preparation

Run uv commands from the relevant subproject directory.

```bash
cd /path/to/azents/python/apps/{project-name}
# or
cd /path/to/azents/python/libs/{project-name}
```

## Update flow

### Step 1: Identify the target

Determine whether the package to update is a direct dependency or a transitive dependency.

```bash
# Check whether it is explicitly listed in pyproject.toml
grep -r "{package-name}" python/apps/*/pyproject.toml python/libs/*/pyproject.toml

# Check the current version in the lockfile
grep -A2 'name = "{package-name}"' python/apps/{project}/uv.lock
```

### Step 2: Run the update

#### Case A: Direct dependency (present in pyproject.toml)

Edit the version in `pyproject.toml`, then refresh the lockfile.

Version specifier rules are the same as in the `python-dependency-management` skill:

- **Runtime dependencies in apps (`apps/*`)**: exact version (`==`)
- **Dev dependencies in apps (`apps/*`)**: minimum version (`>=`)
- **All dependencies in libraries (`libs/*`)**: minimum version (`>=`)

```bash
# Edit pyproject.toml directly with the Edit tool.
# App example: "aiohttp==3.9.0" → "aiohttp==3.11.12"
# Library example: "aiohttp>=3.9.0" → "aiohttp>=3.11.12"

cd /path/to/azents/python/apps/{project-name}
uv lock
```

If several projects use the same package, update every relevant `pyproject.toml` together.

#### Case B: Transitive dependency (not present in pyproject.toml)

The `lowest-direct` resolution strategy does not pin transitive dependencies. Transitive dependencies usually resolve to the latest compatible version. Update only the lockfile:

```bash
cd /path/to/azents/python/apps/{project-name}
uv lock --upgrade-package {package-name}
```

Confirm that the lockfile version changed:

```bash
grep -A2 'name = "{package-name}"' uv.lock
```

If `--upgrade-package` does not update the dependency, the cause is not `lowest-direct`; check these possibilities:

1. **Lockfile preference**: uv prefers the existing lockfile version. Add an explicit version constraint to force the target:
   ```bash
   uv lock --upgrade-package '{package-name}>={target-version}'
   ```
2. **Parent dependency constraint**: another package sets an upper bound such as `{package-name}<X.Y`.
3. **Compatibility conflict**: required version ranges from multiple packages do not overlap.

#### Case C: Another dependency blocks the update

If a parent dependency pins an old version, `uv lock --upgrade-package` alone will not solve it.

1. Find which package requires the dependency:

```bash
# Search uv.lock for entries that list the package as a dependency
grep -B10 '{package-name}' uv.lock
```

2. Update the parent dependency first, using Case A or Case B.

3. If it still cannot be resolved, stop and explain clearly:
   - Which parent package constrains the version
   - Whether the latest version of that parent package still has the constraint
   - Options the user can evaluate, such as replacing the parent package or opening an upstream issue

### Step 3: Verify

```bash
# Confirm the target version in the lockfile
grep -A2 'name = "{package-name}"' uv.lock

# Run type checking
cd /path/to/azents/python/apps/{project-name}
uv run pyright
```

## Handling Dependabot security alerts in batches

When processing multiple alerts at once:

```bash
# List open alerts
gh api repos/{owner}/{repo}/dependabot/alerts \
  --jq '.[] | select(.state=="open") | {
    number,
    severity: .security_advisory.severity,
    package: .security_vulnerability.package.name,
    patched: .security_vulnerability.first_patched_version.identifier
  }'
```

Group alerts for the same package and target the highest patched version among them.

A Python package may be used by several subprojects, so inspect every relevant lockfile.

## Notes

- Do not use `[tool.uv.override]`; forced versions unrelated to dependency constraints are hard to track.
- Do not edit `uv.lock` manually; always refresh it with uv commands.
- Do not run uv commands from the repository root; run them from the subproject directory.
- After the update, run `git diff --stat` and confirm no unrelated files changed.
- Tell the user when a major version upgrade may include breaking changes.
