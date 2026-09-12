import { ExternalAccountLinkConfirmation } from "./ExternalAccountLinkConfirmation";
import type {
  ExternalAccountCandidate,
  ExternalAccountLinkConfirmationState,
  ExternalAccountLinkOrigin,
} from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ExternalAccountLinkConfirmation,
} satisfies Meta<typeof ExternalAccountLinkConfirmation>;

export default meta;

type Story = StoryObj<typeof meta>;

const origin: ExternalAccountLinkOrigin = {
  id: "origin-1",
  workspaceName: "Product Studio",
  workspaceHandle: "product-studio",
  provider: "slack",
  providerTeamLabel: "Acme Slack",
  externalDisplayLabel: "Alex Morgan",
  expiresAt: "2026-09-12T05:00:00.000Z",
  state: "open",
  candidateCount: 1,
  candidateLimit: 5,
  returnUrl: "https://app.slack.com/client/team/channel",
};

const pendingCandidate: ExternalAccountCandidate = {
  id: "candidate-1",
  code: "F7M2-K9Q4-W6RD",
  expiresAt: "2026-09-12T05:00:00.000Z",
  status: "pending_provider_proof",
};

const handlers = {
  onCreateCandidate: (): void => {},
  onCheckStatus: (): void => {},
  onConfirmLink: (): void => {},
  onStartFresh: (): void => {},
  onCancel: (): void => {},
  onSwitchAccount: (): void => {},
  onReturn: (): void => {},
  onRetry: (): void => {},
};

function readyState(
  candidate: ExternalAccountCandidate | null,
): ExternalAccountLinkConfirmationState {
  return {
    type: "READY",
    origin,
    accountEmail: "alex@example.com",
    candidate,
    action: { type: "IDLE", error: null },
  };
}

export const BeforeCode = {
  args: {
    state: readyState(null),
    ...handlers,
  },
} satisfies Story;

export const CodeCreated = {
  args: {
    state: readyState(pendingCandidate),
    ...handlers,
  },
} satisfies Story;

export const ProviderVerified = {
  args: {
    state: readyState({
      ...pendingCandidate,
      status: "provider_verified",
    }),
    ...handlers,
  },
} satisfies Story;

export const MembershipRequired = {
  args: {
    state: {
      type: "READY",
      origin,
      accountEmail: "alex@example.com",
      candidate: null,
      action: { type: "IDLE", error: "membership_required" },
    } satisfies ExternalAccountLinkConfirmationState,
    ...handlers,
  },
} satisfies Story;

export const Connected = {
  args: {
    state: {
      type: "CONNECTED",
      origin,
      accountEmail: "alex@example.com",
      workspaceName: origin.workspaceName,
      provider: origin.provider,
      externalDisplayLabel: origin.externalDisplayLabel,
      returnUrl: origin.returnUrl,
    } satisfies ExternalAccountLinkConfirmationState,
    ...handlers,
  },
} satisfies Story;

export const Expired = {
  args: {
    state: {
      type: "ORIGIN_UNAVAILABLE",
      reason: "expired",
      origin,
      accountEmail: "alex@example.com",
    } satisfies ExternalAccountLinkConfirmationState,
    ...handlers,
  },
} satisfies Story;

export const ElevationMethodsLoading = {
  args: {
    state: {
      type: "ELEVATION_LOADING",
      origin,
      accountEmail: "alex@example.com",
      action: "create_candidate",
    } satisfies ExternalAccountLinkConfirmationState,
    ...handlers,
  },
} satisfies Story;

export const ElevationMethodsError = {
  args: {
    state: {
      type: "ELEVATION_ERROR",
      origin,
      accountEmail: "alex@example.com",
      action: "confirm_candidate",
      message: "Verification methods are unavailable.",
    } satisfies ExternalAccountLinkConfirmationState,
    ...handlers,
  },
} satisfies Story;

export const MobileCode = {
  ...CodeCreated,
  parameters: {
    viewport: { defaultViewport: "mobile1" },
  },
} satisfies Story;
