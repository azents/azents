import { rem } from "@mantine/core";
import { fn } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ModelAvailabilityControl } from "./ModelAvailabilityControl";
import type { ModelAvailabilityViewState } from "../modelAvailability";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const baseAvailability = {
  semantic_label: "Default",
  primary: {
    llm_provider_integration_id: "integration-primary",
    model_identifier: "gpt-primary",
  },
  primary_display_name: "GPT Primary",
  deadline: "2026-09-13T04:05:00Z",
  server_time: "2026-09-13T04:00:00Z",
  first_usable_fallback_display_name: "GPT Fallback",
  reservation: null,
};

function loaded(
  state: "available" | "cooldown" | "probing" | "primary_next",
): ModelAvailabilityViewState {
  return {
    type: "LOADED",
    data: {
      ...baseAvailability,
      state,
      deadline: state === "available" ? null : baseAvailability.deadline,
      reservation:
        state === "primary_next"
          ? {
              semantic_label: "Default",
              candidate: baseAvailability.primary,
              health_generation: 3,
              reservation_generation: 2,
              claim_token: "claim-token",
              created_at: "2026-09-13T04:00:00Z",
              expires_at: "2026-09-13T04:05:00Z",
            }
          : null,
    },
  };
}

const meta = {
  component: ModelAvailabilityControl,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(420)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    activeSemanticLabel: "Default",
    actionPending: false,
    actionError: false,
    observedAtMs: Date.parse("2026-09-13T04:00:00Z"),
    nowMs: Date.parse("2026-09-13T04:00:00Z"),
    onRefresh: fn(async () => {}),
    onReservePrimary: fn(async () => {}),
    onCancelPrimary: fn(async () => {}),
  },
} satisfies Meta<typeof ModelAvailabilityControl>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Available = {
  args: { state: loaded("available") },
} satisfies Story;

export const CooldownWithFallback = {
  args: { state: loaded("cooldown") },
} satisfies Story;

export const ProbeBusy = {
  args: { state: loaded("probing") },
} satisfies Story;

export const PrimaryNext = {
  args: { state: loaded("primary_next") },
} satisfies Story;

export const StaleDraftLabel = {
  args: {
    state: loaded("cooldown"),
    activeSemanticLabel: "Fast",
  },
} satisfies Story;

export const Conflict = {
  args: {
    state: loaded("cooldown"),
    actionError: true,
  },
} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const Error = {
  args: { state: { type: "ERROR" } },
} satisfies Story;
