"use client";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import type {
  RuntimeProfileDeletionErrorKind,
  RuntimeProfileDeletionState,
} from "../types";
import type { WorkspaceRuntimeProfileResponse } from "@azents/public-client";
interface RuntimeProfileDeleteModalProps {
  state: RuntimeProfileDeletionState;
  onClose: () => void;
  onConfirm: (profile: WorkspaceRuntimeProfileResponse) => void;
}

export interface RuntimeProfileDeleteModalViewProps {
  onClose: RuntimeProfileDeleteModalProps["onClose"];
  onConfirm: RuntimeProfileDeleteModalProps["onConfirm"];
  t: ReturnType<typeof useTranslations<"workspace.runtimeProfiles">>;
  profile: WorkspaceRuntimeProfileResponse | null;
  isSubmitting: boolean;
  confirmationName: string;
  setConfirmationName: React.Dispatch<React.SetStateAction<string>>;
  acknowledged: boolean;
  setAcknowledged: React.Dispatch<React.SetStateAction<boolean>>;
  isConfirmed: boolean;
  error: { kind: RuntimeProfileDeletionErrorKind; message: string } | null;
}
export function useRuntimeProfileDeleteModalController({
  state,
  onClose,
  onConfirm,
}: RuntimeProfileDeleteModalProps): RuntimeProfileDeleteModalViewProps {
  const t = useTranslations("workspace.runtimeProfiles");
  const profile = state.type === "CLOSED" ? null : state.profile;
  const isSubmitting = state.type === "SUBMITTING";
  const [confirmationName, setConfirmationName] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    setConfirmationName("");
    setAcknowledged(false);
  }, [profile?.id]);

  const isConfirmed =
    profile !== null &&
    confirmationName === profile.display_name &&
    acknowledged;
  const error = state.type === "CONFIRMING" ? state.error : null;
  return {
    onClose,
    onConfirm,
    t,
    profile,
    isSubmitting,
    confirmationName,
    setConfirmationName,
    acknowledged,
    setAcknowledged,
    isConfirmed,
    error,
  };
}
