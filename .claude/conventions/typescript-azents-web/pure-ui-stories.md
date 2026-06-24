---
title: When adding or changing a pure state UI component in azents-web, add colocated Storybook stories for its meaningful states using static fixtures instead of live API calls.
---

# Pure UI Stories

Pure UI components are easiest to review when their states are visible outside full-page flows.

- ALWAYS add or update a colocated `*.stories.tsx` file when a azents-web component can render from props, static fixtures, or small callbacks.
- ALWAYS cover meaningful states such as loading, empty, error, streaming, disabled, read-only, and completed when those states exist.
- AVOID calling tRPC, WebSocket, browser navigation, or backend endpoints from stories; extract a prop-driven component or use static fixtures instead.
- AVOID story-only barrel files. Import directly from the file that defines the component.

## Without Storybook

- `ChatInput.tsx` exists, but `ChatInput.stories.tsx` does not.
- Disabled, read-only, pending upload, and command-blocked states can only be checked by running the chat page.

## With Storybook

```tsx
export const Disabled = {
  args: {
    disabled: true,
    value: "Waiting for the current turn to finish",
  },
};
```
