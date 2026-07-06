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
  Card,
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
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  modelSelectionProviderValue,
  modelSelectionValue,
} from "../model-selection";
import { agentFormSchema } from "../schemas";
import { AgentAdminSection } from "./AgentAdminSection";
import { AgentToolkitSection } from "./AgentToolkitSection";
import { ModelCatalogPicker } from "./ModelCatalogPicker";
import type { MemberItem } from "../containers/useAgentFormContainer";
import type {
  ModelCatalogState,
  ModelSelectionOption,
  ProviderIntegrationOption,
  SelectableModelCandidate,
} from "../model-selection";
import type { AgentFormValues } from "../schemas";
import type { AdminListState, AgentFormState, MutationState } from "../types";
import type { AgentAdminResponse } from "@azents/public-client";

export type AgentFormSection =
  | "all"
  | "profile"
  | "model"
  | "capabilities"
  | "admins";

interface AgentFormProps {
  handle: string;
  formState: AgentFormState;
  mutationState: MutationState;
  adminListState: AdminListState;
  providerOptions: ProviderIntegrationOption[];
  modelOptions: ModelSelectionOption[];
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
  onSyncCatalog,
  onSubmit,
  onAddAdmin,
  onRemoveAdmin,
  mode = "fullpage",
  section = "all",
  cancelHref,
}: AgentFormProps): React.ReactElement {
  const t = useTranslations("workspace.agents");

  const isEdit = formState.type === "EDIT";
  const backPath = cancelHref ?? `/w/${handle}/agents`;
  const [mainPickerOpen, setMainPickerOpen] = useState(false);
  const [lightweightPickerOpen, setLightweightPickerOpen] = useState(false);
  const [mainModelPreview, setMainModelPreview] =
    useState<SelectableModelCandidate | null>(null);
  const [lightweightModelPreview, setLightweightModelPreview] =
    useState<SelectableModelCandidate | null>(null);

  const form = useForm<AgentFormValues>({
    mode: "controlled",
    initialValues: {
      name: "",
      description: "",
      model_provider_integration_id: null,
      model_selection_value: null,
      lightweight_model_provider_integration_id: null,
      lightweight_model_selection_value: null,
      system_prompt: "",
      type: "public",
      enabled: true,
      reasoning_effort: null,
      context_window_tokens: null,
      max_output_tokens: null,
      shell_enabled: true,
      memory_enabled: true,
      max_turns: null,
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
        model_provider_integration_id: modelSelectionProviderValue(
          agent.model_selection,
        ),
        model_selection_value: modelSelectionValue(agent.model_selection),
        lightweight_model_provider_integration_id: modelSelectionProviderValue(
          agent.lightweight_model_selection,
        ),
        lightweight_model_selection_value: modelSelectionValue(
          agent.lightweight_model_selection,
        ),
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
        builtin_tools:
          agent.model_parameters?.builtin_tools?.map((bt) => bt.name) ?? [],
      });
      form.resetDirty();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run only on initial load
  }, [formState.type]);

  const selectedModelSnapshot =
    formState.type === "EDIT" ? formState.agent.model_selection : null;
  const selectedLightweightModelSnapshot =
    formState.type === "EDIT"
      ? formState.agent.lightweight_model_selection
      : null;
  const selectedModelCapabilities =
    mainModelPreview?.normalized_capabilities ??
    selectedModelSnapshot?.normalized_capabilities ??
    null;

  const selectedModelSupportsReasoning =
    selectedModelCapabilities?.reasoning?.supported ?? false;

  const selectedModelBuiltinTools = useMemo(() => {
    if (!form.values.model_selection_value) {
      return [];
    }
    return selectedModelCapabilities?.built_in_tools?.supported ?? [];
  }, [form.values.model_selection_value, selectedModelCapabilities]);

  const reasoningEffortOptions = useMemo(() => {
    const supported = selectedModelCapabilities?.reasoning?.effort_levels ?? [];
    const values = supported.length > 0 ? supported : ["low", "medium", "high"];
    return values.map((value) => ({
      value,
      label: value.charAt(0).toUpperCase() + value.slice(1),
    }));
  }, [selectedModelCapabilities]);

  const handleMainProviderChange = useCallback(
    (value: string | null): void => {
      form.setFieldValue("model_provider_integration_id", value);
      form.setFieldValue("model_selection_value", null);
      form.setFieldValue("builtin_tools", []);
      form.setFieldValue("reasoning_effort", null);
      setMainModelPreview(null);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is stable ref
    [],
  );

  const handleModelChange = useCallback(
    (model: SelectableModelCandidate): void => {
      const integrationId = form.values.model_provider_integration_id;
      if (integrationId == null) {
        return;
      }
      form.setFieldValue(
        "model_selection_value",
        `${integrationId}:${model.model_identifier}`,
      );
      form.setFieldValue("builtin_tools", []);
      setMainModelPreview(model);
      if (!model.normalized_capabilities.reasoning?.supported) {
        form.setFieldValue("reasoning_effort", null);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is stable ref
    [form.values.model_provider_integration_id],
  );

  const handleLightweightProviderChange = useCallback(
    (value: string | null): void => {
      form.setFieldValue("lightweight_model_provider_integration_id", value);
      form.setFieldValue("lightweight_model_selection_value", null);
      setLightweightModelPreview(null);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is stable ref
    [],
  );

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
    onSubmit(values);
  });

  const fullpageChrome = mode === "fullpage";
  const showProfile = section === "all" || section === "profile";
  const showModel = section === "all" || section === "model";
  const showCapabilities = section === "all" || section === "capabilities";
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

      {showModel && (
        <ModelCatalogPicker
          opened={mainPickerOpen}
          title={t("modelCatalogPicker.selectMainTitle")}
          handle={handle}
          integrations={enabledProviderOptions}
          selectedIntegrationId={form.values.model_provider_integration_id}
          selectedValue={form.values.model_selection_value}
          onClose={() => setMainPickerOpen(false)}
          onSelectIntegration={handleMainProviderChange}
          onSelectModel={handleModelChange}
          onSyncCatalog={onSyncCatalog}
        />
      )}
      {showModel && (
        <ModelCatalogPicker
          opened={lightweightPickerOpen}
          title={t("modelCatalogPicker.selectLightweightTitle")}
          handle={handle}
          integrations={enabledProviderOptions}
          selectedIntegrationId={
            form.values.lightweight_model_provider_integration_id
          }
          selectedValue={form.values.lightweight_model_selection_value}
          onClose={() => setLightweightPickerOpen(false)}
          onSelectIntegration={handleLightweightProviderChange}
          onSelectModel={(model) => {
            const integrationId =
              form.values.lightweight_model_provider_integration_id;
            if (integrationId == null) {
              return;
            }
            form.setFieldValue(
              "lightweight_model_selection_value",
              `${integrationId}:${model.model_identifier}`,
            );
            setLightweightModelPreview(model);
          }}
          onSyncCatalog={onSyncCatalog}
        />
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
            <Stack gap="xs">
              <Text fw={500}>{t("mainModelLabel")}</Text>
              <Text size="sm" c="dimmed">
                {t("mainModelDescription")}
              </Text>
              <Card withBorder padding="sm">
                <Group justify="space-between" align="center">
                  <Stack gap={2}>
                    <Text fw={600}>
                      {mainModelPreview?.model_display_name ??
                        selectedModelSnapshot?.model_display_name ??
                        t("noModelSelected")}
                    </Text>
                    <Text size="sm" c="dimmed">
                      {mainModelPreview?.model_identifier ??
                        selectedModelSnapshot?.model_identifier ??
                        t("chooseModelDescription")}
                    </Text>
                  </Stack>
                  <Button
                    variant="light"
                    onClick={() => setMainPickerOpen(true)}
                  >
                    {t("changeModel")}
                  </Button>
                </Group>
              </Card>
              {form.values.model_selection_value != null &&
                mainModelPreview == null &&
                selectedModelSnapshot == null && (
                  <Alert color="yellow" title={t("selectedModelMissingTitle")}>
                    {t("selectedModelMissingDescription")}
                  </Alert>
                )}
              {form.errors.model_selection_value && (
                <Text size="sm" c="red">
                  {form.errors.model_selection_value}
                </Text>
              )}
            </Stack>
          )}

          {showModel && (
            <Stack gap="xs">
              <Text fw={500}>{t("lightweightModelLabel")}</Text>
              <Text size="sm" c="dimmed">
                {t("lightweightModelDescription")}
              </Text>
              <Card withBorder padding="sm">
                <Group justify="space-between" align="center">
                  <Stack gap={2}>
                    <Text fw={600}>
                      {lightweightModelPreview?.model_display_name ??
                        selectedLightweightModelSnapshot?.model_display_name ??
                        t("useMainOrWorkspaceDefault")}
                    </Text>
                    <Text size="sm" c="dimmed">
                      {lightweightModelPreview?.model_identifier ??
                        selectedLightweightModelSnapshot?.model_identifier ??
                        t("optionalLightweightModel")}
                    </Text>
                  </Stack>
                  <Button
                    variant="light"
                    onClick={() => setLightweightPickerOpen(true)}
                  >
                    {t("changeModel")}
                  </Button>
                </Group>
              </Card>
            </Stack>
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
