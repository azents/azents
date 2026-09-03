import { Box, rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RuntimeTerminalPanel } from "./RuntimeTerminalPanel";
import type { RuntimeTerminalContainerOutput } from "../containers/useRuntimeTerminalContainer";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};

const base: RuntimeTerminalContainerOutput = {
  projection: {
    state: "ready",
    reason_code: null,
    denied_scope: null,
    can_start_runtime: false,
    can_open_or_attach: true,
    terminal: null,
  },
  projectionLoading: false,
  presentation: "collapsed",
  connection: { type: "connected", shellLabel: "Shell" },
  replayTruncated: false,
  hasNewOutput: false,
  ctrlActive: false,
  altActive: false,
  hostRef: noop,
  onExpand: noop,
  onFocus: noop,
  onCollapse: noop,
  onReturnToDock: noop,
  onTerminate: noop,
  onRetry: noop,
  onToggleCtrl: noop,
  onToggleAlt: noop,
  onSoftwareKey: noop,
  onFocusKeyboard: noop,
  dockHeight: 260,
  onDockResizeStart: noop,
  onDockResizeBy: noop,
};

const meta = {
  component: RuntimeTerminalPanel,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(1200)}>
        <Box h="100dvh" style={{ display: "flex", alignItems: "flex-end" }}>
          <Box w="100%">
            <Story />
          </Box>
        </Box>
      </StorybookCanvas>
    ),
  ],
  args: {
    terminal: base,
    mobile: false,
    onStartRuntime: noop,
  },
} satisfies Meta<typeof RuntimeTerminalPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Collapsed: Story = {};

export const CollapsedWithNewOutput: Story = {
  args: { terminal: { ...base, hasNewOutput: true } },
};

export const Docked: Story = {
  args: { terminal: { ...base, presentation: "docked" } },
};

export const Focused: Story = {
  args: { terminal: { ...base, presentation: "focused" } },
};

export const Stopped: Story = {
  args: {
    terminal: {
      ...base,
      presentation: "docked",
      connection: { type: "idle" },
      projection: {
        state: "stopped",
        reason_code: "runtime_stopped",
        denied_scope: "runtime",
        can_start_runtime: true,
        can_open_or_attach: false,
        terminal: null,
      },
    },
  },
};

export const Starting: Story = {
  args: {
    terminal: {
      ...base,
      presentation: "docked",
      connection: { type: "connecting" },
      projection: {
        state: "starting",
        reason_code: "runtime_starting",
        denied_scope: "runtime",
        can_start_runtime: false,
        can_open_or_attach: false,
        terminal: null,
      },
    },
  },
};

export const ReconnectingWithTruncatedReplay: Story = {
  args: {
    terminal: {
      ...base,
      presentation: "docked",
      connection: { type: "reconnecting" },
      replayTruncated: true,
    },
  },
};

export const Exited: Story = {
  args: {
    terminal: {
      ...base,
      presentation: "docked",
      connection: { type: "exited" },
    },
  },
};

export const Revoked: Story = {
  args: {
    terminal: {
      ...base,
      presentation: "docked",
      connection: { type: "revoked" },
    },
  },
};

export const Error: Story = {
  args: {
    terminal: {
      ...base,
      presentation: "docked",
      connection: { type: "error" },
    },
  },
};

export const Unavailable: Story = {
  args: {
    terminal: {
      ...base,
      presentation: "docked",
      connection: { type: "idle" },
      projection: {
        state: "unavailable",
        reason_code: "runner_terminal_unsupported",
        denied_scope: "runner",
        can_start_runtime: false,
        can_open_or_attach: false,
        terminal: null,
      },
    },
  },
};

export const PolicyDenied: Story = {
  args: {
    terminal: {
      ...base,
      projection: {
        state: "unavailable",
        reason_code: "terminal_disabled",
        denied_scope: "agent",
        can_start_runtime: false,
        can_open_or_attach: false,
        terminal: null,
      },
    },
  },
};

export const RuntimeFree: Story = {
  args: {
    terminal: {
      ...base,
      projection: {
        state: "absent",
        reason_code: "runtime_free_agent",
        denied_scope: "runtime",
        can_start_runtime: false,
        can_open_or_attach: false,
        terminal: null,
      },
    },
  },
};

export const MobileFocused: Story = {
  args: {
    mobile: true,
    terminal: { ...base, presentation: "focused", ctrlActive: true },
  },
  parameters: {
    viewport: { defaultViewport: "mobile1" },
  },
};
