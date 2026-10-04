"use client";

import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import {
  hasDuplicateSelectableModelCandidates,
  hasInvalidImageGenerationSelections,
  selectableModelOptionFormValuesFromStoredOptions,
} from "@/shared/model-options/model-selection";
import type {
  ImageGenerationCatalogState,
  ProviderIntegrationOption,
  SelectableModelOptionFormValue,
} from "@/shared/model-options/model-selection";
import type { WorkspaceModelSettingsResponse } from "@azents/public-client";
import type { UseFormReturnType } from "@mantine/form";
import type { FormEventHandler } from "react";

export interface WorkspaceModelSettingsFormValues {
  defaultSelectableModelOptions: SelectableModelOptionFormValue[];
  defaultMainModelLabel: string | null;
  defaultLightweightModelLabel: string | null;
}

export interface WorkspaceModelSettingsCardContainerProps {
  settings: WorkspaceModelSettingsResponse | null;
  handle: string;
  providerOptions: ProviderIntegrationOption[];
  canManage: boolean;
  submitting: boolean;
  error: string | null;
  onSyncCatalog: (integrationId: string) => Promise<void>;
  onSubmit: (values: WorkspaceModelSettingsFormValues) => void;
}

export interface WorkspaceModelSettingsCardForm {
  form: UseFormReturnType<WorkspaceModelSettingsFormValues>;
  hasSubmitAttempted: boolean;
  submit: (
    imageCatalogStates: ReadonlyMap<string, ImageGenerationCatalogState>,
  ) => FormEventHandler<HTMLFormElement>;
}

export function useWorkspaceModelSettingsCardForm({
  settings,
  onSubmit,
}: WorkspaceModelSettingsCardContainerProps): WorkspaceModelSettingsCardForm {
  const t = useTranslations("workspace.llmSettings.modelSelection");
  const [hasSubmitAttempted, setHasSubmitAttempted] = useState(false);
  const form = useForm<WorkspaceModelSettingsFormValues>({
    mode: "controlled",
    initialValues: {
      defaultSelectableModelOptions: [],
      defaultMainModelLabel: null,
      defaultLightweightModelLabel: null,
    },
    validate: (values) => {
      const hasEmptyLabel = values.defaultSelectableModelOptions.some(
        (option) => option.label.trim().length === 0,
      );
      const labels = values.defaultSelectableModelOptions.map((option) =>
        option.label.trim(),
      );
      const uniqueLabels = new Set(labels);
      const hasMissingModel = values.defaultSelectableModelOptions.some(
        (option) =>
          option.candidates.length === 0 ||
          option.candidates.some(
            (candidate) => candidate.model_selection_value == null,
          ),
      );
      if (
        values.defaultSelectableModelOptions.length === 0 ||
        hasEmptyLabel ||
        uniqueLabels.size !== labels.length ||
        hasMissingModel ||
        hasDuplicateSelectableModelCandidates(
          values.defaultSelectableModelOptions,
        )
      ) {
        return { defaultSelectableModelOptions: t("invalidOptions") };
      }
      return {};
    },
  });

  useEffect(() => {
    form.setValues({
      defaultSelectableModelOptions:
        selectableModelOptionFormValuesFromStoredOptions(
          settings?.default_selectable_model_options ?? [],
        ),
      defaultMainModelLabel: settings?.default_main_model_label ?? null,
      defaultLightweightModelLabel:
        settings?.default_lightweight_model_label ?? null,
    });
    form.resetDirty();
    setHasSubmitAttempted(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Resynchronize form when server settings change.
  }, [settings]);

  const submit = (
    imageCatalogStates: ReadonlyMap<string, ImageGenerationCatalogState>,
  ): FormEventHandler<HTMLFormElement> =>
    form.onSubmit(
      (values) => {
        setHasSubmitAttempted(true);
        if (
          hasInvalidImageGenerationSelections(
            values.defaultSelectableModelOptions,
            imageCatalogStates,
          )
        ) {
          return;
        }
        onSubmit(values);
      },
      () => setHasSubmitAttempted(true),
    );
  return { form, hasSubmitAttempted, submit };
}
