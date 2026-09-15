"use client";

import { useRuntimeWebServicesContainer } from "@/features/runtime-web/containers/useRuntimeWebServicesContainer";
import { trpc } from "@/trpc/client";
import type { RuntimeWebServicesContainerOutput } from "@/features/runtime-web/containers/useRuntimeWebServicesContainer";
import type { AgentResponse } from "@azents/public-client";

export interface AgentRuntimeWebServicesContainerProps {
  handle: string;
  agent: AgentResponse;
}

export interface AgentRuntimeWebServicesContainerOutput extends AgentRuntimeWebServicesContainerProps {
  runtimeWebServices: RuntimeWebServicesContainerOutput;
}

export function useAgentRuntimeWebServicesContainer({
  handle,
  agent,
}: AgentRuntimeWebServicesContainerProps): AgentRuntimeWebServicesContainerOutput {
  const runtime = trpc.chat.getAgentRuntime.useQuery({
    handle,
    agentId: agent.id,
  });
  const managed = agent.runtime_capability === "managed";
  const runtimeWebServices = useRuntimeWebServicesContainer({
    handle,
    agentId: agent.id,
    enabled: managed,
    autoRefreshVisible: true,
    runtimeAvailable: runtime.data?.lifecycle?.availability === "ready",
  });
  return { handle, agent, runtimeWebServices };
}
