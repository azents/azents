"use client";

import { trpc } from "@/trpc/client";
import type { UserListState, UserResponse } from "../types";

export interface UserListContainerProps {
  selectedUserId: string | null;
  onRowClick: (user: UserResponse) => void;
}

export interface UserListComponentProps {
  state: UserListState;
  selectedUserId: string | null;
  onRowClick: (user: UserResponse) => void;
}

/**
 * User 목록 컨테이너 훅
 *
 * tRPC를 사용하여 user 목록을 서버사이드에서 가져오고 ADT로 변환합니다.
 */
export function useUserListContainer(
  props: UserListContainerProps,
): UserListComponentProps {
  const { data, isLoading, isError, error } = trpc.user.list.useQuery();

  const state: UserListState = isLoading
    ? { type: "LOADING" }
    : isError
      ? {
          type: "ERROR",
          message: error.message,
        }
      : {
          type: "LOADED",
          users: data?.items ?? [],
        };

  return {
    state,
    selectedUserId: props.selectedUserId,
    onRowClick: props.onRowClick,
  };
}
