"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { SessionChannels } from "./components/SessionChannels";
import { useSessionChannelsContainer } from "./containers/useSessionChannelsContainer";

export const SessionChannelsPage = createReactContainer(
  "SessionChannelsPage",
  useSessionChannelsContainer,
  SessionChannels,
);
