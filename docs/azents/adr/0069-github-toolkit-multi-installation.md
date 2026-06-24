---
title: "ADR-0069: GitHub Toolkit Multi-Installation Routing"
created: 2026-06-21
tags: [backend, engine, frontend, security]
---

# ADR-0069: GitHub Toolkit Multi-Installation Routing

## Context

GitHub App credentials in the GitHub Toolkit previously selected one installation. That was enough when an agent worked in one organization, but coding agents often need to work across repositories owned by different organizations, such as `azents/*` and `hardtack/*`, in the same runtime session.

A GitHub App installation token is scoped to one GitHub App installation. It cannot access repositories outside that installation's account and repository selection. Therefore a single `GH_TOKEN` or a single MCP bearer token cannot represent multiple organization installations at once.

GitHub App installation metadata can be resolved from App credentials and an installation ID by calling GitHub's installation endpoint. Platform App OAuth already returns user-accessible installations with account login metadata, which Azents stores in `github_user_installations` for ownership checks.

## Decision

### ADR-0069-D1 — Store GitHub App credentials as a list of installation targets

For `github_app` and `github_app_platform`, store `installations[]` instead of one `installation_id`. Each target records:

- `installation_id`
- `account_login`
- `account_type`
- `account_avatar_url`

The account login is treated as the repository owner routing key. Platform App creation validates every selected installation against the current user's synced `github_user_installations` rows.

### ADR-0069-D2 — Route MCP tools by per-installation tool prefix

A multi-installation GitHub Toolkit creates one lazy MCP binding per installation. Each binding exchanges an installation token independently and exposes the same GitHub MCP toolset with an installation-specific prefix based on `account_login`, for example:

- `azents__get_file_contents`
- `hardtack__get_file_contents`

The outer ToolkitConfig slug prefix still applies, so the final model-visible name remains namespace-safe, for example `github__azents__get_file_contents`.

### ADR-0069-D3 — Route runtime shell credentials by repository owner

When runtime environment injection is enabled, multi-installation credentials expose:

- `GITHUB_INSTALLATION_MAP` — owner login to installation/env metadata
- `GITHUB_TOKEN_INSTALLATION_<installation_id>` — installation token per target

The runtime image's Git credential helper reads the repository owner from the credential protocol `path` and chooses the matching token for Git HTTPS operations. GitHub CLI commands must select an installation token explicitly, for example `GH_TOKEN=$GITHUB_TOKEN_INSTALLATION_<installation_id> gh pr create ...`.

Single-installation credentials also keep `GH_TOKEN` and `GITHUB_TOKEN` for existing GitHub CLI behavior. Multi-installation credentials do not install or rely on a custom `gh` wrapper.

## Considered Options

### Add `installation_id` as a parameter to every GitHub MCP tool

Rejected. This would require mutating MCP tool schemas and then intercepting calls to switch bearer tokens at call time. It also asks the model to pass a low-level installation identifier on every call, increasing error risk.

### Create separate user-visible ToolkitConfigs for each installation

Rejected as the primary model. It works with existing prefixing, but it spreads one conceptual GitHub connection across multiple configs and cannot solve shell token routing without additional helper logic.

### Use one environment variable token

Rejected for multi-installation credentials. A single token silently limits shell work to one installation and makes cross-organization cloning or pushing unreliable.

### Install a custom `gh` wrapper in the runtime image

Rejected. The Kubernetes provider can control the runtime image, but other runtime providers may not. Tool-specific CLI wrappers are therefore not portable as a default platform contract. Explicit command-level environment selection is simpler and works in every runtime that receives the injected environment variables.

## Consequences

- GitHub App credentials are no longer modeled as a single installation.
- Tool names become longer but route unambiguously by organization/account owner.
- Runtime shell credential routing depends on repository owner matching `account_login`.
- Selected-repository installations can still fail for repositories outside the installation's allowed repository set; GitHub remains the source of truth for that authorization failure.
- Existing single-installation behavior is represented as a one-element installation list.
