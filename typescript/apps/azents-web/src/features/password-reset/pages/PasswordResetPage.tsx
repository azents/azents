"use client";

import { PasswordResetView } from "../components/PasswordResetView";
import { usePasswordResetContainer } from "../containers/usePasswordResetContainer";

export interface PasswordResetPageProps {
  token: string;
}

export function PasswordResetPage({
  token,
}: PasswordResetPageProps): React.ReactElement {
  const container = usePasswordResetContainer(token);
  return <PasswordResetView {...container} />;
}
