"use client";

/**
 * Account settings page entry point.
 */
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { Account } from "./components/Account";
import { useAccountContainer } from "./containers/useAccountContainer";

export const AccountPage = createReactContainer(
  "AccountPage",
  useAccountContainer,
  Account,
);
