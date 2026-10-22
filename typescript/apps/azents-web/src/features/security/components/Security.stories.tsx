import { fn } from "storybook/test";
import { ElevationRequiredViewView, Security } from "./Security";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  tags: ["ci-contract"],
  component: Security,
  args: {
    state: { type: "LOADING" },
    passwordState: { type: "IDLE", error: null },
    passwordResetKey: 0,
    onSetPassword: fn(),
    onElevated: fn(),
  },
} satisfies Meta<typeof Security>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Loading = {} satisfies Story;
export const Error = {
  args: {
    state: { type: "ERROR", message: "Unable to load security settings." },
  },
} satisfies Story;
export const Loaded = {
  args: {
    state: {
      type: "LOADED",
      methods: [
        {
          type: "email",
          enabled: true,
          configured: true,
          valid: true,
          can_login: true,
          can_elevate: true,
          can_remove: false,
        },
        {
          type: "password",
          enabled: false,
          configured: false,
          valid: false,
          can_login: false,
          can_elevate: false,
          can_remove: false,
        },
      ],
      hasPassword: false,
    },
  },
} satisfies Story;
export const ElevationRequired = {
  args: { state: { type: "ELEVATION_REQUIRED", elevationMethods: null } },
  render: () => (
    <ElevationRequiredViewView
      elevation={{
        state: { type: "CHOOSE_METHOD", methods: [] },
        onSelectEmail: fn(),
        onSelectPassword: fn(),
        onSubmitEmailCode: fn(),
        onSubmitPassword: fn(),
        onResendCode: fn(),
      }}
    />
  ),
} satisfies Story;
