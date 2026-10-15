"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { SessionBrowserPanel } from "./components/SessionBrowserPanel";
import { useSessionBrowserContainer } from "./containers/useSessionBrowserContainer";

export const SessionBrowserPage = createReactContainer(
  "SessionBrowserPage",
  useSessionBrowserContainer,
  SessionBrowserPanel,
);
