"use client";

import { AdminShell } from "./components/AdminShell";
import { useAdminShellContainer } from "./containers/useAdminShellContainer";
import { createReactContainer } from "./lib/createReactContainer";

export const AdminShellContainer = createReactContainer(
  "AdminShell",
  useAdminShellContainer,
  AdminShell,
);
