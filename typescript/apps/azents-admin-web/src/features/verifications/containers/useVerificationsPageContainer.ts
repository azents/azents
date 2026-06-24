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
 * Verifications 페이지 컨테이너 훅
 *
 * URL 쿼리 상태로 선택된 verification ID를 관리합니다.
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
