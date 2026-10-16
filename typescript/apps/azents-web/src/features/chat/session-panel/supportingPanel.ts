import type { SessionPanelState } from "./useSessionPanelState";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";
import type { ReactNode } from "react";

export interface SupportingPanelProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  session: AgentSessionResponse;
  panel: SessionPanelState;
}
export type SupportingPanelRenderer = (
  props: SupportingPanelProps,
) => ReactNode;
