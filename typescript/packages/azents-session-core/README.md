# Session core

`@azents/session-core` owns the host-independent Session types and pure
projection/presentation functions used by the Main Web application. An
independently deployed web client can consume the same modules without importing
an application workspace.

Import the defining module directly:

```typescript
import { projectChatPresentationItems } from "@azents/session-core/toolActivityPresentation";
import { providerToolCallFromPayload } from "@azents/session-core/providerToolCallProjection";
import type { ChatMessage } from "@azents/session-core/types";
```

## Ownership

- `types` and `action`: existing Session wire, projection, and input types.
- `toolCallMerge`, `providerToolCallProjection`: canonical tool call/result
  projection, identity matching, attachments, and provider-neutral status.
- `toolActivityPresentation`: ordered transcript selection and Activity grouping.
- `pendingMailboxState`: pending envelope reduction, promotion suppression,
  deletion state, and display order.
- `chatLiveHistoryProjection`, `toolCallVisibility`, `liveRetryVisibility`:
  existing live/durable and timeline display selection.
- `toolInputPresentation`, `v4aPatchPresentation`,
  `providerToolCallPresentation`: display-only input parsing, patch structure,
  and provider tool labels.

The package has no runtime dependency on React, Next.js, the DOM, native APIs,
cookies, transport, or persistence. The generated Public API client supplies
types only through `@azents/public-client/types`, without loading its fetch SDK.
Typechecking does not include DOM libraries. Package boundary tests
keep source imports inside this package or the type-only Public API contract.

The web host still owns authentication, network connections, resync orchestration,
scroll/viewport effects, React components, and syntax-highlighter-dependent
specialized tool rendering. In particular, this extraction does **not** add
multi-server state, a native bridge, mobile-web hosting, new unknown-response
behavior, or a protocol compatibility policy.

## Behavior contracts

Existing behavioral tests move with their production implementation. A
consumer-level test imports the package through its exports and composes tool
projection, Activity selection, and pending input reduction without a web host.
These tests are not a substitute for browser E2E or native-device acceptance.

From `typescript/`:

```console
pnpm run generate
pnpm --filter @azents/session-core test
pnpm --filter @azents/session-core typecheck
pnpm --filter @azents/session-core lint
pnpm --filter @azents/session-core format:check
pnpm --filter @azents/web test
```

The existing required TypeScript CI lane runs the package tests. Production web
builds consume the TypeScript source exports, following the repository's
workspace model; there is no separate package publication or deployment.
