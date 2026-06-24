"use client";

import { SessionProvider as NextAuthSessionProvider } from "next-auth/react";
import { useConfig } from "@/config/client";

export function SessionProvider({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  const config = useConfig();

  if (!config.authEnabled) {
    return <>{children}</>;
  }

  return <NextAuthSessionProvider>{children}</NextAuthSessionProvider>;
}
