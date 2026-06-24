"use client";

import { useCallback } from "react";
import { serializers, useQueryState } from "@/hooks/use-query-state";
import type { UserResponse } from "../types";

export interface UsersPageContentProps {
  selectedUserId: string | null;
  onUserSelect: (user: UserResponse) => void;
  onDeleted: () => void;
  onDetailClose: () => void;
}

/**
 * Users 페이지 컨테이너 훅
 *
 * URL 쿼리 상태로 선택된 user를 관리합니다.
 */
export function useUsersPageContainer(): UsersPageContentProps {
  const [selectedUserId, setSelectedUserId] = useQueryState("userId", {
    serializer: serializers.stringOrNull(),
  });

  const handleUserSelect = useCallback(
    (user: UserResponse): void => {
      setSelectedUserId(user.id);
    },
    [setSelectedUserId],
  );

  const handleDeleted = useCallback((): void => {
    setSelectedUserId(null);
  }, [setSelectedUserId]);

  const handleDetailClose = useCallback((): void => {
    setSelectedUserId(null);
  }, [setSelectedUserId]);

  return {
    selectedUserId,
    onUserSelect: handleUserSelect,
    onDeleted: handleDeleted,
    onDetailClose: handleDetailClose,
  };
}
