"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useUserDetailContainer } from "../containers/useUserDetailContainer";
import { UserDetailView } from "./UserDetailView";
import type { UserDetailContainerProps } from "../containers/useUserDetailContainer";

/**
 * User detail container component
 *
 * Connects the container hook to the view.
 */
export const UserDetail = createReactContainer<
  UserDetailContainerProps,
  ReturnType<typeof useUserDetailContainer>
>("UserDetail", useUserDetailContainer, UserDetailView);
