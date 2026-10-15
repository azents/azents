"use client";
import {
  outputFileState,
  toolCallForDisplay,
} from "@azents/session-core/delegatedToolPresentation";
import { Component } from "react";
import { BrowserToolResultLink } from "@/features/session-browser/BrowserToolResultLink";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import {
  GenericToolCallCard,
  StandardSpecializedToolCallCard,
} from "../components/ToolCallCard";
import { knownToolPresentation } from "../knownToolPresentation";
import { useRawToolDialog } from "./useRawToolDialog";
import type {
  GenericToolCallCardViewProps,
  StandardToolCallCardInput,
  StandardToolCallCardViewProps,
  ToolCallCardInput,
} from "../types";
import type { ReactElement, ReactNode } from "react";

interface SpecializedToolCallBoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
  resetKey: string;
}

interface SpecializedToolCallBoundaryState {
  failed: boolean;
}

class SpecializedToolCallBoundary extends Component<
  SpecializedToolCallBoundaryProps,
  SpecializedToolCallBoundaryState
> {
  public state: SpecializedToolCallBoundaryState = { failed: false };

  public static getDerivedStateFromError(): SpecializedToolCallBoundaryState {
    return { failed: true };
  }

  public componentDidUpdate(
    previousProps: SpecializedToolCallBoundaryProps,
  ): void {
    if (this.state.failed && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  public render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function useGenericToolCallCard({
  hiddenAttachmentUris = [],
  ...props
}: ToolCallCardInput): GenericToolCallCardViewProps {
  return {
    ...props,
    rawToolCall: props.toolCall,
    toolCall: toolCallForDisplay(props.toolCall),
    outputFileState: outputFileState(props.toolCall),
    hiddenAttachmentUris,
    ...useRawToolDialog(),
  };
}
function useStandardToolCallCard({
  hiddenAttachmentUris = [],
  ...props
}: StandardToolCallCardInput): StandardToolCallCardViewProps {
  return {
    ...props,
    rawToolCall: props.toolCall,
    toolCall: toolCallForDisplay(props.toolCall),
    outputFileState: outputFileState(props.toolCall),
    hiddenAttachmentUris,
    ...useRawToolDialog(),
  };
}
const GenericCard = createReactContainer(
  "GenericToolCallCard",
  useGenericToolCallCard,
  GenericToolCallCard,
);
const StandardCard = createReactContainer(
  "StandardSpecializedToolCallCard",
  useStandardToolCallCard,
  StandardSpecializedToolCallCard,
);

export function ToolCallCardContainer({
  toolCall,
  hiddenAttachmentUris = [],
}: ToolCallCardInput): ReactElement {
  const result = knownToolPresentation(toolCallForDisplay(toolCall));
  const generic = (
    <GenericCard
      toolCall={toolCall}
      hiddenAttachmentUris={hiddenAttachmentUris}
    />
  );
  if (result.type === "generic") {
    return (
      <>
        {generic}
        {toolCall.status === "completed" &&
          ["browser_open", "browser_observe", "browser_act"].includes(
            toolCall.name,
          ) && (
            <BrowserToolResultLink
              name={toolCall.name}
              result={toolCall.result ?? null}
            />
          )}
      </>
    );
  }
  return (
    <SpecializedToolCallBoundary
      resetKey={`${toolCall.id}:${toolCall.status}:${toolCall.result ?? ""}`}
      fallback={generic}
    >
      <StandardCard
        toolCall={toolCall}
        presentation={result.presentation}
        hiddenAttachmentUris={hiddenAttachmentUris}
      />
    </SpecializedToolCallBoundary>
  );
}
