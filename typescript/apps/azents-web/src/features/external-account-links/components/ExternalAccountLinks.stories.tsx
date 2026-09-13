import { ExternalAccountLinks } from "./ExternalAccountLinks";
import type {
  ExternalAccountLinkItem,
  ExternalAccountLinksState,
  ExternalAccountProviderAvailability,
} from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ExternalAccountLinks,
} satisfies Meta<typeof ExternalAccountLinks>;

export default meta;

type Story = StoryObj<typeof meta>;

const providersReady: ExternalAccountProviderAvailability[] = [
  { provider: "slack", status: "ready", available: true },
  { provider: "discord", status: "ready", available: true },
];

const slackLink: ExternalAccountLinkItem = {
  id: "link-slack",
  provider: "slack",
  providerTeamLabel: "Acme Slack",
  externalDisplayLabel: "Alex Morgan",
  linkedAt: "2026-09-13T04:30:00.000Z",
};

const discordLink: ExternalAccountLinkItem = {
  id: "link-discord",
  provider: "discord",
  providerTeamLabel: null,
  externalDisplayLabel: "alex_dev",
  linkedAt: "2026-09-13T03:15:00.000Z",
};

const handlers = {
  onRequestDisconnect: (): void => {},
  onCancelDisconnect: (): void => {},
  onConfirmDisconnect: (): void => {},
  onRetry: (): void => {},
};

export const MultipleProviders = {
  args: {
    state: {
      type: "READY",
      providers: providersReady,
      links: [slackLink, discordLink],
      disconnect: { type: "IDLE" },
    } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const Empty = {
  args: {
    state: {
      type: "READY",
      providers: providersReady,
      links: [],
      disconnect: { type: "IDLE" },
    } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const ProviderUnavailable = {
  args: {
    state: {
      type: "READY",
      providers: [
        { provider: "slack", status: "ready", available: true },
        { provider: "discord", status: "incomplete", available: false },
      ],
      links: [slackLink],
      disconnect: { type: "IDLE" },
    } satisfies ExternalAccountLinksState,
    ...handlers,
  },
} satisfies Story;

export const DisconnectConfirmation = {
  args: {
    state: {
      type: "READY",
      providers: providersReady,
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

export const DisconnectFailure = {
  args: {
    state: {
      type: "READY",
      providers: providersReady,
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
  ...MultipleProviders,
  parameters: {
    viewport: { defaultViewport: "mobile1" },
  },
} satisfies Story;
