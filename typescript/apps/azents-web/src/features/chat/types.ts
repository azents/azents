import type { AgentResponse } from "@azents/public-client";
import type {
  ActiveToolCall,
  ProviderToolCall,
} from "@azents/session-core/types";

/** Agent list status */
export type AgentListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; agents: AgentResponse[] };

export interface RawToolDialogProps {
  rawOpened: boolean;
  onOpenRaw: () => void;
  onCloseRaw: () => void;
}
export interface ToolCallCardInput {
  toolCall: ActiveToolCall;
  hiddenAttachmentUris?: readonly string[];
}
export interface GenericToolCallCardViewProps extends RawToolDialogProps {
  toolCall: ActiveToolCall;
  rawToolCall?: ActiveToolCall;
  outputFileState?: OutputFileState | null;
  hiddenAttachmentUris: readonly string[];
}
export interface StandardToolCallCardInput extends ToolCallCardInput {
  presentation: KnownToolPresentation;
}
export interface StandardToolCallCardViewProps extends GenericToolCallCardViewProps {
  presentation: KnownToolPresentation;
}
export interface ProviderToolCallCardInput {
  toolCall: ProviderToolCall;
  hiddenAttachmentUris?: readonly string[];
}
export interface ProviderToolCallCardViewProps
  extends ProviderToolCallCardInput, RawToolDialogProps {}

import type { KnownToolPresentation } from "./knownToolPresentation";
import type { OutputFileState } from "@azents/session-core/delegatedToolPresentation";
