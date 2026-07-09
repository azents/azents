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
  Button,
  Checkbox,
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
import { useForm } from "@mantine/form";
import { IconArrowLeft } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  findSelectableModelOptionByLabel,
  selectableModelOptionFormValuesFromStoredOptions,
} from "../model-selection";
import { agentFormSchema } from "../schemas";
import { AgentAdminSection } from "./AgentAdminSection";
import { AgentToolkitSection } from "./AgentToolkitSection";
import { SelectableModelOptionsEditor } from "./SelectableModelOptionsEditor";
import type { MemberItem } from "../containers/useAgentFormContainer";
import type {
  ModelCatalogState,
  ModelSelectionOption,
  ProviderIntegrationOption,
} from "../model-selection";
import type { AgentFormValues } from "../schemas";
import type { AdminListState, AgentFormState, MutationState } from "../types";
import type {
  AgentAdminResponse,
  WorkspaceModelSettingsResponse,
} from "@azents/public-client";

export type AgentFormSection =
  | "all"
  | "profile"
  | "model"
  | "capabilities"
  | "subagents"
  | "admins";

interface AgentFormProps {
  handle: string;
  formState: AgentFormState;
  mutationState: MutationState;
  adminListState: AdminListState;
  providerOptions: ProviderIntegrationOption[];
  modelOptions: ModelSelectionOption[];
  workspaceModelSettings: WorkspaceModelSettingsResponse | null;
  catalogStates: ReadonlyMap<string, ModelCatalogState>;
  modelsLoading: boolean;
  members: MemberItem[];
  onSyncCatalog: (integrationId: string) => void;
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

function formatBuiltinToolLabel(tool: string): string {
  const labels: Record<string, string> = {
    web_search: "Web search",
    web_fetch: "Web fetch",
    image_generation: "Image generation",
  };

  return labels[tool] ?? tool;
}

export function AgentForm({
  handle,
  formState,
  mutationState,
  adminListState,
  modelsLoading,
  members,
  providerOptions,
  workspaceModelSettings,
  onSyncCatalog,
  onSubmit,
  onAddAdmin,
  onRemoveAdmin,
  mode = "fullpage",
  section = "all",
  cancelHref,
}: AgentFormProps): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const [hasSubmitAttempted, setHasSubmitAttempted] = useState(false);

  const isEdit = formState.type === "EDIT";
  const backPath = cancelHref ?? `/w/${handle}/agents`;

  const form = useForm<AgentFormValues>({
    mode: "controlled",
    initialValues: {
      name: "",
      description: "",
      selectable_model_options: [],
      main_model_label: null,
      lightweight_model_label: null,
      system_prompt: "",
      type: "public",
      enabled: true,
      reasoning_effort: null,
      context_window_tokens: null,
      max_output_tokens: null,
      shell_enabled: true,
      memory_enabled: true,
      max_turns: null,
      subagent_max_subagents: 3,
      subagent_max_depth: 1,
      builtin_tools: [],
    },
    validate: (values) => {
      const result = agentFormSchema.safeParse(values);
      if (result.success) {
        return {};
      }
      const errors: Record<string, string> = {};
      for (const issue of result.error.issues) {
        const path = issue.path.join(".");
        if (path && !errors[path]) {
          errors[path] = issue.message;
        }
      }
      return errors;
    },
  });

  const enabledProviderOptions = useMemo(
    () => providerOptions.filter((option) => !option.disabled),
    [providerOptions],
  );

