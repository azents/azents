"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { HomePageContent } from "./components/HomePageContent";
import { useHomePageContainer } from "./containers/useHomePageContainer";

export const HomePage = createReactContainer(
  "HomePage",
  useHomePageContainer,
  HomePageContent,
);
