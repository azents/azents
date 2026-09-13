import { ExternalAccountLinks } from "./ExternalAccountLinks";
import type {
  ExternalAccountLinkItem,
  ExternalAccountLinksState,
} from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ExternalAccountLinks,
} satisfies Meta<typeof ExternalAccountLinks>;

export default meta;

type Story = StoryObj<typeof meta>;

const slackLink: ExternalAccountLinkItem = {
  id: "link-slack",
  accountContextLabel: "Acme Slack",
  provider: "slack",
  providerTeamLabel: "Acme Slack",
  externalDisplayLabel: "Alex Morgan",
  linkedAt: "2026-09-12T04:30:00.000Z",
  status: "active",
};

const inactiveDiscordLink: ExternalAccountLinkItem = {
  id: "link-discord",
  accountContextLabel: "Discord",
  provider: "discord",
  providerTeamLabel: "Azents Builders",
  externalDisplayLabel: "alex_dev",
  linkedAt: "2026-09-11T22:15:00.000Z",
  status: "inactive",
};

const handlers = {
  onRequestDisconnect: (): void => {},
  onCancelDisconnect: (): void => {},
  onConfirmDisconnect: (): void => {},
  onRetry: (): void => {},
};

export const Loaded = {
  args: {
    state: {
      type: "READY",
      links: [slackLink, inactiveDiscordLink],
      disconnect: { type: "IDLE" },
    } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const Empty = {
  args: {
    state: {
      type: "READY",
      links: [],
      disconnect: { type: "IDLE" },
    } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const DisconnectConfirmation = {
  args: {
    state: {
      type: "READY",
      links: [slackLink],
      disconnect: {
        type: "CONFIRMING",
        link: slackLink,
        error: null,
      },
    } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const DisconnectConflict = {
  args: {
    state: {
      type: "READY",
      links: [slackLink],
      disconnect: {
        type: "CONFIRMING",
        link: slackLink,
        error: "busy",
      },
    } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const Loading = {
  args: {
    state: { type: "LOADING" } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const Error = {
  args: {
    state: {
      type: "ERROR",
      message: "External account service is unavailable.",
    } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const ElevationMethodsLoading = {
  args: {
    state: {
      type: "ELEVATION_LOADING",
      link: slackLink,
    } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const ElevationMethodsError = {
  args: {
    state: {
      type: "ELEVATION_ERROR",
      link: slackLink,
      message: "Verification methods are unavailable.",
    } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const Mobile = {
  ...Loaded,
  parameters: {
    viewport: { defaultViewport: "mobile1" },
  },
} satisfies Story;
