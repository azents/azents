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
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { useEffect, useMemo } from "react";
import {
  policySchemaVersionForInfrastructure,
  proxyDomainModeForInfrastructure,
} from "../runtimeProfilePolicy";
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

function networkModeForProfile(
  editorState: RuntimeProfileEditorState,
): RuntimeProfileFormValues["networkMode"] {
  if (editorState.type !== "EDIT") {
    return "inherit";
  }
  const policy = editorState.profile.policy;
  if (policy.schema_version === 1) {
    return policy.network_restriction === null ? "inherit" : "direct";
  }
  return policy.network_restriction.mode;
}

function networkFieldsForProfile(
  editorState: RuntimeProfileEditorState,
): Pick<
  RuntimeProfileFormValues,
  | "allowedCidrs"
  | "deniedCidrs"
  | "proxyDomainMode"
  | "allowedDomains"
  | "deniedDomains"
> {
  if (editorState.type !== "EDIT") {
    return {
      allowedCidrs: "",
      deniedCidrs: "",
      proxyDomainMode: "unrestricted",
      allowedDomains: "",
      deniedDomains: "",
    };
  }
  const restriction = editorState.profile.policy.network_restriction;
  if (
    restriction === null ||
    ("mode" in restriction &&
      (restriction.mode === "inherit" || restriction.mode === "no_network"))
  ) {
    return {
      allowedCidrs: "",
      deniedCidrs: "",
      proxyDomainMode: "unrestricted",
      allowedDomains: "",
      deniedDomains: "",
    };
  }
  return {
    allowedCidrs: cidrsToText(restriction.allowed_cidrs),
    deniedCidrs: cidrsToText(restriction.denied_cidrs),
    proxyDomainMode:
      "domain_policy" in restriction
        ? restriction.domain_policy.mode
        : "unrestricted",
    allowedDomains:
      "domain_policy" in restriction
        ? cidrsToText(restriction.domain_policy.allowed_domains)
        : "",
    deniedDomains:
      "domain_policy" in restriction
        ? cidrsToText(restriction.domain_policy.denied_domains)
        : "",
  };
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
      terminalEnabled: true,
      policySchemaVersion: 2,
      networkMode: "inherit",
      allowedCidrs: "",
      deniedCidrs: "",
      proxyDomainMode: "unrestricted",
      allowedDomains: "",
      deniedDomains: "",
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
      const selectedInfrastructure = infrastructureProfiles.find(
        (profile) =>
          profile.id === editorState.profile.infrastructure_profile_id,
      );
      const infrastructureNetwork =
        selectedInfrastructure?.infrastructure_network ??
        editorState.profile.infrastructure_network;
      const networkFields = networkFieldsForProfile(editorState);
      form.setValues({
        displayName: editorState.profile.display_name,
        description: editorState.profile.description,
        infrastructureProfileId: editorState.profile.infrastructure_profile_id,
        lifecycle: editorState.profile.lifecycle,
        terminalEnabled: editorState.profile.terminal_enabled,
        policySchemaVersion: editorState.profile.policy.schema_version,
        networkMode: networkModeForProfile(editorState),
        ...networkFields,
        proxyDomainMode:
          infrastructureNetwork?.domain_mode === "allowlist"
            ? "allowlist"
            : networkFields.proxyDomainMode,
      });
      form.resetDirty();
      return;
    }
    if (editorState.type === "CREATE") {
      const initialInfrastructure = infrastructureProfiles[0];
      form.setValues({
        displayName: "",
        description: "",
        infrastructureProfileId: initialInfrastructure?.id ?? "",
        lifecycle: "active",
        terminalEnabled: true,
        policySchemaVersion: initialInfrastructure
          ? policySchemaVersionForInfrastructure(initialInfrastructure)
          : 2,
        networkMode: "inherit",
        allowedCidrs: "",
        deniedCidrs: "",
        proxyDomainMode: proxyDomainModeForInfrastructure(
          initialInfrastructure?.infrastructure_network ?? null,
        ),
        allowedDomains: "",
        deniedDomains: "",
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
