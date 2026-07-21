"use client";

import { useTranslations } from "next-intl";
/**
 * Member profile edit container
 *
 * Manages current user workspace profile fetch and update logic.
 */
import { useCallback, useState } from "react";
import { trpc } from "@/trpc/client";
import type { FormState, MemberProfileState } from "../types";

export interface MemberProfileContainerProps {
  handle: string;
  state: MemberProfileState;
  onSubmit: (name: string) => void;
  onResetForm: () => void;
}

export function useMemberProfileContainer(props: {
  handle: string;
}): MemberProfileContainerProps {
  const { handle } = props;
  const t = useTranslations("common");
  const [formState, setFormState] = useState<FormState>({ type: "IDLE" });

  const utils = trpc.useUtils();

  // Fetch profile
  const profileQuery = trpc.memberProfile.getMyProfile.useQuery(
    { handle },
    { retry: false },
  );

  // Update profile
  const updateMutation = trpc.memberProfile.updateMyProfile.useMutation({
    onSuccess: () => {
      setFormState({ type: "SUCCESS" });
      void utils.memberProfile.getMyProfile.invalidate({ handle });
    },
    onError: (error) => {
      setFormState({ type: "ERROR", message: error.message });
    },
  });

  const onSubmit = useCallback(
    (name: string): void => {
      setFormState({ type: "SUBMITTING" });
      updateMutation.mutate({ handle, name });
    },
    [handle, updateMutation],
  );

  const onResetForm = useCallback((): void => {
    setFormState({ type: "IDLE" });
  }, []);

  const data = profileQuery.data;

  const state: MemberProfileState = profileQuery.isLoading
    ? { type: "LOADING" }
    : profileQuery.isError || !data
      ? {
          type: "ERROR",
          message: profileQuery.error?.message ?? t("unknownError"),
        }
      : {
          type: "LOADED",
          profile: {
            id: data.id,
            name: data.name,
            role: data.role,
            createdAt: data.created_at,
            updatedAt: data.updated_at,
          },
          formState,
        };

  return { handle, state, onSubmit, onResetForm };
}
