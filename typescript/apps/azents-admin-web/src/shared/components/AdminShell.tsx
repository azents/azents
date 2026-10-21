"use client";

import {
  ActionIcon,
  Anchor,
  AppShell,
  Avatar,
  Box,
  Breadcrumbs,
  Burger,
  Divider,
  Drawer,
  Group,
  Menu,
  NavLink,
  Paper,
  rem,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconBrightnessAuto,
  IconCheck,
  IconLogout,
  IconMoon,
  IconSun,
} from "@tabler/icons-react";
import NextLink from "next/link";
import type {
  AdminLocation,
  AdminNavigationGroup,
} from "../lib/admin-navigation";

type ColorPreference = "light" | "dark" | "system";

export interface AdminShellProps {
  children: React.ReactNode;
  groups: AdminNavigationGroup[];
  location: AdminLocation;
  homeHref: string;
  opened: boolean;
  onToggleNavigation: () => void;
  onCloseNavigation: () => void;
  user: { name: string; avatar: string } | null;
  preference: ColorPreference;
  mode: "light" | "dark";
  onPreferenceChange: (value: ColorPreference) => void;
  onLogout: () => void;
}

function Navigation({
  groups,
  user,
  onCloseNavigation,
  onLogout,
}: Pick<
  AdminShellProps,
  "groups" | "user" | "onCloseNavigation" | "onLogout"
>): React.ReactElement {
  return (
    <Stack h="100%" gap="sm" p="sm">
      <ScrollArea style={{ flex: 1, minHeight: 0 }} type="auto">
        <Stack component="nav" aria-label="Admin navigation" gap="lg">
          {groups.map((group) => (
            <Stack key={group.label} gap="xs">
              <Text size="xs" fw={600} c="dimmed" px="sm">
                {group.label}
              </Text>
              <Stack gap={0}>
                {group.items.map(({ key, label, href, active, Icon }) => (
                  <NavLink
                    key={key}
                    component={NextLink}
                    href={href}
                    label={label}
                    active={active}
                    aria-current={active ? "page" : false}
                    leftSection={<Icon size={18} />}
                    onClick={onCloseNavigation}
                  />
                ))}
              </Stack>
            </Stack>
          ))}
        </Stack>
      </ScrollArea>
      <Divider />
      {user && (
        <Group gap="sm" wrap="nowrap" px="sm">
          <Avatar src={user.avatar} alt="" size="sm" />
          <Text size="sm" truncate>
            {user.name}
          </Text>
        </Group>
      )}
      <NavLink
        component="button"
        type="button"
        label="Sign out"
        leftSection={<IconLogout size={18} />}
        onClick={onLogout}
      />
    </Stack>
  );
}

export function AdminShell(props: AdminShellProps): React.ReactElement {
  const {
    children,
    location,
    homeHref,
    opened,
    onToggleNavigation,
    onCloseNavigation,
    preference,
    mode,
    onPreferenceChange,
  } = props;
  const ThemeIcon =
    preference === "system"
      ? IconBrightnessAuto
      : mode === "dark"
        ? IconMoon
        : IconSun;
  return (
    <AppShell
      header={{ height: rem(64) }}
      navbar={{
        width: rem(240),
        breakpoint: "sm",
        collapsed: { mobile: true },
      }}
      padding={{ base: "sm", sm: "md" }}
    >
      <AppShell.Header>
        <Group h="100%" px="md" wrap="nowrap" gap="md">
          <Burger
            opened={opened}
            onClick={onToggleNavigation}
            hiddenFrom="sm"
            size="sm"
            aria-label="Open admin navigation"
            aria-expanded={opened}
            aria-controls="admin-mobile-navigation"
          />
          <Anchor
            component={NextLink}
            href={homeHref}
            c="inherit"
            underline="never"
            visibleFrom="sm"
            w={rem(208)}
            style={{ flexShrink: 0 }}
          >
            <Text fw={700}>
              Azents{" "}
              <Text component="span" c="dimmed" fw={400}>
                Admin
              </Text>
            </Text>
          </Anchor>
          <Box style={{ flex: 1, minWidth: 0 }}>
            <Breadcrumbs visibleFrom="sm">
              <Text size="sm" c="dimmed">
                {location.group}
              </Text>
              <Text size="sm" fw={600} truncate>
                {location.label}
              </Text>
            </Breadcrumbs>
            <Text hiddenFrom="sm" size="sm" fw={600} truncate>
              {location.label}
            </Text>
          </Box>
          <Menu position="bottom-end">
            <Menu.Target>
              <ActionIcon variant="subtle" size="lg" aria-label="Color scheme">
                <ThemeIcon size={20} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              {(["light", "dark", "system"] as const).map((value) => (
                <Menu.Item
                  key={value}
                  rightSection={
                    preference === value ? <IconCheck size={16} /> : null
                  }
                  onClick={() => onPreferenceChange(value)}
                >
                  {value.charAt(0).toUpperCase() + value.slice(1)}
                </Menu.Item>
              ))}
            </Menu.Dropdown>
          </Menu>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar visibleFrom="sm">
        <Navigation {...props} />
      </AppShell.Navbar>
      <Drawer
        opened={opened}
        onClose={onCloseNavigation}
        title="Azents Admin"
        id="admin-mobile-navigation"
        hiddenFrom="sm"
        size="sm"
        padding="sm"
        styles={{
          content: { display: "flex", flexDirection: "column" },
          body: { flex: 1, minHeight: 0 },
        }}
      >
        <Navigation {...props} />
      </Drawer>
      <AppShell.Main
        style={{
          height: "100dvh",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <Paper
          withBorder
          radius="md"
          style={{ flex: 1, minHeight: 0, minWidth: 0, overflow: "auto" }}
        >
          <Box h="100%" style={{ minWidth: 0 }}>
            {children}
          </Box>
        </Paper>
      </AppShell.Main>
    </AppShell>
  );
}
