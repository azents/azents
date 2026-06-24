import { Paper, Stack, Text, TextInput, Title } from "@mantine/core";
import { FormPageLayout } from "./FormPageLayout";
import { StepIndicator } from "./StepIndicator";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: FormPageLayout,
} satisfies Meta<typeof FormPageLayout>;

export default meta;

type Story = StoryObj<typeof meta>;

const formContent = (
  <Paper withBorder p="lg" radius="md">
    <Stack gap="md">
      <Title order={3}>Create workspace</Title>
      <Text c="dimmed" size="sm">
        Set up the first workspace before inviting teammates.
      </Text>
      <TextInput label="Workspace name" value="Design Ops" readOnly />
    </Stack>
  </Paper>
);

export const BasicForm = {
  args: {
    children: formContent,
  },
} satisfies Story;

export const WithHeader = {
  args: {
    header: <StepIndicator currentStep={2} />,
    children: formContent,
  },
} satisfies Story;
