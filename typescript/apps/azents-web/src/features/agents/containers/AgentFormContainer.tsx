"use client";

import { useForm } from "@mantine/form";
import { useEffect, useMemo, useState } from "react";
import {
  normalizeReasoningEffort,
  reasoningEffortLevels,
} from "@/shared/lib/reasoning-effort";
import { AgentForm } from "../components/AgentForm";
import {
  findSelectableModelOptionByLabel,
  selectableModelOptionFormValuesFromStoredOptions,
} from "../model-selection";
import { agentFormSchema } from "../schemas";
import { useAgentFormTranslations } from "./useAgentFormTranslations";
import type { AgentFormProps } from "../components/AgentForm";
import type { AgentFormValues } from "../schemas";

const initialValues: AgentFormValues = {
  name: "",
  description: "",
  selectable_model_options: [],
  main_model_label: null,
  lightweight_model_label: null,
  system_prompt: "",
  runtime_profile_id: null,
  type: "public",
  enabled: true,
  reasoning_effort: null,
  terminal_enabled: true,
  memory_enabled: true,
  tool_search_enabled: true,
  max_turns: null,
  auto_archive_ttl_days: 30,
  subagent_max_subagents: 3,
  subagent_max_depth: 1,
};

export function AgentFormContainer(props: AgentFormProps): React.ReactElement {
  const t = useAgentFormTranslations();
  const [hasSubmitAttempted, setHasSubmitAttempted] = useState(false);
  const form = useForm<AgentFormValues>({
    mode: "controlled",
    initialValues,
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

  useEffect(() => {
    if (props.formState.type === "EDIT") {
      const agent = props.formState.agent;
      const mainOption = agent.selectable_model_options.find(
        (option) => option.label === agent.main_model_label,
      );
      const defaultReasoningEffort = normalizeReasoningEffort(
        agent.model_parameters?.reasoning_effort ?? null,
        reasoningEffortLevels(
          mainOption?.model_selection.normalized_capabilities,
        ),
      );
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
        runtime_profile_id: agent.runtime_profile_id,
        type: agent.type,
        enabled: agent.enabled,
        reasoning_effort: defaultReasoningEffort,
        terminal_enabled: agent.terminal_enabled,
        memory_enabled: agent.memory_enabled,
        tool_search_enabled: agent.tool_search_enabled,
        max_turns: agent.max_turns ?? null,
        auto_archive_ttl_days: agent.auto_archive_ttl_days,
        subagent_max_subagents: agent.subagent_settings.max_subagents ?? 3,
        subagent_max_depth: agent.subagent_settings.max_depth ?? 1,
      });
      form.resetDirty();
      setHasSubmitAttempted(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the loaded Agent changes form mode.
  }, [props.formState.type]);

  useEffect(() => {
    if (
      props.formState.type !== "CREATE" ||
      props.workspaceModelSettings == null ||
      form.isDirty()
    ) {
      return;
    }
    const selectableModelOptions =
      selectableModelOptionFormValuesFromStoredOptions(
        props.workspaceModelSettings.default_selectable_model_options ?? [],
      );
    const mainModelLabel =
      props.workspaceModelSettings.default_main_model_label ?? null;
    const mainOption = findSelectableModelOptionByLabel(
      selectableModelOptions,
      mainModelLabel,
    );
    form.setValues({
      selectable_model_options: selectableModelOptions,
      main_model_label: mainModelLabel,
      lightweight_model_label:
        props.workspaceModelSettings.default_lightweight_model_label ?? null,
      reasoning_effort: normalizeReasoningEffort(
        null,
        reasoningEffortLevels(mainOption?.normalized_capabilities),
      ),
    });
    form.resetDirty();
    setHasSubmitAttempted(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resynchronize create defaults before user edits.
  }, [props.formState.type, props.workspaceModelSettings]);

  const selectedMainModelOption = findSelectableModelOptionByLabel(
    form.values.selectable_model_options,
    form.values.main_model_label,
  );
  const selectedModelEffortLevels = useMemo(
    () =>
      reasoningEffortLevels(
        selectedMainModelOption?.normalized_capabilities ?? null,
      ),
    [selectedMainModelOption?.normalized_capabilities],
  );

  useEffect(() => {
    const normalizedEffort = normalizeReasoningEffort(
      form.values.reasoning_effort ?? null,
      selectedModelEffortLevels,
    );
    if (form.values.reasoning_effort !== normalizedEffort) {
      form.setFieldValue("reasoning_effort", normalizedEffort);
    }
  }, [form, form.values.reasoning_effort, selectedModelEffortLevels]);

  return (
    <AgentForm
      {...props}
      t={t}
      form={form}
      hasSubmitAttempted={hasSubmitAttempted}
      onSubmitAttempted={() => setHasSubmitAttempted(true)}
      selectedModelEffortLevels={selectedModelEffortLevels}
    />
  );
}
