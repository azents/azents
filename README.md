# Azents

Managed agents, inside your cloud.

Azents is an open-source control plane for remote agent runtimes. It keeps
sessions, tools, permissions, and execution state close to your repositories and
private network, so managed agents can run where the work actually happens.

Learn more at [azents.io](https://azents.io).

## Why Azents

- **Remote runs that keep going**: Long-running agent work should not depend on a
  laptop tab, SSH session, or local process staying alive.
- **Runtime in your infrastructure**: Run managed agent sessions next to the
  workspace, services, credentials, and network boundaries they need.
- **Self-hosted control**: Keep ownership of deployment, policy, observability,
  and data residency while using an open-source agent control plane.
- **Team-visible work**: Track tool calls, command output, diffs, blockers, and
  handoffs from one shared system instead of a single developer machine.

## What Is In This Repository

This repository contains the Azents backend, runtime providers, web apps, API
clients, documentation, test fixtures, and Helm packaging.

The main implementation areas are:

- `python/apps/azents/`: API server, workers, scheduler, and domain logic
- `python/apps/azents-runtime-*`: runtime runner and provider packages
- `typescript/apps/azents-web/`: Azents web application
- `typescript/apps/azents-site/`: public Azents website
- `docs/azents/`: ADRs, design notes, and living specs
- `infra/charts/azents/`: Helm chart
- `proto/azents/`: runtime control protobuf definitions

## Links

- Website: [azents.io](https://azents.io)
- Documentation: [docs/azents](./docs/azents/INDEX.md)
- Development guide: [DEVELOPMENT.md](./DEVELOPMENT.md)
- Trademark policy: [TRADEMARKS.md](./TRADEMARKS.md)

## License

Azents source code is licensed under the [MIT License](./LICENSE).

The Azents name, logo, icons, and other brand assets are not licensed under the
MIT License. You may not use them in a way that suggests you are the official
Azents project, an official Azents cloud or hosting provider, or endorsed by
Azents without written permission. See [TRADEMARKS.md](./TRADEMARKS.md) for
details.
