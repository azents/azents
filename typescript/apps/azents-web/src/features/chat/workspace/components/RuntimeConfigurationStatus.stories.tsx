import { Box, rem } from "@mantine/core";
import { NextIntlClientProvider } from "next-intl";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import koMessages from "../../../../../messages/ko-KR.json";
import { RuntimeConfigurationStatus } from "./RuntimeConfigurationStatus";
import type { RuntimeConfigurationRevisionResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const desiredRevision: RuntimeConfigurationRevisionResponse = {
  id: "runtime-configuration-revision-desired",
  provider_id: "runtime-provider-kubernetes",
  provider_capability_revision_id: "capability-revision-12",
  infrastructure_profile_id: "infrastructure-profile-standard",
  infrastructure_profile_version: 4,
  workspace_runtime_profile_id: "workspace-runtime-profile-default",
  workspace_runtime_profile_version: 7,
  agent_selection_version: 3,
  resolution_status: "ready",
  reason_code: null,
  required_capabilities: ["runtime.kubernetes.pod-profile.v1"],
  missing_capabilities: [],
  digest: "sha256:desired-runtime-configuration-digest",
  target_desired_generation: 18,
  provider_reported_digest: null,
  runner_reported_digest: null,
  provider_acknowledged_at: null,
  runtime_observed_at: null,
  created_at: "2026-07-31T06:00:00Z",
};

const appliedRevision: RuntimeConfigurationRevisionResponse = {
  ...desiredRevision,
  provider_reported_digest: desiredRevision.digest,
  runner_reported_digest: desiredRevision.digest,
  provider_acknowledged_at: "2026-07-31T06:01:00Z",
  runtime_observed_at: "2026-07-31T06:02:00Z",
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
        containment: {
          enabled: false,
          applied: false,
          recreation_required: false,
          nested_docker_available: false,
          runtime_available: false,
          availability_reason_code: "runtime_unavailable",
        },
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
          ...desiredRevision,
          resolution_status: "blocked",
          reason_code: "provider_capability_missing",
          missing_capabilities: ["runtime.kubernetes.pod-profile.v1"],
        },
        applied: null,
        containment: {
          enabled: false,
          applied: false,
          recreation_required: false,
          nested_docker_available: false,
          runtime_available: false,
          availability_reason_code: "provider_capability_missing",
        },
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
        desired: desiredRevision,
        applied: null,
        containment: {
          enabled: true,
          applied: false,
          recreation_required: false,
          nested_docker_available: false,
          runtime_available: false,
          availability_reason_code: "runtime_unavailable",
        },
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
        desired: desiredRevision,
        applied: {
          ...appliedRevision,
          id: "runtime-configuration-revision-previous",
          digest: "sha256:previous-runtime-configuration-digest",
          provider_reported_digest:
            "sha256:previous-runtime-configuration-digest",
          runner_reported_digest:
            "sha256:previous-runtime-configuration-digest",
          target_desired_generation: 17,
        },
        containment: {
          enabled: true,
          applied: false,
          recreation_required: true,
          nested_docker_available: false,
          runtime_available: false,
          availability_reason_code: "runtime_recreation_required",
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
        desired: desiredRevision,
        applied: appliedRevision,
        containment: {
          enabled: true,
          applied: true,
          recreation_required: false,
          nested_docker_available: false,
          runtime_available: true,
          availability_reason_code: null,
        },
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
        desired: desiredRevision,
        applied: appliedRevision,
        containment: {
          enabled: false,
          applied: false,
          recreation_required: false,
          nested_docker_available: true,
          runtime_available: true,
          availability_reason_code: null,
        },
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
