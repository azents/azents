"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useUserListContainer } from "../containers/useUserListContainer";
import { UserListView } from "./UserListView";
import type { UserListContainerProps } from "../containers/useUserListContainer";

/**
 * User list container component
 *
 * Connects the container hook to the view.
 */
export const UserList = createReactContainer<
  UserListContainerProps,
  ReturnType<typeof useUserListContainer>
>("UserList", useUserListContainer, UserListView);
