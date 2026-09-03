"use client";

import {
  Alert,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import {
  policySchemaVersionForInfrastructure,
  proxyDomainModeForInfrastructure,
} from "../runtimeProfilePolicy";
import type { RuntimeProfileFormValues } from "../schemas";
import type {
  RuntimeProfileEditorState,
  RuntimeProfileMutationState,
} from "../types";
import type { SelectableInfrastructureProfileResponse } from "@azents/public-client";
import type { UseFormReturnType } from "@mantine/form";

interface RuntimeProfileFormModalProps {
  editorState: RuntimeProfileEditorState;
  mutationState: RuntimeProfileMutationState;
  form: UseFormReturnType<RuntimeProfileFormValues>;
  infrastructureProfiles: SelectableInfrastructureProfileResponse[];
  onClose: () => void;
  onSubmit: (values: RuntimeProfileFormValues) => void;
}

export function RuntimeProfileFormModal({
  editorState,
  mutationState,
  form,
  infrastructureProfiles,
  onClose,
  onSubmit,
}: RuntimeProfileFormModalProps): React.ReactElement {
  const t = useTranslations("workspace.runtimeProfiles");

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
  const selectedInfrastructure = infrastructureProfiles.find(
    (profile) => profile.id === form.values.infrastructureProfileId,
  );
  const infrastructureNetworkMode =
    selectedInfrastructure?.infrastructure_network.mode ??
    (editorState.type === "EDIT" &&
    editorState.profile.infrastructure_profile_id ===
      form.values.infrastructureProfileId
      ? editorState.profile.infrastructure_network?.mode
      : null) ??
    null;
  const infrastructureDomainMode =
    selectedInfrastructure?.infrastructure_network.domain_mode ??
    (editorState.type === "EDIT" &&
    editorState.profile.infrastructure_profile_id ===
      form.values.infrastructureProfileId
      ? editorState.profile.infrastructure_network?.domain_mode
      : null) ??
    null;
  const modeOptions = [
    { value: "inherit", label: t("networkMode.inherit") },
    ...(form.values.policySchemaVersion === 1 ||
    infrastructureNetworkMode === "direct"
      ? [{ value: "direct", label: t("networkMode.direct") }]
      : []),
    ...(form.values.policySchemaVersion === 2 &&
    (infrastructureNetworkMode === "direct" ||
      infrastructureNetworkMode === "proxy_required")
      ? [
          {
            value: "proxy_required",
            label: t("networkMode.proxy_required"),
          },
        ]
      : []),
    ...(form.values.policySchemaVersion === 2
      ? [{ value: "no_network", label: t("networkMode.no_network") }]
      : []),
  ];

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
            value={form.values.infrastructureProfileId}
            error={form.errors.infrastructureProfileId}
            onChange={(value) => {
              form.setFieldValue("infrastructureProfileId", value ?? "");
              form.setFieldValue("networkMode", "inherit");
              const infrastructure = infrastructureProfiles.find(
                (profile) => profile.id === value,
              );
              if (infrastructure) {
                form.setFieldValue(
                  "policySchemaVersion",
                  policySchemaVersionForInfrastructure(infrastructure),
                );
                form.setFieldValue(
                  "proxyDomainMode",
                  proxyDomainModeForInfrastructure(
                    infrastructure.infrastructure_network,
                  ),
                );
              }
            }}
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
          <Switch
            label={t("terminalEnabledLabel")}
            description={t("terminalEnabledDescription")}
            checked={form.values.terminalEnabled}
            onChange={(event) =>
              form.setFieldValue("terminalEnabled", event.currentTarget.checked)
            }
          />
          <Select
            label={t("networkModeLabel")}
            description={t("networkModeDescription")}
            data={modeOptions}
            allowDeselect={false}
            key={form.key("networkMode")}
            {...form.getInputProps("networkMode")}
          />
          {infrastructureNetworkMode !== null && (
            <Text size="xs" c="dimmed">
              {t("infrastructureAuthority", {
                mode: t(`networkMode.${infrastructureNetworkMode}`),
              })}
            </Text>
          )}
          {form.values.networkMode === "proxy_required" && (
            <Alert color="blue" title={t("proxyLimitationsTitle")}>
              {t("proxyLimitationsDescription")}
            </Alert>
          )}
          {form.values.networkMode === "no_network" && (
            <Alert color="gray" title={t("noNetworkTitle")}>
              {t("noNetworkDescription")}
            </Alert>
          )}
          {(form.values.networkMode === "direct" ||
            form.values.networkMode === "proxy_required") && (
            <>
              <Textarea
                label={t("allowedCidrsLabel")}
                description={t("cidrsDescription")}
                minRows={3}
                key={form.key("allowedCidrs")}
                {...form.getInputProps("allowedCidrs")}
              />
              <Textarea
                label={t("deniedCidrsLabel")}
                description={t("deniedCidrsDescription")}
                minRows={3}
                key={form.key("deniedCidrs")}
                {...form.getInputProps("deniedCidrs")}
              />
            </>
          )}
          {form.values.policySchemaVersion === 2 &&
            form.values.networkMode === "proxy_required" && (
              <>
                <Select
                  label={t("proxyDomainModeLabel")}
                  data={[
                    ...(infrastructureDomainMode === "allowlist"
                      ? []
                      : [
                          {
                            value: "unrestricted",
                            label: t("proxyDomainMode.unrestricted"),
                          },
                        ]),
                    {
                      value: "allowlist",
                      label: t("proxyDomainMode.allowlist"),
                    },
                  ]}
                  allowDeselect={false}
                  key={form.key("proxyDomainMode")}
                  {...form.getInputProps("proxyDomainMode")}
                />
                {form.values.proxyDomainMode === "allowlist" && (
                  <Textarea
                    label={t("allowedDomainsLabel")}
                    description={t("domainsDescription")}
                    minRows={3}
                    key={form.key("allowedDomains")}
                    {...form.getInputProps("allowedDomains")}
                  />
                )}
                <Textarea
                  label={t("deniedDomainsLabel")}
                  description={t("deniedDomainsDescription")}
                  minRows={3}
                  key={form.key("deniedDomains")}
                  {...form.getInputProps("deniedDomains")}
                />
              </>
            )}
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
