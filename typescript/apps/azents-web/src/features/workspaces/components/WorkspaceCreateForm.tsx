"use client";

/**
 * Workspace creation form component
 *
 * Display per-field errors with Mantine useForm + Zod validation.
 */
import { Button, Divider, Stack, Text, TextInput, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef } from "react";
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import { workspaceSchema } from "../schemas";
import type { WorkspaceCreateContainerProps } from "../containers/useWorkspaceCreate";

/** Convert name to kebab-case handle */
function toHandle(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

/** Workspace information input form (pure UI) */
function WorkspaceCreateFormInner({
  error,
  isPending,
  onSubmit,
}: {
  error: string | null;
  isPending: boolean;
  onSubmit: (data: {
    workspaceName: string;
    workspaceHandle: string;
    ownerName: string;
  }) => void;
}): React.ReactElement {
  const t = useTranslations("workspaces");

  const form = useForm({
    mode: "controlled",
    initialValues: {
      workspaceName: "",
      workspaceHandle: "",
      ownerName: "",
    },
    validate: (values) => {
      const result = workspaceSchema.safeParse(values);
      if (result.success) {
        return {};
      }
      const errors: Record<string, string> = {};
      for (const issue of result.error.issues) {
        const path = issue.path.join(".");
        if (!path) {
          continue;
        }
        if (path === "workspaceName") {
          errors[path] = t("errors.nameRequired");
        } else if (path === "workspaceHandle") {
          errors[path] =
            issue.code === "invalid_format"
              ? t("errors.handleFormat")
              : t("errors.handleRequired");
        } else if (path === "ownerName") {
          errors[path] = t("errors.nameRequired");
        } else {
          errors[path] = issue.message;
        }
      }
      return errors;
    },
  });

  const handleEditedRef = useRef(false);

  const handleNameChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const name = e.currentTarget.value;
      form.setFieldValue("workspaceName", name);
      if (!handleEditedRef.current) {
        form.setFieldValue("workspaceHandle", toHandle(name));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is new reference every render
    [],
  );

  const handleHandleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      handleEditedRef.current = true;
      form.setFieldValue("workspaceHandle", e.currentTarget.value);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is new reference every render
    [],
  );

  useEffect(() => {
    if (error) {
      form.clearErrors();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is new reference every render
  }, [error]);

  function handleSubmit(values: typeof form.values): void {
    onSubmit({
      workspaceName: values.workspaceName.trim(),
      workspaceHandle: values.workspaceHandle.trim(),
      ownerName: values.ownerName.trim(),
    });
  }

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
