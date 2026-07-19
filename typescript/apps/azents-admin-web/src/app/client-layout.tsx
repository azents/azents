"use client";

import {
  ActionIcon,
  Anchor,
  AppShell,
  Avatar,
  Burger,
  Group,
  Menu,
  NavLink,
  ScrollArea,
  Text,
  Title,
  useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  Authenticated,
  Refine,
  useGetIdentity,
  useLogout,
} from "@refinedev/core";
import routerProvider from "@refinedev/nextjs-router";
import {
  IconArchive,
  IconBrightnessAuto,
  IconBug,
  IconBuilding,
  IconCheck,
  IconLinkPlus,
  IconLogout,
  IconMail,
  IconMoon,
  IconRefresh,
  IconSun,
  IconUser,
  IconUsersGroup,
} from "@tabler/icons-react";
import NextLink from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useMemo } from "react";

import { useConfig } from "@/config/client";
import { createAuthProvider } from "@/providers/auth-provider";
import { ColorModeProvider, useColorMode } from "@/providers/color-mode";
import { dataProvider } from "@/providers/data-provider";
import { TRPCProvider } from "@/providers/trpc";
import { getPublicRoutePath } from "@/shared/lib/auth-policy";

type ColorModePreference = "light" | "dark" | "system";

interface UserIdentity {
  id: string;
  name: string;
  avatar: string;
}

interface ResourceItem {
  name: string;
  list: string;
  icon: React.ReactNode;
  label: string;
}

const RESOURCES: ResourceItem[] = [
  {
    name: "workspaces",
    list: "/workspaces",
    icon: <IconBuilding size={20} />,
    label: "Workspaces",
  },
  {
    name: "users",
    list: "/users",
    icon: <IconUser size={20} />,
    label: "Users",
  },
  {
    name: "workspace-members",
    list: "/workspace-members",
    icon: <IconUsersGroup size={20} />,
    label: "Workspace Members",
  },
  {
    name: "verifications",
    list: "/verifications",
    icon: <IconMail size={20} />,
    label: "Email Verifications",
  },
  {
    name: "signup-tokens",
    list: "/signup-tokens",
    icon: <IconLinkPlus size={20} />,
    label: "Signup Links",
  },
  {
    name: "model-catalog",
    list: "/model-catalog",
    icon: <IconRefresh size={20} />,
    label: "Model Catalog",
  },
  {
    name: "retention",
    list: "/retention",
    icon: <IconArchive size={20} />,
    label: "Retention",
  },
  {
    name: "debug",
    list: "/debug",
    icon: <IconBug size={20} />,
    label: "Debug",
  },
];

function Sidebar({
  onNavigate,
}: {
  onNavigate?: () => void;
}): React.ReactElement {
  const pathname = usePathname();
  const { publicBaseUrl } = useConfig();
  const { mutate: logout } = useLogout();

  return (
    <>
      <AppShell.Section grow component={ScrollArea} pt="md">
        {RESOURCES.map((resource) => {
          const listPath = getPublicRoutePath(publicBaseUrl, resource.list);
          const isActive =
            pathname.startsWith(listPath) || pathname.startsWith(resource.list);
          return (
            <NavLink
              key={resource.name}
              component={NextLink}
              href={listPath}
              label={resource.label}
              leftSection={resource.icon}
              active={isActive}
              variant="subtle"
              onClick={onNavigate}
            />
          );
        })}
      </AppShell.Section>
      <AppShell.Section p="md">
        <NavLink
          label="Sign out"
          leftSection={<IconLogout size={20} />}
          onClick={() => logout()}
          variant="subtle"
        />
      </AppShell.Section>
    </>
  );
}

