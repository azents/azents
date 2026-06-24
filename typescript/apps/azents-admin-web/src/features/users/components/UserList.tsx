"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useUserListContainer } from "../containers/useUserListContainer";
import { UserListView } from "./UserListView";
import type { UserListContainerProps } from "../containers/useUserListContainer";

/**
 * User 목록 컨테이너 컴포넌트
 *
 * 컨테이너 훅과 뷰를 연결합니다.
 */
export const UserList = createReactContainer<
  UserListContainerProps,
  ReturnType<typeof useUserListContainer>
>("UserList", useUserListContainer, UserListView);
