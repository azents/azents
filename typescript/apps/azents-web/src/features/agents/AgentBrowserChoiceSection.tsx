"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentBrowserChoice } from "./components/AgentBrowserChoice";
import { useAgentBrowserChoice } from "./containers/useAgentBrowserChoice";

export const AgentBrowserChoiceSection = createReactContainer(
  "AgentBrowserChoiceSection",
  useAgentBrowserChoice,
  AgentBrowserChoice,
);
