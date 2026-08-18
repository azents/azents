"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useVerificationListContainer } from "../containers/useVerificationListContainer";
import { VerificationListView } from "./VerificationListView";
import type { VerificationListContainerProps } from "../containers/useVerificationListContainer";

/**
 * Verification list container component
 *
 * Connects the container hook to the view.
 */
export const VerificationList = createReactContainer<
  VerificationListContainerProps,
  ReturnType<typeof useVerificationListContainer>
>("VerificationList", useVerificationListContainer, VerificationListView);
