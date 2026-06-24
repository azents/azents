"use client";

/**
 * Toolkit setup redirect container hook.
 *
 * Calls trpc.toolkit.connectOauth on mount
 * and redirects to OAuth authorization URL.
 * To bypass external provider button URL length limits,
 * use short web app URL → server creates OAuth URL → redirect flow.
 */

import { useEffect, useRef } from "react";
import { trpc } from "@/trpc/client";
import type { ToolkitSetupState } from "../types";

export interface ToolkitSetupContainerProps {
  handle: string;
  toolkitId: string;
}

export interface ToolkitSetupContainerOutput {
  state: ToolkitSetupState;
}

export function useToolkitSetupContainer(
  props: ToolkitSetupContainerProps,
): ToolkitSetupContainerOutput {
  const { handle, toolkitId } = props;
  const started = useRef(false);

  const mutation = trpc.toolkit.connectOauth.useMutation();

  useEffect(() => {
    if (started.current) {
      return;
    }
    started.current = true;

    mutation.mutate(
      { handle, toolkitConfigId: toolkitId },
      {
        onSuccess: (data) => {
          window.location.href = data.authorization_url;
        },
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mutation has a new reference every render, so exclude from dependencies
  }, [handle, toolkitId]);

  const state: ToolkitSetupState = mutation.isError
    ? { type: "ERROR", message: mutation.error.message }
    : { type: "REDIRECTING" };

  return { state };
}
