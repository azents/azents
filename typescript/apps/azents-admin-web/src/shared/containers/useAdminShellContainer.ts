"use client";

import { useMantineColorScheme } from "@mantine/core";
import { useDisclosure, useHash, useMediaQuery } from "@mantine/hooks";
import { useGetIdentity, useLogout } from "@refinedev/core";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useConfig } from "@/config/client";
import { useColorMode } from "@/providers/color-mode";
import { adminNavigation } from "../lib/admin-navigation";
import { getPublicRoutePath } from "../lib/auth-policy";
import type { AdminShellProps } from "../components/AdminShell";

interface UserIdentity {
  id: string;
  name: string;
  avatar: string;
}

export function useAdminShellContainer({
  children,
}: {
  children: React.ReactNode;
}): AdminShellProps {
  const pathname = usePathname();
  const [hash] = useHash();
  const { publicBaseUrl } = useConfig();
  const [opened, { toggle, close }] = useDisclosure();
  const isDesktop = useMediaQuery("(min-width: 48em)", true);
  useEffect(() => {
    if (isDesktop) {
      close();
    }
  }, [isDesktop, close]);
  const { mode, preference, setColorMode } = useColorMode();
  const { setColorScheme } = useMantineColorScheme();
  const { data: user } = useGetIdentity<UserIdentity>();
  const { mutate: logout } = useLogout();
  const navigation = adminNavigation(publicBaseUrl, pathname, hash);
  return {
    children,
    ...navigation,
    homeHref: getPublicRoutePath(publicBaseUrl, "/"),
    opened,
    onToggleNavigation: toggle,
    onCloseNavigation: close,
    user: user ? { name: user.name, avatar: user.avatar } : null,
    preference,
    mode,
    onPreferenceChange: (value) => {
      setColorMode(value);
      setColorScheme(value === "system" ? "auto" : value);
    },
    onLogout: () => logout(),
  };
}
