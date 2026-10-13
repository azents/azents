export interface RuntimeEnvironmentVariableDraft {
  id: string;
  name: string;
  value: string;
  hasStoredValue: boolean;
  nameError: string | null;
  valueError: string | null;
}

export type RuntimeEnvironmentEditorStatus =
  | { type: "UNCHANGED" }
  | { type: "DIRTY" }
  | { type: "SAVING" }
  | { type: "SAVED" }
  | { type: "ERROR"; message: string };

export type RuntimeEnvironmentVariablesState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      entries: RuntimeEnvironmentVariableDraft[];
      canManage: boolean;
      status: RuntimeEnvironmentEditorStatus;
    };

export interface RuntimeEnvironmentVariablesProps {
  state: RuntimeEnvironmentVariablesState;
  onAdd: () => void;
  onNameChange: (id: string, name: string) => void;
  onValueChange: (id: string, value: string) => void;
  onRemove: (id: string) => void;
  onDiscard: () => void;
  onSave: () => void;
  onRetry: () => void;
}
