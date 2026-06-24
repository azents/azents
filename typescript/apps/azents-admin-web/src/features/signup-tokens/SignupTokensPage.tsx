"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { SignupTokensPageContent } from "./components/SignupTokensPageContent";
import { useSignupTokensPageContainer } from "./containers/useSignupTokensPageContainer";

export const SignupTokensPage = createReactContainer(
  "SignupTokensPage",
  useSignupTokensPageContainer,
  SignupTokensPageContent,
);
