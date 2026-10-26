import type {
  AgentBrowserConfiguration,
  BrowserImplementation,
} from "@azents/public-client";

export type BrowserChoiceState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      configuration: AgentBrowserConfiguration;
      browserEnabled: boolean;
      readOnly: boolean;
      saving: boolean;
      confirmation: BrowserImplementation | null;
      error: string | null;
    };

export interface AgentBrowserChoiceProps {
  state: BrowserChoiceState;
  onSelect: (implementation: BrowserImplementation) => void;
  onCancel: () => void;
  onConfirm: () => void;
  onRetry: () => void;
  onRefresh: () => void;
}
