import { SignupTokenAdminView } from "./SignupTokenAdminView";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};

const meta = {
  component: SignupTokenAdminView,
} satisfies Meta<typeof SignupTokenAdminView>;

export default meta;

type Story = StoryObj<typeof meta>;

export const LoadedEmpty = {
  args: {
    state: { type: "LOADED", tokens: [] },
    createState: { type: "IDLE", error: null },
    createdToken: null,
    onCreateManualToken: noop,
    onRevokeToken: noop,
    onClearCreatedToken: noop,
  },
} satisfies Story;

export const WithCreatedToken = {
  args: {
    state: { type: "LOADED", tokens: [] },
    createState: { type: "IDLE", error: null },
    createdToken: {
      email: "new-user@example.com",
      signupUrl: "https://app.example.com/signup?token=example-token",
    },
    onCreateManualToken: noop,
    onRevokeToken: noop,
    onClearCreatedToken: noop,
  },
} satisfies Story;

export const WithTokens = {
  args: {
    state: {
      type: "LOADED",
      tokens: [
        {
          id: "token-active",
          email: "active@example.com",
          created_by_user_id: null,
          delivery_method: "manual",
          expires_at: "2099-01-01T00:00:00Z",
          max_uses: 1,
          used_count: 0,
          revoked_at: null,
          created_at: "2026-06-17T00:00:00Z",
          updated_at: "2026-06-17T00:00:00Z",
        },
        {
          id: "token-used",
          email: "used@example.com",
          created_by_user_id: null,
          delivery_method: "manual",
          expires_at: "2099-01-01T00:00:00Z",
          max_uses: 1,
          used_count: 1,
          revoked_at: null,
          created_at: "2026-06-17T00:00:00Z",
          updated_at: "2026-06-17T00:00:00Z",
        },
      ],
    },
    createState: { type: "IDLE", error: null },
    createdToken: null,
    onCreateManualToken: noop,
    onRevokeToken: noop,
    onClearCreatedToken: noop,
  },
} satisfies Story;
