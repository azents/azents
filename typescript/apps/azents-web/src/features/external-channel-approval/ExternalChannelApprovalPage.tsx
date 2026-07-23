"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ExternalChannelApproval } from "./components/ExternalChannelApproval";
import { useExternalChannelApprovalContainer } from "./containers/useExternalChannelApprovalContainer";

export const ExternalChannelApprovalPage = createReactContainer(
  "ExternalChannelApprovalPage",
  useExternalChannelApprovalContainer,
  ExternalChannelApproval,
);
