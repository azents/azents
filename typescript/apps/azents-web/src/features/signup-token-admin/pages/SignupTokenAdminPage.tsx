"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { SignupTokenAdminView } from "../components/SignupTokenAdminView";
import { useSignupTokenAdminContainer } from "../containers/useSignupTokenAdminContainer";

export const SignupTokenAdminPage = createReactContainer(
  "SignupTokenAdminPage",
  useSignupTokenAdminContainer,
  SignupTokenAdminView,
);
