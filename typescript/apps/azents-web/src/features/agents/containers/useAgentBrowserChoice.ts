"use client";

import { useState } from "react";
import { useAgentLifecycle } from "@/shared/agent-session/useAgentLifecycle";
import { trpc } from "@/trpc/client";
import type { AgentBrowserChoiceProps } from "../browserChoiceTypes";
import type { BrowserImplementation } from "@azents/public-client";

interface Draft {
  implementation: BrowserImplementation;
  expectedIntentId: string;
  retry: boolean;
}

export function useAgentBrowserChoice({
  handle,
  agentId,
  disabled,
}: {
  handle: string;
  agentId: string;
  disabled: boolean;
}): AgentBrowserChoiceProps {
  const utils = trpc.useUtils();
  const input = { handle, agentId };
  const { agent, readOnly } = useAgentLifecycle({ handle, agentId });
  const query = trpc.agent.getBrowserConfiguration.useQuery(input, {
    refetchInterval: (current): number | false => {
      switch (current.state.data?.state) {
        case "applying":
          return 2_000;
        case "offline":
          return 5_000;
        default:
          return false;
      }
    },
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const mutation = trpc.agent.replaceBrowserConfiguration.useMutation({
    onSuccess: async (configuration): Promise<void> => {
      setDraft(null);
      utils.agent.getBrowserConfiguration.setData(input, configuration);
      await Promise.all([
        utils.agent.getBrowserConfiguration.invalidate(input),
        utils.browser.invalidate(),
      ]);
    },
    onError: async (): Promise<void> => {
      setDraft(null);
      await utils.agent.getBrowserConfiguration.invalidate(input);
    },
  });
  const browserEnabled = agent?.browser_enabled === true;
  const canManage =
    browserEnabled &&
    !disabled &&
    !readOnly &&
    agent.toolkit_management_available === true;
  const begin = (
    implementation: BrowserImplementation,
    retry: boolean,
  ): void => {
    if (!canManage || mutation.isPending || !query.data) {
      return;
    }
    if (!retry && implementation === query.data.requested) {
      return;
    }
    mutation.reset();
    setDraft({ implementation, expectedIntentId: query.data.intent_id, retry });
  };
  return {
    state: query.isError
      ? { type: "ERROR", message: query.error.message }
      : !query.data
        ? { type: "LOADING" }
        : {
            type: "READY",
            configuration: query.data,
            browserEnabled,
            readOnly: !canManage,
            saving: mutation.isPending,
            confirmation: canManage ? (draft?.implementation ?? null) : null,
            error: mutation.error?.message ?? null,
          },
    onSelect: (implementation): void => begin(implementation, false),
    onCancel: (): void => {
      if (!mutation.isPending) {
        setDraft(null);
      }
    },
    onConfirm: (): void => {
      if (!canManage || !draft || mutation.isPending) {
        return;
      }
      mutation.mutate({ ...input, ...draft });
    },
    onRetry: (): void => {
      if (query.data?.state === "failed") {
        begin(query.data.requested, true);
      }
    },
    onRefresh: (): void => {
      void utils.agent.getBrowserConfiguration.invalidate(input);
    },
  };
}
