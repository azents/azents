"use client";
import { Button, Divider, Stack, Text, TextInput, Title } from "@mantine/core";
/**
 * Workspace creation form component
 *
 * Display per-field errors with Mantine useForm + Zod validation.
 */
import { FormPageLayout } from "@/shared/components/FormPageLayout";

import { useWorkspaceCreateFormInnerController } from "../containers/useWorkspaceCreateFormInnerController";
import type { WorkspaceCreateContainerProps } from "../containers/useWorkspaceCreate";
import type { WorkspaceCreateFormInnerViewProps } from "../containers/useWorkspaceCreateFormInnerController";

/** Workspace information input form (pure UI) */
function WorkspaceCreateFormInner(props: {
  error: string | null;
  isPending: boolean;
  onSubmit: (data: {
    workspaceName: string;
    workspaceHandle: string;
    ownerName: string;
  }) => void;
}): React.ReactElement {
  return (
    <WorkspaceCreateFormInnerView
      {...useWorkspaceCreateFormInnerController(props)}
    />
  );
}

export function WorkspaceCreateFormInnerView({
  error,
  isPending,
  t,
  form,
  handleNameChange,
  handleHandleChange,
  handleSubmit,
}: WorkspaceCreateFormInnerViewProps): React.ReactElement {
  return (
    <form onSubmit={form.onSubmit(handleSubmit)}>
      <Stack gap="lg">
        <Stack gap="xs" align="center">
          <Title order={2}>{t("create.headline")}</Title>
          <Text c="dimmed">{t("create.description")}</Text>
        </Stack>

        <Divider label={t("create.sectionWorkspace")} labelPosition="left" />

        <TextInput
          label={t("create.workspaceName")}
          placeholder={t("create.workspaceNamePlaceholder")}
          {...form.getInputProps("workspaceName")}
          onChange={handleNameChange}
          size="lg"
          disabled={isPending}
        />

        <TextInput
          label={t("create.workspaceHandle")}
          placeholder={t("create.workspaceHandlePlaceholder")}
          {...form.getInputProps("workspaceHandle")}
          onChange={handleHandleChange}
          size="lg"
          disabled={isPending}
        />

        <Divider label={t("create.sectionOwner")} labelPosition="left" />

        <TextInput
          label={t("create.ownerName")}
          placeholder={t("create.ownerNamePlaceholder")}
          {...form.getInputProps("ownerName")}
          size="lg"
          disabled={isPending}
        />

        {error && (
          <Text size="sm" c="red">
            {error}
          </Text>
        )}

        <Button type="submit" size="lg" loading={isPending}>
          {t("create.submit")}
        </Button>
      </Stack>
    </form>
  );
}

/** Container -> Component mapping (including FormPageLayout) */
export function WorkspaceCreateForm({
  state,
  onSubmit,
}: WorkspaceCreateContainerProps): React.ReactElement {
  return (
    <FormPageLayout>
      <WorkspaceCreateFormInner
        error={state.type === "IDLE" ? state.error : null}
        isPending={state.type === "CREATING"}
        onSubmit={onSubmit}
      />
    </FormPageLayout>
  );
}
