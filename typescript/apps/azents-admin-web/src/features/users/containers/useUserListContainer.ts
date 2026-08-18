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
 * User list container hook
 *
 * Fetches the user list server-side through tRPC and converts it to an ADT.
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
