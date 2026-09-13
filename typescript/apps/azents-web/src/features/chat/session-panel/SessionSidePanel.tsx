"use client";

import {
  ActionIcon,
  Box,
  Group,
  rem,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { IconChevronLeft, IconChevronRight, IconX } from "@tabler/icons-react";
import { useId } from "react";
import classes from "./SessionSidePanel.module.css";
import { useSessionPanelNavigation } from "./useSessionPanelNavigation";
import type { SessionPanelView } from "./sessionPanel";
import type { SessionPanelNavigation } from "./useSessionPanelNavigation";
import type { ReactElement, ReactNode } from "react";

export interface SessionPanelItem {
  id: SessionPanelView;
  label: string;
  icon: ReactNode;
}

export interface SessionSidePanelProps {
  items: readonly SessionPanelItem[];
  activeId: SessionPanelView;
  onSelect: (id: SessionPanelView) => void;
  onClose: () => void;
  title: string;
  closeLabel: string;
  previousTabsLabel: string;
  nextTabsLabel: string;
  mobile: boolean;
  children: ReactNode;
}

export function SessionSidePanelPresentation({
  items,
  activeId,
  onSelect,
  onClose,
  title,
  closeLabel,
  previousTabsLabel,
  nextTabsLabel,
  mobile,
  children,
  navigation,
  id,
}: SessionSidePanelProps & {
  navigation: SessionPanelNavigation;
  id: string;
}): ReactElement {
  return (
    <Box className={classes.panel} aria-label={title}>
      <Group
        px="sm"
        h={rem(40)}
        justify="space-between"
        wrap="nowrap"
        style={{
          flexShrink: 0,
          borderBottom: `${rem(1)} solid var(--mantine-color-default-border)`,
        }}
      >
        <Text data-session-panel-title size="sm" fw={600}>
          {title}
        </Text>
        <ActionIcon variant="subtle" onClick={onClose} aria-label={closeLabel}>
          <IconX size={rem(18)} />
        </ActionIcon>
      </Group>
      <div className={classes.body} data-mobile={mobile}>
        <div className={classes.strip}>
          <div
            className={classes.tabs}
            ref={navigation.viewportRef}
            onScroll={navigation.onScroll}
            role="tablist"
            aria-label={title}
            aria-orientation={mobile ? "horizontal" : "vertical"}
          >
            {items.map((item) => (
              <UnstyledButton
                key={item.id}
                className={classes.tab}
                role="tab"
                aria-label={item.label}
                id={`${id}-${item.id}`}
                aria-controls={`${id}-content`}
                aria-selected={item.id === activeId}
                tabIndex={item.id === activeId ? 0 : -1}
                onKeyDown={navigation.onTabKeyDown}
                onClick={() => onSelect(item.id)}
              >
                {item.icon}
                <span>{item.label}</span>
              </UnstyledButton>
            ))}
          </div>
          {navigation.canScrollPrevious && (
            <div className={`${classes.nudge} ${classes.previous}`}>
              <ActionIcon
                size="sm"
                variant="default"
                aria-label={previousTabsLabel}
                onClick={navigation.scrollPrevious}
              >
                <IconChevronLeft size={rem(16)} />
              </ActionIcon>
            </div>
          )}
          {navigation.canScrollNext && (
            <div className={`${classes.nudge} ${classes.next}`}>
              <ActionIcon
                size="sm"
                variant="default"
                aria-label={nextTabsLabel}
                onClick={navigation.scrollNext}
              >
                <IconChevronRight size={rem(16)} />
              </ActionIcon>
            </div>
          )}
        </div>
        <div
          className={classes.content}
          id={`${id}-content`}
          role="tabpanel"
          aria-labelledby={`${id}-${activeId}`}
        >
          {children}
        </div>
      </div>
    </Box>
  );
}

export function SessionSidePanel(props: SessionSidePanelProps): ReactElement {
  const navigation = useSessionPanelNavigation(props.activeId, props.mobile);
  const id = useId();
  return (
    <SessionSidePanelPresentation {...props} navigation={navigation} id={id} />
  );
}
