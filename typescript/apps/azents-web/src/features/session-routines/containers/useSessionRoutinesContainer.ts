"use client";

import { useState } from "react";
import { trpc } from "@/trpc/client";
import { useRoutinePanelNavigation } from "./useRoutinePanelNavigation";
import type { RoutineDetailState, SessionRoutinesState } from "../types";
import type { RoutinePanelNavigation } from "./useRoutinePanelNavigation";
import type { AgentResponse } from "@azents/public-client";

export interface SessionRoutinesContainerProps {
  agent: AgentResponse;
  sessionId: string;
}

export interface SessionRoutinesContainerOutput extends RoutinePanelNavigation {
  state: SessionRoutinesState;
  detail: RoutineDetailState;
  selectedSlug: string | null;
  selectedTitle: string | null;
}

export function useSessionRoutinesContainer({
  agent,
  sessionId,
}: SessionRoutinesContainerProps): SessionRoutinesContainerOutput {
  const utils = trpc.useUtils();
  const [selection, setSelection] = useState<{
    sessionId: string;
    slug: string;
  } | null>(null);
  const input = { agentId: agent.id, sessionId };
  const inventory = trpc.routine.list.useQuery(input);
  const selected =
    selection?.sessionId === sessionId
      ? (inventory.data?.items.find((item) => item.slug === selection.slug) ??
        null)
      : null;
  const selectedSlug = selected?.slug ?? null;
  const detailQuery = trpc.routine.detail.useQuery(
    { ...input, slug: selectedSlug ?? "" },
    { enabled: selectedSlug !== null },
  );
  const state: SessionRoutinesState = inventory.isPending
    ? { type: "LOADING" }
    : inventory.isError
      ? { type: "ERROR", message: inventory.error.message }
      : { type: "LOADED", items: inventory.data.items };
  const detail: RoutineDetailState =
    selectedSlug === null
      ? { type: "NONE" }
      : detailQuery.isPending
        ? { type: "LOADING" }
        : detailQuery.isError
          ? { type: "ERROR", message: detailQuery.error.message }
          : { type: "LOADED", data: detailQuery.data };

  const navigation = useRoutinePanelNavigation({
    selectedSlug,
    onSelect: (slug) => setSelection({ sessionId, slug }),
    onBack: () => setSelection(null),
    onRefresh: async () => {
      await Promise.all([
        utils.routine.list.invalidate(input, {}, { throwOnError: true }),
        utils.routine.detail.invalidate(
          input,
          {},
          {
            throwOnError: true,
          },
        ),
      ]);
    },
  });

  return {
    state,
    detail,
    selectedSlug,
    selectedTitle: selected?.content.title ?? null,
    ...navigation,
  };
}
