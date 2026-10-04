"use client";

import { useTranslations } from "next-intl";
import { ModelCatalogPickerContainer } from "@/shared/model-options/containers/ModelCatalogPickerContainer";
import { SelectableModelOptionsEditorContainer } from "@/shared/model-options/containers/SelectableModelOptionsEditorContainer";
import { useImageGenerationCatalogs } from "@/shared/model-options/containers/useImageGenerationCatalogs";
import { WorkspaceModelSettingsCard } from "../components/WorkspaceModelSettingsCard";
import {
  useImageCatalogTransport,
  useModelCatalogQuery,
} from "./model-catalog-transport";
import { useWorkspaceModelSettingsCardForm } from "./useWorkspaceModelSettingsCardForm";
import type { WorkspaceModelSettingsCardContainerProps } from "./useWorkspaceModelSettingsCardForm";
import type { ModelCatalogPickerContainerProps } from "@/shared/model-options/containers/ModelCatalogPickerContainer";

function renderModelPicker(
  props: ModelCatalogPickerContainerProps,
): React.ReactNode {
  return (
    <ModelCatalogPickerContainer
      {...props}
      useCatalogQuery={useModelCatalogQuery}
    />
  );
}

export function WorkspaceModelSettingsCardContainer(
  props: WorkspaceModelSettingsCardContainerProps,
): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.modelSelection");
  const { form, hasSubmitAttempted, submit } =
    useWorkspaceModelSettingsCardForm(props);
  const imageCatalogs = useImageGenerationCatalogs(
    props.handle,
    form.values.defaultSelectableModelOptions,
    useImageCatalogTransport,
  );
  const modelOptionsEditor = (
    <SelectableModelOptionsEditorContainer
      handle={props.handle}
      title={t("optionsTitle")}
      description={t("optionsDescription")}
      options={form.values.defaultSelectableModelOptions}
      mainModelLabel={form.values.defaultMainModelLabel}
      lightweightModelLabel={form.values.defaultLightweightModelLabel}
      providerOptions={props.providerOptions}
      canEdit={props.canManage}
      showValidationErrors={hasSubmitAttempted}
      onSyncCatalog={props.onSyncCatalog}
      imageGenerationCatalogStates={imageCatalogs.states}
      canSyncImageCatalog={props.canManage}
      onSyncImageCatalog={imageCatalogs.onSync}
      onChangeOptions={(options) =>
        form.setFieldValue("defaultSelectableModelOptions", options)
      }
      onChangeMainModelLabel={(label) =>
        form.setFieldValue("defaultMainModelLabel", label)
      }
      onChangeLightweightModelLabel={(label) =>
        form.setFieldValue("defaultLightweightModelLabel", label)
      }
      renderModelPicker={renderModelPicker}
    />
  );
  return (
    <WorkspaceModelSettingsCard
      modelOptionsEditor={modelOptionsEditor}
      canManage={props.canManage}
      submitting={props.submitting}
      error={props.error}
      onSubmit={submit(imageCatalogs.states)}
    />
  );
}
