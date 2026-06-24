"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { BootstrapView } from "../components/BootstrapView";
import { useBootstrapContainer } from "../containers/useBootstrapContainer";

export const BootstrapPage = createReactContainer(
  "BootstrapPage",
  useBootstrapContainer,
  BootstrapView,
);
