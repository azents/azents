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
 * Users page container hook
 *
 * Manages the selected user through URL query state.
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
