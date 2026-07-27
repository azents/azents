import { RuntimeExecutionRestrictionEditor } from "./RuntimeExecutionRestrictionEditor";
import type { RuntimeExecutionPolicyRestriction } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const emptyRestriction: RuntimeExecutionPolicyRestriction = {
  schema_version: 1,
  docker: null,
  resources: null,
};

const meta = {
  title: "Runtime Execution/Restriction Editor",
  component: RuntimeExecutionRestrictionEditor,
  args: {
    restriction: emptyRestriction,
    onChange: () => null,
  },
} satisfies Meta<typeof RuntimeExecutionRestrictionEditor>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Inherited: Story = {};

export const Restricted: Story = {
  args: {
    restriction: {
      ...emptyRestriction,
      docker: {
        enabled: false,
        storage_mode: null,
        storage_capacity_bytes: null,
      },
      resources: {
        cpu_request_millicores: 1_000,
        cpu_limit_millicores: 2_000,
        memory_request_bytes: 2_147_483_648,
        memory_limit_bytes: 4_294_967_296,
        ephemeral_storage_bytes: 10_737_418_240,
        persistent_storage_bytes: 21_474_836_480,
      },
    },
  },
};

export const ReadOnly: Story = {
  args: {
    readOnly: true,
    restriction: {
      ...emptyRestriction,
      docker: {
        enabled: false,
        storage_mode: null,
        storage_capacity_bytes: null,
      },
    },
  },
};
