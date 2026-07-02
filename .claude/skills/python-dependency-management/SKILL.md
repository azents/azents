---
name: python-dependency-management
description: Guide for adding dependencies to Python projects. Uses the uv package manager, and version specifier rules differ by project type (apps/libs).
---

# Python Dependency Management

Use this guide to add Python dependencies correctly.

## Identify the project type

First identify the type of project you are changing:

- `python/apps/*`: application project
- `python/libs/*`: library project

## Version specifier rules

All projects use the `lowest-direct` resolution strategy. A specified version is the **minimum** version, so always specify the **latest available version**.

### Application projects (`python/apps/*`)

| Dependency type | Version specifier | Example |
| --- | --- | --- |
| Runtime dependency | Exact version (`==`) | `"fastapi==0.127.0"` |
| Dev dependency | Minimum version (`>=`) | `"pytest>=9.0.1"` |

**Why:**

- Runtime dependencies use exact versions for reproducible builds and predictable deployments.
- Dev dependencies do not affect production builds, so minimum versions are acceptable.

### Library projects (`python/libs/*`)

| Dependency type | Version specifier | Example |
| --- | --- | --- |
| All dependencies | Minimum version (`>=`) | `"pydantic>=2.12"` |

**Why:**

- Libraries should allow consuming apps to choose compatible versions flexibly.

## Dependency addition procedure

### 1. Inspect `pyproject.toml`

**Important:** Before adding a dependency, read the existing `pyproject.toml` file and check whether dependencies are grouped by comments:

- Look for groups such as `# Local dependencies` and `# External dependencies`.
- Follow the existing grouping pattern and place the new dependency in the appropriate section.

### 2. Move to the project directory

**Important:** Run `uv` commands from the subproject directory.

```bash
cd /path/to/azents/python/apps/{project-name}
# or
cd /path/to/azents/python/libs/{project-name}
```

### 3. Check existing versions

**Important:** Check whether the same dependency is already used by another project:

- Use the Glob tool to find other `pyproject.toml` files.
- Use the Grep tool to search for the package name.
- If the dependency is already used, use the **same version** to preserve monorepo consistency.

### 4. Check the latest version for new dependencies

Find the latest package version on PyPI:

- Use web search: `"{package-name} pypi latest version 2026"`.
- Or run `uv pip index versions {package-name}`.

### 5. Add the dependency

Use the version specifier that matches the project type:

**Application runtime dependency:**

```bash
uv add "{package-name}=={latest-version}"
```

**Application dev dependency:**

```bash
uv add --dev "{package-name}>={latest-version}"
```

**Library dependency:**

```bash
uv add "{package-name}>={latest-version}"
```

### 6. Clean up `pyproject.toml`

After adding the dependency, inspect `pyproject.toml` and verify that:

- The new dependency is in the appropriate commented section.
- If necessary, move it manually to match the existing structure, such as a local dependency section.

### 7. Verify

Confirm that the dependency was added correctly:

```bash
uv pip list | grep {package-name}
```

## Examples

### Inspecting `pyproject.toml` structure

```toml
[project]
dependencies = [
    # Local dependencies
    "az-common",

    # External dependencies
    "fastapi==0.127.0",
    "pydantic==2.12.4",
]
```

### Adding fastapi to an application

```bash
cd /path/to/azents/python/apps/azents
uv add "fastapi==0.127.0"
```

### Adding pytest as an application dev dependency

```bash
cd /path/to/azents/python/apps/azents
uv add --dev "pytest>=9.0.1"
```

### Adding pydantic to a library

```bash
cd /path/to/azents/python/libs/az-common
uv add "pydantic>=2.12"
```

## Notes

- ❌ Do not run `uv run` from the repository root.
- ✅ Always change to the subproject directory with an absolute path.
- ✅ Avoid relative paths.
- ✅ Check the latest version before adding a dependency.
- ✅ Use the version specifier that matches the project type.
- ✅ Preserve commented dependency grouping in `pyproject.toml`.
