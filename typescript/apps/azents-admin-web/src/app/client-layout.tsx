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
  IconBrightnessAuto,
  IconBug,
  IconBuilding,
  IconCheck,
  IconLinkPlus,
  IconLogout,
  IconMail,
  IconMoon,
  IconSun,
  IconUser,
  IconUsersGroup,
} from "@tabler/icons-react";
import NextLink from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

import { useConfig } from "@/config/client";
import { authProvider } from "@/providers/auth-provider";
import { ColorModeProvider, useColorMode } from "@/providers/color-mode";
import { dataProvider } from "@/providers/data-provider";
import { TRPCProvider } from "@/providers/trpc";

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
  const { mutate: logout } = useLogout();
  const config = useConfig();

  return (
    <>
      <AppShell.Section grow component={ScrollArea} pt="md">
        {RESOURCES.map((resource) => {
          const isActive = pathname.startsWith(`/${resource.name}`);
          return (
            <NavLink
              key={resource.name}
              component={NextLink}
              href={resource.list}
              label={resource.label}
              leftSection={resource.icon}
              active={isActive}
              variant="subtle"
              onClick={onNavigate}
            />
          );
        })}
      </AppShell.Section>
      {config.authEnabled && (
        <AppShell.Section p="md">
          <NavLink
            label="로그아웃"
            leftSection={<IconLogout size={20} />}
            onClick={() => logout()}
            variant="subtle"
          />
        </AppShell.Section>
      )}
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
        <Anchor component={NextLink} href="/" underline="never" c="inherit">
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
              라이트
            </Menu.Item>
            <Menu.Item
              leftSection={<IconMoon size={16} />}
              rightSection={
                preference === "dark" ? <IconCheck size={16} /> : null
              }
              onClick={() => handleSelect("dark")}
            >
              다크
            </Menu.Item>
            <Menu.Item
              leftSection={<IconBrightnessAuto size={16} />}
              rightSection={
                preference === "system" ? <IconCheck size={16} /> : null
              }
              onClick={() => handleSelect("system")}
            >
              시스템
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
  const config = useConfig();
  const pathname = usePathname();
  const isLoginPage = pathname === "/login";

  const content = isLoginPage ? (
    children
  ) : (
    <AdminLayout>{children}</AdminLayout>
  );

  return (
    <Refine
      routerProvider={routerProvider}
      dataProvider={dataProvider}
      {...(config.authEnabled && { authProvider })}
      resources={RESOURCES.map((r) => ({
        name: r.name,
        list: r.list,
        meta: { icon: r.icon, label: r.label },
      }))}
      options={{
        syncWithLocation: true,
        warnWhenUnsavedChanges: true,
        disableTelemetry: true,
      }}
    >
      {config.authEnabled && !isLoginPage ? (
        <Authenticated key="main" redirectOnFail="/login">
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
    <Suspense fallback={<div>로딩 중...</div>}>
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