function Header({
  opened,
  toggle,
}: {
  opened: boolean;
  toggle: () => void;
}): React.ReactElement {
  const { publicBaseUrl } = useConfig();
  const { mode, preference, setColorMode } = useColorMode();
  const { setColorScheme } = useMantineColorScheme();
  const { data: user } = useGetIdentity<UserIdentity>();

  const handleSelect = (newPreference: ColorModePreference): void => {
    setColorMode(newPreference);
    if (newPreference === "system") {
      setColorScheme("auto");
    } else {
      setColorScheme(newPreference);
    }
  };

  const getCurrentIcon = (): React.ReactElement => {
    if (preference === "system") {
      return <IconBrightnessAuto size={20} />;
    }
    return mode === "dark" ? <IconMoon size={20} /> : <IconSun size={20} />;
  };

  return (
    <Group h="100%" px="md" justify="space-between">
      <Group>
        <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
        <Anchor
          component={NextLink}
          href={getPublicRoutePath(publicBaseUrl, "/")}
          underline="never"
          c="inherit"
        >
          <Group gap="sm">
            <Text fw={700} size="lg">
              AZ
            </Text>
            <Title order={4}>Azents Admin</Title>
          </Group>
        </Anchor>
      </Group>
      <Group>
        <Menu shadow="md" width={200}>
          <Menu.Target>
            <ActionIcon variant="subtle" size="lg">
              {getCurrentIcon()}
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item
              leftSection={<IconSun size={16} />}
              rightSection={
                preference === "light" ? <IconCheck size={16} /> : null
              }
              onClick={() => handleSelect("light")}
            >
              Light
            </Menu.Item>
            <Menu.Item
              leftSection={<IconMoon size={16} />}
              rightSection={
                preference === "dark" ? <IconCheck size={16} /> : null
              }
              onClick={() => handleSelect("dark")}
            >
              Dark
            </Menu.Item>
            <Menu.Item
              leftSection={<IconBrightnessAuto size={16} />}
              rightSection={
                preference === "system" ? <IconCheck size={16} /> : null
              }
              onClick={() => handleSelect("system")}
            >
              System
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
        {user && <Avatar src={user.avatar} alt={user.name} size="sm" />}
      </Group>
    </Group>
  );
}

function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  const [opened, { toggle, close }] = useDisclosure();

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{
        width: 250,
        breakpoint: "sm",
        collapsed: { mobile: !opened },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Header opened={opened} toggle={toggle} />
      </AppShell.Header>
      <AppShell.Navbar>
        <Sidebar onNavigate={close} />
      </AppShell.Navbar>
      <AppShell.Main
        style={{
          height: "calc(100vh - 60px)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ flex: 1, minHeight: 0 }}>{children}</div>
      </AppShell.Main>
    </AppShell>
  );
}

function AppContent({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  const pathname = usePathname();
  const { publicBaseUrl } = useConfig();
  const loginPath = getPublicRoutePath(publicBaseUrl, "/login");
  const isLoginPage = pathname === loginPath || pathname === "/login";
  const authProvider = useMemo(
    () => createAuthProvider(publicBaseUrl),
    [publicBaseUrl],
  );

  const content = isLoginPage ? (
    children
  ) : (
    <AdminLayout>{children}</AdminLayout>
  );

  return (
    <Refine
      routerProvider={routerProvider}
      dataProvider={dataProvider}
      authProvider={authProvider}
      resources={RESOURCES.map((resource) => ({
        name: resource.name,
        list: getPublicRoutePath(publicBaseUrl, resource.list),
        meta: { icon: resource.icon, label: resource.label },
      }))}
      options={{
        syncWithLocation: true,
        warnWhenUnsavedChanges: true,
        disableTelemetry: true,
      }}
    >
      {!isLoginPage ? (
        <Authenticated key="main" redirectOnFail={loginPath}>
          {content}
        </Authenticated>
      ) : (
        content
      )}
    </Refine>
  );
}

type ColorMode = "light" | "dark";

interface ClientLayoutProps {
  children: React.ReactNode;
  initialPreference: ColorModePreference;
  initialResolvedMode: ColorMode;
}

export function ClientLayout({
  children,
  initialPreference,
  initialResolvedMode,
}: ClientLayoutProps): React.ReactElement {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <TRPCProvider>
        <ColorModeProvider
          initialPreference={initialPreference}
          initialResolvedMode={initialResolvedMode}
        >
          <AppContent>{children}</AppContent>
        </ColorModeProvider>
      </TRPCProvider>
    </Suspense>
  );
}
