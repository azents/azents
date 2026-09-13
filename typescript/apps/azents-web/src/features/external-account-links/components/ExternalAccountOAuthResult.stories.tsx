import { ExternalAccountOAuthResult } from "./ExternalAccountOAuthResult";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ExternalAccountOAuthResult,
} satisfies Meta<typeof ExternalAccountOAuthResult>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Connected = {
  args: {
    state: {
      type: "CONNECTED",
      provider: "slack",
      externalDisplayLabel: "Alex Morgan",
      providerTeamLabel: "Acme Slack",
    },
  },
} satisfies Story;

export const Cancelled = {
  args: {
    state: { type: "CANCELLED", provider: "discord" },
  },
} satisfies Story;

export const ProviderUnavailable = {
  args: {
    state: {
      type: "PROVIDER_UNAVAILABLE",
      provider: "slack",
      status: "incomplete",
    },
  },
} satisfies Story;

export const OwnershipConflict = {
  args: {
    state: {
      type: "FAILED",
      provider: "discord",
      reason: "conflict",
    },
  },
} satisfies Story;

export const ConfigurationChanged = {
  args: {
    state: {
      type: "FAILED",
      provider: "slack",
      reason: "configuration_changed",
    },
  },
} satisfies Story;

export const AuthenticationRequired = {
  args: {
    state: { type: "AUTH_REQUIRED" },
  },
} satisfies Story;

export const Mobile = {
  ...Connected,
  parameters: {
    viewport: { defaultViewport: "mobile1" },
  },
} satisfies Story;
