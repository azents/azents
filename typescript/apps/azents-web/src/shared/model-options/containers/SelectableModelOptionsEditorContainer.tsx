"use client";

import { useSortable } from "@dnd-kit/sortable";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import {
  OptionCard,
  SelectableModelOptionsEditor,
} from "../components/SelectableModelOptionsEditor";
import { updateCandidate } from "../model-option-editor";
import {
  selectCandidateIntegration,
  selectCandidateModel,
} from "../model-selection";
import { useSelectableModelOptionsEditor } from "./useSelectableModelOptionsEditor";
import type {
  OptionCardProps,
  SelectableModelOptionsEditorProps,
} from "../components/SelectableModelOptionsEditor";
import type { ModelCatalogPickerContainerProps } from "./ModelCatalogPickerContainer";
import type { ReactNode } from "react";

export interface SelectableModelOptionsEditorContainerProps extends SelectableModelOptionsEditorProps {
  renderModelPicker: (props: ModelCatalogPickerContainerProps) => ReactNode;
}

function SortableOptionCard(props: OptionCardProps): React.ReactElement {
  const sortable = useSortable({
    disabled: !props.canEdit,
    id: props.option.id,
  });
  return <OptionCard {...props} sortable={sortable} />;
}

export function SelectableModelOptionsEditorContainer({
  renderModelPicker,
  ...props
}: SelectableModelOptionsEditorContainerProps): React.ReactElement {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  const controller = useSelectableModelOptionsEditor(props);
  const { picker, pickerTarget, setPickerTarget, handleChangeOptions } =
    controller;
  const enabledProviderOptions = useMemo(
    () => props.providerOptions.filter((option) => !option.disabled),
    [props.providerOptions],
  );
  const modelPicker =
    picker == null
      ? null
      : renderModelPicker({
          opened: pickerTarget != null,
          title: t("selectModelTitle", {
            label: picker.option.label || t("newOption"),
          }),
          handle: props.handle,
          integrations: enabledProviderOptions,
          selectedIntegrationId: picker.candidate.model_provider_integration_id,
          selectedValue: picker.candidate.model_selection_value,
          onClose: () => setPickerTarget(null),
          onSelectIntegration: (integrationId) => {
            if (pickerTarget == null) {
              return;
            }
            handleChangeOptions(
              updateCandidate(props.options, pickerTarget, (candidate) =>
                selectCandidateIntegration(candidate, integrationId),
              ),
            );
          },
          onSelectModel: (model) => {
            if (pickerTarget == null) {
              return;
            }
            handleChangeOptions(
              updateCandidate(props.options, pickerTarget, (candidate) =>
                selectCandidateModel(candidate, model, {
                  reasoningEffort: props.reasoningEffort ?? null,
                }),
              ),
            );
          },
          onSyncCatalog: props.onSyncCatalog,
        });
  return (
    <SelectableModelOptionsEditor
      {...props}
      controller={controller}
      modelPicker={modelPicker}
      OptionCardComponent={SortableOptionCard}
    />
  );
}
