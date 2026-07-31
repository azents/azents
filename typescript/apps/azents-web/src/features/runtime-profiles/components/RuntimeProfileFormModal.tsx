"use client";

import {
  Alert,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { useEffect, useMemo } from "react";
import { runtimeProfileFormSchema } from "../schemas";
import type { RuntimeProfileFormValues } from "../schemas";
import type {
  RuntimeProfileEditorState,
  RuntimeProfileMutationState,
} from "../types";
import type { SelectableInfrastructureProfileResponse } from "@azents/public-client";

interface RuntimeProfileFormModalProps {
  editorState: RuntimeProfileEditorState;
  mutationState: RuntimeProfileMutationState;
  infrastructureProfiles: SelectableInfrastructureProfileResponse[];
  onClose: () => void;
  onSubmit: (values: RuntimeProfileFormValues) => void;
}

function cidrsToText(cidrs?: string[]): string {
  return cidrs?.join("\n") ?? "";
}

export function RuntimeProfileFormModal({
  editorState,
  mutationState,
  infrastructureProfiles,
  onClose,
  onSubmit,
}: RuntimeProfileFormModalProps): React.ReactElement {
  const t = useTranslations("workspace.runtimeProfiles");
  const form = useForm<RuntimeProfileFormValues>({
    mode: "controlled",
    initialValues: {
      displayName: "",
      description: "",
      infrastructureProfileId: "",
      lifecycle: "active",
      allowedCidrs: "",
      deniedCidrs: "",
    },
    validate: (values) => {
      const result = runtimeProfileFormSchema.safeParse(values);
      if (result.success) {
        return {};
      }
      return Object.fromEntries(
        result.error.issues.map((issue) => [
          issue.path.join("."),
          issue.message,
        ]),
      );
    },
  });

  useEffect(() => {
    if (editorState.type === "EDIT") {
      const restriction = editorState.profile.policy.network_restriction;
      form.setValues({
        displayName: editorState.profile.display_name,
        description: editorState.profile.description,
        infrastructureProfileId: editorState.profile.infrastructure_profile_id,
        lifecycle: editorState.profile.lifecycle,
        allowedCidrs: cidrsToText(restriction?.allowed_cidrs),
        deniedCidrs: cidrsToText(restriction?.denied_cidrs),
      });
      form.resetDirty();
      return;
    }
    if (editorState.type === "CREATE") {
      form.setValues({
        displayName: "",
        description: "",
        infrastructureProfileId: infrastructureProfiles[0]?.id ?? "",
        lifecycle: "active",
        allowedCidrs: "",
        deniedCidrs: "",
      });
      form.resetDirty();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the editor target changes.
  }, [editorState]);

  const infrastructureOptions = useMemo(() => {
    const options = infrastructureProfiles.map((profile) => ({
      value: profile.id,
      label: `${profile.provider_display_name} · ${profile.display_name}`,
      disabled: false,
    }));
    if (
      editorState.type === "EDIT" &&
      !infrastructureProfiles.some(
        (profile) =>
          profile.id === editorState.profile.infrastructure_profile_id,
      )
    ) {
      options.push({
        value: editorState.profile.infrastructure_profile_id,
        label: `${editorState.profile.infrastructure_profile_id} · ${t("unavailable")}`,
        disabled: true,
      });
    }
    return options;
  }, [editorState, infrastructureProfiles, t]);

  return (
    <Modal
      opened={editorState.type !== "CLOSED"}
      onClose={onClose}
      title={editorState.type === "EDIT" ? t("editTitle") : t("createTitle")}
      size="lg"
    >
      <form onSubmit={form.onSubmit(onSubmit)}>
        <Stack gap="md">
          <TextInput
            label={t("nameLabel")}
            required
            key={form.key("displayName")}
            {...form.getInputProps("displayName")}
          />
          <Textarea
            label={t("descriptionLabel")}
            minRows={2}
            key={form.key("description")}
            {...form.getInputProps("description")}
          />
          <Select
            label={t("infrastructureLabel")}
            description={t("infrastructureDescription")}
            data={infrastructureOptions}
            searchable
            required
            key={form.key("infrastructureProfileId")}
            {...form.getInputProps("infrastructureProfileId")}
          />
          <Select
            label={t("lifecycleLabel")}
            data={[
              { value: "active", label: t("active") },
              { value: "disabled", label: t("disabled") },
            ]}
            allowDeselect={false}
            key={form.key("lifecycle")}
            {...form.getInputProps("lifecycle")}
          />
          <Textarea
            label={t("allowedCidrsLabel")}
            description={t("cidrsDescription")}
            minRows={3}
            key={form.key("allowedCidrs")}
            {...form.getInputProps("allowedCidrs")}
          />
          <Textarea
            label={t("deniedCidrsLabel")}
            description={t("cidrsDescription")}
            minRows={3}
            key={form.key("deniedCidrs")}
            {...form.getInputProps("deniedCidrs")}
          />
          {mutationState.type === "IDLE" && mutationState.error !== null && (
            <Alert color="red">{mutationState.error}</Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" loading={mutationState.type === "SUBMITTING"}>
              {t("save")}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
