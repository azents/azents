"use client";

import { useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type { RoutineDetailState, SessionRoutinesState } from "../types";
import type { AgentResponse } from "@azents/public-client";
import type { RefObject } from "react";

export interface SessionRoutinesContainerProps {
  agent: AgentResponse;
  sessionId: string;
}

export interface SessionRoutinesContainerOutput {
  state: SessionRoutinesState;
  detail: RoutineDetailState;
  selectedSlug: string | null;
  selectedTitle: string | null;
  detailHeading: RefObject<HTMLHeadingElement | null>;
  onSelect: (slug: string, trigger: HTMLElement) => void;
  onBack: () => void;
  onRefresh: () => void;
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
  const trigger = useRef<HTMLElement | null>(null);
  const detailHeading = useRef<HTMLHeadingElement | null>(null);
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

  useEffect(() => {
    if (selectedSlug !== null) {
      detailHeading.current?.focus();
    } else if (trigger.current?.isConnected) {
      trigger.current.focus();
      trigger.current = null;
    }
  }, [selectedSlug]);

  return {
    state,
    detail,
    selectedSlug,
    selectedTitle: selected?.content.title ?? null,
    detailHeading,
    onSelect: (slug, element) => {
      trigger.current = element;
      setSelection({ sessionId, slug });
    },
    onBack: () => setSelection(null),
    onRefresh: () => {
      void Promise.all([
        utils.routine.list.invalidate(input),
        utils.routine.detail.invalidate(input),
      ]);
    },
  };
}
