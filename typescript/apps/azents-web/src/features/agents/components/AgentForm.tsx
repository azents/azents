"use client";

/**
 * Agent create/update Full Page form component.
 *
 * Inputs name, description, model selection, system prompt, visibility, and enabled state.
 * Admin management section is added in edit mode.
 */

import {
  Alert,
  Anchor,
  Badge,
  Button,
  Container,
  Divider,
  Group,
  Loader,
  NumberInput,
  Radio,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import Link from "next/link";
import { AgentAdminSection } from "./AgentAdminSection";
import { AgentToolkitSection } from "./AgentToolkitSection";
import { SelectableModelOptionsEditor } from "./SelectableModelOptionsEditor";
import type { MemberItem } from "../containers/useAgentFormContainer";
import type { AgentFormTranslator } from "../containers/useAgentFormTranslations";
import type {
  ModelCatalogState,
  ModelSelectionOption,
  ProviderIntegrationOption,
} from "../model-selection";
import type { AgentFormValues } from "../schemas";
import type { AdminListState, AgentFormState, MutationState } from "../types";
import type {
  AgentAdminResponse,
  ModelReasoningEffort,
  WorkspaceModelSettingsResponse,
  WorkspaceRuntimeProfileResponse,
} from "@azents/public-client";
import type { UseFormReturnType } from "@mantine/form";

export type AgentFormSection =
  "all" | "profile" | "model" | "capabilities" | "subagents" | "admins";

function runtimeProfileAvailabilityReason(
  reasonCode: string | null,
):
  | "workspaceProfileDisabled"
  | "providerUnavailable"
  | "infrastructureProfileUnavailable"
  | "workspacePolicyInvalid"
  | "profileIncompatible"
  | "unknown" {
  switch (reasonCode) {
    case "workspace_profile_disabled":
      return "workspaceProfileDisabled";
    case "provider_unavailable":
    case "provider_disabled":
    case "provider_not_active":
    case "provider_disconnected":
    case "provider_workspace_unavailable":
      return "providerUnavailable";
    case "infrastructure_profile_unavailable":
    case "infrastructure_profile_disabled":
      return "infrastructureProfileUnavailable";
    case "workspace_policy_invalid":
      return "workspacePolicyInvalid";
    case "provider_capability_missing":
    case "provider_capability_unavailable":
    case "profile_incompatible":
      return "profileIncompatible";
    default:
      return "unknown";
  }
}

export interface AgentFormProps {
  handle: string;
  formState: AgentFormState;
  mutationState: MutationState;
  adminListState: AdminListState;
  providerOptions: ProviderIntegrationOption[];
  modelOptions: ModelSelectionOption[];
  workspaceModelSettings: WorkspaceModelSettingsResponse | null;
  runtimeProfiles: WorkspaceRuntimeProfileResponse[];
  runtimeProfilesLoading: boolean;
  catalogStates: ReadonlyMap<string, ModelCatalogState>;
  modelsLoading: boolean;
  members: MemberItem[];
  onSyncCatalog: (integrationId: string) => Promise<void>;
  onSubmit: (values: AgentFormValues) => void;
  onAddAdmin: (workspaceUserId: string) => void;
  onRemoveAdmin: (admin: AgentAdminResponse) => void;
  /**
   * "fullpage" (default): own Container + back link + Title.
   * "embedded": external (Settings tab) owns layout, so omit this wrapper.
   */
  mode?: "fullpage" | "embedded";
  section?: AgentFormSection;
  cancelHref?: string;
}

interface AgentFormViewProps extends AgentFormProps {
  form: UseFormReturnType<AgentFormValues>;
  hasSubmitAttempted: boolean;
  onSubmitAttempted: () => void;
  selectedModelEffortLevels: ModelReasoningEffort[];
  t: AgentFormTranslator;
}

export function AgentForm({
  t,
  form,
  hasSubmitAttempted,
  onSubmitAttempted,
  selectedModelEffortLevels,
  handle,
  formState,
  mutationState,
  adminListState,
  modelsLoading,
  members,
  providerOptions,
  runtimeProfiles,
  runtimeProfilesLoading,
  onSyncCatalog,
  onSubmit,
  onAddAdmin,
  onRemoveAdmin,
  mode = "fullpage",
  section = "all",
  cancelHref,
}: AgentFormViewProps): React.ReactElement {
  const isEdit = formState.type === "EDIT";
  const backPath = cancelHref ?? `/w/${handle}/agents`;
  const enabledProviderOptions = providerOptions.filter(
    (option) => !option.disabled,
  );
  const selectedModelSupportsReasoning = selectedModelEffortLevels.length > 0;
  const reasoningEffortOptions = selectedModelEffortLevels.map((value) => ({
    value,
    label: value,
  }));
  const runtimeProfileOptions = runtimeProfiles.map((profile) => ({
    value: profile.id,
    label: profile.display_name,
    disabled: !profile.available || profile.lifecycle === "disabled",
  }));
  const selectedRuntimeProfile =
    runtimeProfiles.find(
      (profile) => profile.id === form.values.runtime_profile_id,
    ) ?? null;

  if (formState.type === "LOADING") {
    return (
      <Container size="md" py="xl">
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      </Container>
    );
  }

  if (formState.type === "NOT_FOUND") {
    return (
      <Container size="md" py="xl">
        <Alert color="red">{t("notFound")}</Alert>
      </Container>
    );
  }

  const handleSubmit = form.onSubmit((values) => {
    onSubmitAttempted();
    onSubmit(values);
  }, onSubmitAttempted);

  const fullpageChrome = mode === "fullpage";
  const showProfile = section === "all" || section === "profile";
  const showModel = section === "all" || section === "model";
  const showCapabilities = section === "all" || section === "capabilities";
  const showSubagents = section === "all" || section === "subagents";
  const showAdmins = section === "all" || section === "admins";
  const showFormActions = section !== "admins";

  const content = (
    <Stack gap="lg">
      {fullpageChrome && (
        <>
          <Anchor component={Link} href={backPath} size="sm">
            <Group gap={4}>
              <IconArrowLeft size={14} />
              <Text size="sm">{t("backToList")}</Text>
            </Group>
          </Anchor>
          <Title order={3}>{isEdit ? t("editTitle") : t("createTitle")}</Title>
        </>
      )}

      {showModel && enabledProviderOptions.length === 0 && !modelsLoading && (
        <Alert color="yellow" title={t("noIntegrationTitle")}>
          <Text size="sm">
            {t("noEnabledIntegrationDescription")}{" "}
            <Anchor component={Link} href={`/w/${handle}/settings`}>
              {t("goToSettings")}
            </Anchor>
          </Text>
        </Alert>
      )}

      <form onSubmit={handleSubmit}>
        <Stack gap="md">
          {showProfile && (
            <TextInput
              label={t("nameLabel")}
              placeholder={t("namePlaceholder")}
              required
              key={form.key("name")}
              {...form.getInputProps("name")}
            />
          )}

          {showProfile && (
            <Textarea
              label={t("descriptionLabel")}
              placeholder={t("descriptionPlaceholder")}
              key={form.key("description")}
              {...form.getInputProps("description")}
            />
          )}

          {showProfile && !isEdit && (
            <Alert color="blue" title={t("runtimeFreeDefaultTitle")}>
              {t("runtimeFreeDefaultDescription")}
            </Alert>
          )}

          {showProfile && !isEdit && (
            <Select
              label={t("runtimeProfileLabel")}
              description={t("runtimeProfileDescription")}
              placeholder={
                runtimeProfilesLoading
                  ? t("runtimeProfileLoading")
                  : t("runtimeProfilePlaceholder")
              }
              data={runtimeProfileOptions}
              clearable
              searchable
              disabled={runtimeProfilesLoading}
              value={form.values.runtime_profile_id}
              onChange={(value) =>
                form.setFieldValue("runtime_profile_id", value)
              }
              error={form.errors.runtime_profile_id}
            />
          )}

          {showProfile &&
            !isEdit &&
            selectedRuntimeProfile !== null &&
            !selectedRuntimeProfile.available && (
              <Alert color="red" title={t("runtimeProfileUnavailableTitle")}>
                {t("runtimeProfileUnavailableDescription", {
                  reason: t(
                    `runtimeProfileAvailabilityReasons.${runtimeProfileAvailabilityReason(
                      selectedRuntimeProfile.availability_reason_code,
                    )}`,
                  ),
                })}
                {selectedRuntimeProfile.availability_reason_code !== null && (
                  <Text size="xs" c="dimmed" ff="monospace" mt="xs">
                    {selectedRuntimeProfile.availability_reason_code}
                  </Text>
                )}
              </Alert>
            )}

          {showModel && (
            <SelectableModelOptionsEditor
              handle={handle}
              title={t("selectableModelOptions.title")}
              description={t("selectableModelOptions.description")}
              options={form.values.selectable_model_options}
              mainModelLabel={form.values.main_model_label}
              lightweightModelLabel={form.values.lightweight_model_label}
              defaultReasoningEffortControl={
                selectedModelSupportsReasoning ? (
                  <Select
                    label={t("defaultReasoningEffortLabel")}
                    data={reasoningEffortOptions}
                    allowDeselect={false}
                    value={form.values.reasoning_effort ?? null}
                    onChange={(value) => {
                      const nextValue =
                        selectedModelEffortLevels.find(
                          (effort) => effort === value,
                        ) ?? null;
                      form.setFieldValue("reasoning_effort", nextValue);
                    }}
                    error={form.errors.reasoning_effort}
                  />
                ) : null
              }
              providerOptions={providerOptions}
              canEdit
              showValidationErrors={hasSubmitAttempted}
              onSyncCatalog={onSyncCatalog}
              onChangeOptions={(options) =>
                form.setFieldValue("selectable_model_options", options)
              }
              onChangeMainModelLabel={(label) =>
                form.setFieldValue("main_model_label", label)
              }
              onChangeLightweightModelLabel={(label) =>
                form.setFieldValue("lightweight_model_label", label)
              }
            />
          )}

          {showProfile && (
            <Textarea
              label={t("systemPromptLabel")}
              placeholder={t("systemPromptPlaceholder")}
              minRows={5}
              autosize
              key={form.key("system_prompt")}
              {...form.getInputProps("system_prompt")}
            />
          )}

          {showProfile && (
            <NumberInput
              label={t("autoArchiveTtlDaysLabel")}
              description={t("autoArchiveTtlDaysDescription")}
              min={1}
              step={1}
              allowDecimal={false}
              allowNegative={false}
              value={form.values.auto_archive_ttl_days}
              onChange={(value) => {
                form.setFieldValue(
                  "auto_archive_ttl_days",
                  typeof value === "number" ? value : 1,
                );
              }}
              error={form.errors.auto_archive_ttl_days}
            />
          )}

          {showModel && (
            <NumberInput
              label={t("maxTurnsLabel")}
              description={t("maxTurnsDescription")}
              placeholder={t("maxTurnsPlaceholder")}
              min={1}
              step={1}
              allowDecimal={false}
              allowNegative={false}
              value={form.values.max_turns ?? ""}
              onChange={(value) => {
                form.setFieldValue(
                  "max_turns",
                  typeof value === "number" ? value : null,
                );
              }}
              error={form.errors.max_turns}
            />
          )}

          {showSubagents && (
            <>
              <Divider
                label={t("subagentsSectionLabel")}
                labelPosition="left"
              />
              <NumberInput
                label={t("subagentMaxSubagentsLabel")}
                description={t("subagentMaxSubagentsDescription")}
                min={0}
                step={1}
                allowDecimal={false}
                allowNegative={false}
                value={form.values.subagent_max_subagents}
                onChange={(value) => {
                  form.setFieldValue(
                    "subagent_max_subagents",
                    typeof value === "number" ? value : 0,
                  );
                }}
                error={form.errors.subagent_max_subagents}
              />
              <NumberInput
                label={t("subagentMaxDepthLabel")}
                description={t("subagentMaxDepthDescription")}
                min={0}
                step={1}
                allowDecimal={false}
                allowNegative={false}
                value={form.values.subagent_max_depth}
                onChange={(value) => {
                  form.setFieldValue(
                    "subagent_max_depth",
                    typeof value === "number" ? value : 0,
                  );
                }}
                error={form.errors.subagent_max_depth}
              />
            </>
          )}

          {showProfile && (
            <Radio.Group
              label={t("typeLabel")}
              key={form.key("type")}
              {...form.getInputProps("type")}
            >
              <Stack gap="xs" mt="xs">
                <Radio
                  value="public"
                  label={t("typePublic")}
                  description={t("typePublicDescription")}
                />
                <Radio
                  value="private"
                  label={t("typePrivate")}
                  description={t("typePrivateDescription")}
                />
              </Stack>
            </Radio.Group>
          )}

          {showCapabilities && (
            <Switch
              label={t("terminalEnabledLabel")}
              description={t("terminalEnabledDescription")}
              checked={form.values.terminal_enabled ?? true}
              onChange={(e) =>
                form.setFieldValue("terminal_enabled", e.currentTarget.checked)
              }
            />
          )}

          {showCapabilities && formState.type === "EDIT" ? (
            <Group gap="xs">
              <Badge
                color={
                  formState.agent.effective_terminal_enabled ? "green" : "red"
                }
                variant="outline"
              >
                {formState.agent.effective_terminal_enabled
                  ? t("terminalCurrentEffectiveEnabled")
                  : t("terminalCurrentEffectiveDisabled")}
              </Badge>
              {formState.agent.terminal_denied_scope !== null ? (
                <Badge color="red" variant="light">
                  {t("terminalDeniedScopeLabel", {
                    scope: t(
                      `terminalDeniedScope.${formState.agent.terminal_denied_scope}`,
                    ),
                  })}
                </Badge>
              ) : null}
            </Group>
          ) : null}

          {showCapabilities && (
            <Switch
              label={t("memoryEnabledLabel")}
              description={t("memoryEnabledDescription")}
              checked={form.values.memory_enabled ?? true}
              onChange={(e) =>
                form.setFieldValue("memory_enabled", e.currentTarget.checked)
              }
            />
          )}

          {showCapabilities && (
            <Switch
              label={t("toolSearchEnabledLabel")}
              description={t("toolSearchEnabledDescription")}
              checked={form.values.tool_search_enabled}
              onChange={(e) =>
                form.setFieldValue(
                  "tool_search_enabled",
                  e.currentTarget.checked,
                )
              }
            />
          )}

          {showProfile && (
            <Switch
              label={t("enabledLabel")}
              key={form.key("enabled")}
              {...form.getInputProps("enabled", { type: "checkbox" })}
            />
          )}

          {showCapabilities && formState.type === "EDIT" && (
            <AgentToolkitSection handle={handle} agentId={formState.agent.id} />
          )}

          {showAdmins && isEdit && (
            <AgentAdminSection
              adminListState={adminListState}
              members={members}
              onAddAdmin={onAddAdmin}
              onRemoveAdmin={onRemoveAdmin}
            />
          )}

          {mutationState.type === "IDLE" && mutationState.error && (
            <Alert color="red">{mutationState.error}</Alert>
          )}

          {showFormActions && (
            <Group justify="flex-end">
              <Button component={Link} href={backPath} variant="default">
                {t("cancel")}
              </Button>
              <Button
                type="submit"
                loading={mutationState.type === "SUBMITTING"}
              >
                {isEdit ? t("save") : t("create")}
              </Button>
            </Group>
          )}
        </Stack>
      </form>
    </Stack>
  );

  if (fullpageChrome) {
    return (
      <Container size="md" py="xl">
        {content}
      </Container>
    );
  }
  return <div style={{ padding: "var(--mantine-spacing-lg)" }}>{content}</div>;
}
