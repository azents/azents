"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { trpc } from "@/trpc/client";
import type { AgentResponse } from "@azents/public-client";

interface AgentLifecycleInput {
  handle: string;
  agentId: string;
  initialAgent?: AgentResponse;
}

interface AgentLifecycleView {
  agent?: AgentResponse;
  readOnly: boolean;
}

export function useAgentLifecycle({
  handle,
  agentId,
  initialAgent,
}: AgentLifecycleInput): AgentLifecycleView {
  const router = useRouter();
  const query = trpc.agent.get.useQuery(
    { handle, agentId },
    {
      initialData: initialAgent,
      refetchOnWindowFocus: true,
      refetchIntervalInBackground: false,
      refetchInterval: (current) =>
        current.state.error?.data?.code === "NOT_FOUND"
          ? false
          : current.state.data?.deletion_status != null
            ? 5000
            : false,
      retry: (count, error) => error.data?.code !== "NOT_FOUND" && count < 3,
    },
  );
  useEffect(() => {
    if (query.error?.data?.code === "NOT_FOUND") {
      router.replace(`/w/${encodeURIComponent(handle)}/agents`);
    }
  }, [handle, query.error, router]);
  const agent = query.data ?? initialAgent;
  return {
    ...(agent ? { agent } : {}),
    readOnly: agent == null || agent.deletion_status !== null,
  };
}