  useEffect(() => {
    if (formState.type === "EDIT") {
      const agent = formState.agent;
      form.setValues({
        name: agent.name,
        description: agent.description ?? "",
        selectable_model_options:
          selectableModelOptionFormValuesFromStoredOptions(
            agent.selectable_model_options,
          ),
        main_model_label: agent.main_model_label,
        lightweight_model_label: agent.lightweight_model_label,
        system_prompt: agent.system_prompt ?? "",
        type: agent.type,
        enabled: agent.enabled,
        reasoning_effort: agent.model_parameters?.reasoning_effort ?? null,
        context_window_tokens:
          agent.model_parameters?.context_window_tokens ?? null,
        max_output_tokens: agent.model_parameters?.max_output_tokens ?? null,
        shell_enabled: agent.shell_enabled,
        memory_enabled: agent.memory_enabled,
        max_turns: agent.max_turns ?? null,
        subagent_max_subagents: agent.subagent_settings.max_subagents ?? 3,
        subagent_max_depth: agent.subagent_settings.max_depth ?? 1,
        builtin_tools:
          agent.model_parameters?.builtin_tools?.map((bt) => bt.name) ?? [],
      });
      form.resetDirty();
      setHasSubmitAttempted(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run only on initial load
  }, [formState.type]);

  useEffect(() => {
    if (formState.type !== "CREATE" || workspaceModelSettings == null) {
      return;
    }
    if (form.isDirty()) {
      return;
    }
    form.setValues({
      selectable_model_options:
        selectableModelOptionFormValuesFromStoredOptions(
          workspaceModelSettings.default_selectable_model_options ?? [],
        ),
      main_model_label: workspaceModelSettings.default_main_model_label ?? null,
      lightweight_model_label:
        workspaceModelSettings.default_lightweight_model_label ?? null,
    });
    form.resetDirty();
    setHasSubmitAttempted(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Resynchronize create defaults before user edits.
  }, [formState.type, workspaceModelSettings]);

  const selectedMainModelOption = findSelectableModelOptionByLabel(
    form.values.selectable_model_options,
    form.values.main_model_label,
  );
  const selectedModelCapabilities =
    selectedMainModelOption?.normalized_capabilities ?? null;

  const selectedModelSupportsReasoning =
    selectedModelCapabilities?.reasoning?.supported ?? false;

  const selectedModelBuiltinTools = useMemo(() => {
    if (selectedMainModelOption == null) {
      return [];
    }
    return selectedModelCapabilities?.built_in_tools?.supported ?? [];
  }, [selectedMainModelOption, selectedModelCapabilities]);

  const reasoningEffortOptions = useMemo(() => {
    const supported = selectedModelCapabilities?.reasoning?.effort_levels ?? [];
    const values = supported.length > 0 ? supported : ["low", "medium", "high"];
    return values.map((value) => ({
      value,
      label: value.charAt(0).toUpperCase() + value.slice(1),
    }));
  }, [selectedModelCapabilities]);

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

  const handleSubmit = form.onSubmit(
    (values) => {
      setHasSubmitAttempted(true);
      onSubmit(values);
    },
    () => setHasSubmitAttempted(true),
  );

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

          {showModel && (
            <SelectableModelOptionsEditor
              handle={handle}
              title={t("selectableModelOptions.title")}
              description={t("selectableModelOptions.description")}
              options={form.values.selectable_model_options}
              mainModelLabel={form.values.main_model_label}
              lightweightModelLabel={form.values.lightweight_model_label}
              providerOptions={providerOptions}
              canEdit
              showValidationErrors={hasSubmitAttempted}
              onSyncCatalog={onSyncCatalog}
              onChangeOptions={(options) =>
                form.setFieldValue("selectable_model_options", options)
              }
              onChangeMainModelLabel={(label) => {
                form.setFieldValue("main_model_label", label);
                form.setFieldValue("builtin_tools", []);
                form.setFieldValue("reasoning_effort", null);
              }}
              onChangeLightweightModelLabel={(label) =>
                form.setFieldValue("lightweight_model_label", label)
              }
            />
          )}

          {showModel && selectedModelSupportsReasoning && (
            <Select
              label={t("reasoningEffortLabel")}
              data={reasoningEffortOptions}
              clearable
              value={form.values.reasoning_effort ?? null}
              onChange={(value) => {
                const nextValue =
                  value === "low" || value === "medium" || value === "high"
                    ? value
                    : null;
                form.setFieldValue("reasoning_effort", nextValue);
              }}
              error={form.errors.reasoning_effort}
            />
          )}

          {showCapabilities && selectedModelBuiltinTools.length > 0 && (
            <>
              <Divider label={t("builtinToolsLabel")} labelPosition="left" />
              <Checkbox.Group
                value={form.values.builtin_tools}
                onChange={(value) => form.setFieldValue("builtin_tools", value)}
              >
                <Stack gap="xs">
                  {selectedModelBuiltinTools.map((tool) => (
                    <Stack key={tool} gap={4}>
                      <Checkbox
                        value={tool}
                        label={formatBuiltinToolLabel(tool)}
                      />
                      {mutationState.type === "IDLE" &&
                        mutationState.builtinToolErrors?.[tool]?.map((msg) => (
                          <Text key={msg} c="red" size="xs" ml="xl">
                            {msg}
                          </Text>
                        ))}
                    </Stack>
                  ))}
                </Stack>
              </Checkbox.Group>
            </>
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

          {showModel && (
            <NumberInput
              label={t("contextWindowTokensLabel")}
              description={t("contextWindowTokensDescription")}
              placeholder={t("contextWindowTokensPlaceholder")}
              min={1}
              step={1}
              allowDecimal={false}
              allowNegative={false}
              value={form.values.context_window_tokens ?? ""}
              onChange={(value) => {
                form.setFieldValue(
                  "context_window_tokens",
                  typeof value === "number" ? value : null,
                );
              }}
              error={form.errors.context_window_tokens}
            />
          )}

          {showModel && (
            <NumberInput
              label={t("maxOutputTokensLabel")}
              description={t("maxOutputTokensDescription")}
              placeholder={t("maxOutputTokensPlaceholder")}
              min={1}
              step={1}
              allowDecimal={false}
              allowNegative={false}
              value={form.values.max_output_tokens ?? ""}
              onChange={(value) => {
                form.setFieldValue(
                  "max_output_tokens",
                  typeof value === "number" ? value : null,
                );
              }}
              error={form.errors.max_output_tokens}
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
              label={t("shellEnabledLabel")}
              description={t("shellEnabledDescription")}
              checked={form.values.shell_enabled ?? false}
              onChange={(e) =>
                form.setFieldValue("shell_enabled", e.currentTarget.checked)
              }
            />
          )}

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
