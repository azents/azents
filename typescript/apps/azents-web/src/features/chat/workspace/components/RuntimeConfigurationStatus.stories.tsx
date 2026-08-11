import { Box, rem } from "@mantine/core";
import { NextIntlClientProvider } from "next-intl";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import koMessages from "../../../../../messages/ko-KR.json";
import { RuntimeConfigurationStatus } from "./RuntimeConfigurationStatus";
import type { RuntimeConfigurationStateResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const desiredState: RuntimeConfigurationStateResponse = {
  sequence: 18,
  status: "ready",
  target_generation: 18,
  digest: "sha256:desired-runtime-configuration-digest",
  provider_id: "runtime-provider-kubernetes",
  provider_capability_revision_id: "capability-revision-12",
  infrastructure_profile_id: "infrastructure-profile-standard",
  infrastructure_profile_version: 4,
  workspace_runtime_profile_id: "workspace-runtime-profile-default",
  workspace_runtime_profile_version: 7,
  agent_selection_version: 3,
  required_capabilities: ["runtime.kubernetes.pod-profile.v1"],
  missing_capabilities: [],
  reason_code: null,
  provider_reported_digest: null,
  runner_reported_digest: null,
  provider_acknowledged_at: null,
  runner_observed_at: null,
  applied_at: null,
};

const appliedState: RuntimeConfigurationStateResponse = {
  ...desiredState,
  provider_reported_digest: desiredState.digest,
  runner_reported_digest: desiredState.digest,
  provider_acknowledged_at: "2026-07-31T06:01:00Z",
  runner_observed_at: "2026-07-31T06:02:00Z",
  applied_at: "2026-07-31T06:02:00Z",
};

const meta = {
  component: RuntimeConfigurationStatus,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(760)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof RuntimeConfigurationStatus>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const ProfileRequired = {
  args: {
    state: {
      type: "LOADED",
      configuration: {
        status: "profile_required",
        desired: null,
        applied: null,
      },
    },
  },
} satisfies Story;

export const ConfigurationBlocked = {
  args: {
    state: {
      type: "LOADED",
      configuration: {
        status: "configuration_blocked",
        desired: {
          ...desiredState,
          status: "blocked",
          digest: null,
          reason_code: "provider_capability_missing",
          missing_capabilities: ["runtime.kubernetes.pod-profile.v1"],
        },
        applied: null,
      },
    },
  },
} satisfies Story;

export const ConfiguredNotCreated = {
  args: {
    state: {
      type: "LOADED",
      configuration: {
        status: "configured_not_created",
        desired: desiredState,
        applied: null,
      },
    },
  },
} satisfies Story;

export const WaitingForRecreation = {
  args: {
    state: {
      type: "LOADED",
      configuration: {
        status: "waiting_for_recreation",
        desired: desiredState,
        applied: {
          ...appliedState,
          sequence: 17,
          digest: "sha256:previous-runtime-configuration-digest",
          provider_reported_digest:
            "sha256:previous-runtime-configuration-digest",
          runner_reported_digest:
            "sha256:previous-runtime-configuration-digest",
          target_generation: 17,
        },
      },
    },
  },
} satisfies Story;

export const Applied = {
  args: {
    state: {
      type: "LOADED",
      configuration: {
        status: "applied",
        desired: desiredState,
        applied: appliedState,
      },
    },
  },
} satisfies Story;

export const DirectRuntimeApplied = {
  args: {
    state: {
      type: "LOADED",
      configuration: {
        status: "applied",
        desired: desiredState,
        applied: appliedState,
      },
    },
  },
} satisfies Story;

export const MobileApplied = {
  args: Applied.args,
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="ko-KR" messages={koMessages}>
        <Box maw={rem(360)} mx="auto">
          <Story />
        </Box>
      </NextIntlClientProvider>
    ),
  ],
} satisfies Story;

export const MobileWaitingForRecreation = {
  args: WaitingForRecreation.args,
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="ko-KR" messages={koMessages}>
        <Box maw={rem(360)} mx="auto">
          <Story />
        </Box>
      </NextIntlClientProvider>
    ),
  ],
} satisfies Story;
