"use client";

import { Button, rem } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ModelCatalogPicker } from "./ModelCatalogPicker";
import type { ProviderIntegrationOption } from "../model-selection";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const integrations: ProviderIntegrationOption[] = [
  {
    value: "integration-bedrock",
    label: "AWS Bedrock · aws_bedrock",
    provider: "aws_bedrock",
    integration: {
      id: "integration-bedrock",
      provider: "aws_bedrock",
      name: "AWS Bedrock",
      config: {
        type: "aws_credentials",
        access_key_id: "AKIA...",
        region: "us-west-2",
      },
      enabled: true,
      created_at: "2026-06-21T00:00:00Z",
      updated_at: "2026-06-21T00:00:00Z",
    },
    disabled: false,
  },
];

function OpenStory(): React.ReactElement {
  const [opened, { open, close }] = useDisclosure(true);
  return (
    <>
      <Button onClick={open}>Open picker</Button>
      <ModelCatalogPicker
        opened={opened}
        title="Select model"
        handle="story-workspace"
        integrations={integrations}
        selectedIntegrationId="integration-bedrock"
        selectedValue={null}
        onClose={close}
        onSelectIntegration={() => {}}
        onSelectModel={() => {}}
        onSyncCatalog={() => Promise.resolve()}
      />
    </>
  );
}

const meta = {
  component: OpenStory,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(900)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof OpenStory>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;
