"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useVerificationDetailContainer } from "../containers/useVerificationDetailContainer";
import { VerificationDetailView } from "./VerificationDetailView";
import type { VerificationDetailContainerProps } from "../containers/useVerificationDetailContainer";

/**
 * Verification detail container component
 *
 * Connects the container hook to the view.
 */
export const VerificationDetail = createReactContainer<
  VerificationDetailContainerProps,
  ReturnType<typeof useVerificationDetailContainer>
>("VerificationDetail", useVerificationDetailContainer, VerificationDetailView);
