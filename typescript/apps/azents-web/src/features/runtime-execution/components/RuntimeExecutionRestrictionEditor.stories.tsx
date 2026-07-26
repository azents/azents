import { RuntimeExecutionRestrictionEditor } from "./RuntimeExecutionRestrictionEditor";
import type { RuntimeExecutionPolicyRestriction } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const emptyRestriction: RuntimeExecutionPolicyRestriction = {
  schema_version: 1,
  image_build: null,
  container_run: null,
  compose: null,
  resources: null,
  engine_storage: null,
  network_egress: null,
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
      image_build: { enabled: false },
      resources: {
        cpu_millicores: 2_000,
        memory_bytes: 4_294_967_296,
        pids: 512,
        container_count: 8,
        ephemeral_storage_bytes: 10_737_418_240,
      },
      network_egress: {
        mode: "restricted",
        allowed_destinations: ["registry.example.com"],
        denied_destinations: ["metadata.internal"],
      },
    },
  },
};

export const ReadOnly: Story = {
  args: {
    readOnly: true,
    restriction: {
      ...emptyRestriction,
      container_run: { enabled: false },
    },
  },
};
