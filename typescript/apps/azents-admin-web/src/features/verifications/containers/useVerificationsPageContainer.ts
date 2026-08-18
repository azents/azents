"use client";

import { useCallback } from "react";
import { serializers, useQueryState } from "@/hooks/use-query-state";
import type { EmailVerificationResponse } from "../types";

export interface VerificationsPageContentProps {
  selectedVerificationId: string | null;
  onVerificationSelect: (verification: EmailVerificationResponse) => void;
  onDetailClose: () => void;
}

/**
 * Verifications page container hook
 *
 * Manages the selected verification ID through URL query state.
 */
export function useVerificationsPageContainer(): VerificationsPageContentProps {
  const [selectedVerificationId, setSelectedVerificationId] = useQueryState(
    "verificationId",
    {
      serializer: serializers.stringOrNull(),
    },
  );

  const handleVerificationSelect = useCallback(
    (verification: EmailVerificationResponse): void => {
      setSelectedVerificationId(verification.id);
    },
    [setSelectedVerificationId],
  );

  const handleDetailClose = useCallback((): void => {
    setSelectedVerificationId(null);
  }, [setSelectedVerificationId]);

  return {
    selectedVerificationId,
    onVerificationSelect: handleVerificationSelect,
    onDetailClose: handleDetailClose,
  };
}
