"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useUserDetailContainer } from "../containers/useUserDetailContainer";
import { UserDetailView } from "./UserDetailView";
import type { UserDetailContainerProps } from "../containers/useUserDetailContainer";

/**
 * User 상세 컨테이너 컴포넌트
 *
 * 컨테이너 훅과 뷰를 연결합니다.
 */
export const UserDetail = createReactContainer<
  UserDetailContainerProps,
  ReturnType<typeof useUserDetailContainer>
>("UserDetail", useUserDetailContainer, UserDetailView);
