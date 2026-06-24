"use client";

import { PasswordResetAdminView } from "../components/PasswordResetAdminView";
import { usePasswordResetAdminContainer } from "../containers/usePasswordResetAdminContainer";

export function PasswordResetAdminPage(): React.ReactElement {
  const container = usePasswordResetAdminContainer();
  return <PasswordResetAdminView {...container} />;
}
