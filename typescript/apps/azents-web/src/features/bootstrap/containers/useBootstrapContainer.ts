"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { trpc } from "@/trpc/client";
import type { BootstrapFormValues, BootstrapState } from "../types";

export interface BootstrapContainerProps {
  state: BootstrapState;
  onSubmit: (values: BootstrapFormValues) => void;
}

export function useBootstrapContainer(): BootstrapContainerProps {
  const router = useRouter();
  const statusQuery = trpc.workspace.bootstrapStatus.useQuery();
  const bootstrapMutation = trpc.workspace.bootstrapFirstOwner.useMutation({
    onSuccess: () => {
      router.replace("/login");
      router.refresh();
    },
  });

  const state: BootstrapState = statusQuery.isLoading
    ? { type: "LOADING" }
    : !statusQuery.data?.available
      ? { type: "UNAVAILABLE" }
      : bootstrapMutation.isSuccess
        ? { type: "SUCCESS" }
        : {
            type: "READY",
            error: bootstrapMutation.error?.message ?? null,
            submitting: bootstrapMutation.isPending,
          };

  const onSubmit = useCallback(
    (values: BootstrapFormValues) => {
      bootstrapMutation.mutate(values);
    },
    [bootstrapMutation],
  );

  return { state, onSubmit };
}
