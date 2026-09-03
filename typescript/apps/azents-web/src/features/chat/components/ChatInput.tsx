"use client";

import {
  ActionIcon,
  Box,
  Button,
  Divider,
  Drawer,
  Group,
  Paper,
  Popover,
  rem,
  Stack,
  Text,
  Textarea,
  UnstyledButton,
} from "@mantine/core";
import {
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconPaperclip,
  IconPlayerStop,
  IconSend,
  IconX,
} from "@tabler/icons-react";
import { memo } from "react";
import { AttachmentPreviewBarContainer } from "../containers/AttachmentPreviewBarContainer";
import { useChatInputContainer } from "../containers/useChatInputContainer";
import classes from "./ChatInput.module.css";
import { TodoPreviewBar } from "./TodoPreviewBar";
import { TokenUsageDetails, TokenUsageIndicator } from "./TokenUsageIndicator";
import type {
  ChatInputContainer,
  ChatInputProps,
} from "../containers/useChatInputContainer";
import type * as React from "react";

function HighlightedKeyword({
  keyword,
  ranges,
}: {
  keyword: string;
  ranges: number[];
}): React.ReactElement {
  const highlighted = new Set(ranges);
  return (
    <>
      /
      {[...keyword].map((char, index) => (
        <Text
          key={`${char}-${index}`}
          component="span"
          inherit
          fw={highlighted.has(index) ? 800 : 500}
          td={highlighted.has(index) ? "underline" : void 0}
        >
          {char}
        </Text>
      ))}
    </>
  );
}

export const ChatInput = memo(function ChatInput(
  props: ChatInputProps,
): React.ReactElement {
  return <ChatInputView view={useChatInputContainer(props)} />;
});

function ChatInputView({
  view,
}: {
  view: ChatInputContainer;
}): React.ReactElement {
  const {
    t,
    isMobile,
    selectableModelOptions,
    inferenceProfileSelectionEnabled,
    contextUsageEnabled,
    contextUsage,
    contextUsageActiveRun,
    onApplyInferenceProfile,
    isUploading,
    pendingFiles,
    goal,
    todo,
    onClearGoal,
    onUpdateGoal,
    onPauseGoal,
    onResumeGoal,
    removeFile,
    wasCommandBlocked,
    isStopAvailable,
    isStopPending,
    onStopRequest,
    editingMessageId,
    editSendDisabled,
    inputDisabled,
    disabledPlaceholder,
    inputValue,
    inferenceProfile,
    profilePickerOpened,
    setProfilePickerOpened,
    setScrollToContextUsageOnOpen,
    contextUsageDetailsRef,
    desktopProfileSection,
    setDesktopProfileSection,
    sendErrorVisible,
    selectedAction,
    setSelectedAction,
    inputActionListboxId,
    inputActionOptionRefs,
    desktopProfileDialogId,
    desktopProfileModelPanelId,
    desktopProfileEffortPanelId,
    profileTriggerRef,
    desktopProfileSectionRefs,
    desktopModelOptionRefs,
    desktopEffortOptionRefs,
    selectableEfforts,
    selectedModelLabel,
    selectedEffortLabel,
    hasPendingInferenceProfileChange,
    fileInputRef,
    textareaRef,
    inputActionQuery,
    visibleInputActions,
    todoPreviewVisible,
    activeInputActionIndex,
    setActiveInputActionIndex,
    activeInputAction,
    activeInputActionOptionId,
    updateInputValue,
    persistDraft,
    handleCancelEdit,
    handleSend,
    handleSelectInputAction,
    handleInputFocus,
    handleInputBlur,
    handleKeyDown,
    handleFileChange,
    handleModelChange,
    handleEffortChange,
    handleOpenContextUsage,
    handleProfilePickerEnterTransitionEnd,
    handleDesktopProfileSectionKeyDown,
    handleDesktopProfileOptionKeyDown,
    handleProfileTriggerKeyDown,
  } = view;
  const profileTrigger = (
    <Button
      variant="light"
      size="compact-sm"
      radius={rem(12)}
      disabled={inputDisabled || selectableModelOptions.length === 0}
      ref={profileTriggerRef}
      onClick={() => {
        setProfilePickerOpened(!profilePickerOpened);
        if (profilePickerOpened) {
          setDesktopProfileSection(null);
        }
      }}
      onKeyDown={handleProfileTriggerKeyDown}
      rightSection={
        <Group gap={rem(4)} wrap="nowrap">
          {hasPendingInferenceProfileChange && (
            <Box
              aria-hidden="true"
              bg="blue.6"
              w={rem(6)}
              h={rem(6)}
              style={{ borderRadius: rem(999) }}
            />
          )}
          <IconChevronDown aria-hidden="true" size={14} />
        </Group>
      }
      aria-label={t("composerProfile.model")}
      {...(!isMobile
        ? {
            "aria-controls": desktopProfileDialogId,
            "aria-expanded": profilePickerOpened,
            "aria-haspopup": "dialog" as const,
          }
        : {})}
      style={{
        border: hasPendingInferenceProfileChange
          ? `${rem(1)} solid var(--mantine-color-blue-6)`
          : void 0,
        boxShadow: hasPendingInferenceProfileChange
          ? `0 0 0 ${rem(2)} var(--mantine-color-blue-light)`
          : void 0,
        minWidth: rem(128),
        maxWidth: rem(224),
        minHeight: rem(36),
      }}
    >
      <Text size="sm" truncate style={{ maxWidth: "20ch", minWidth: 0 }}>
        {selectableEfforts.length > 0
          ? `${selectedModelLabel} · ${selectedEffortLabel}`
          : selectedModelLabel}
      </Text>
    </Button>
  );
  const contextUsageTrigger = contextUsageEnabled ? (
    <TokenUsageIndicator usage={contextUsage} onOpen={handleOpenContextUsage} />
  ) : null;
  const modelOptionRows = selectableModelOptions.map((option, index) => {
    const selected = option.label === inferenceProfile.model_target_label;
    return (
      <UnstyledButton
        key={option.label}
        ref={(node) => {
          if (node === null) {
            desktopModelOptionRefs.current.delete(index);
          } else {
            desktopModelOptionRefs.current.set(index, node);
          }
        }}
        onClick={() => handleModelChange(option.label)}
        onKeyDown={(event) => {
          if (!isMobile) {
            handleDesktopProfileOptionKeyDown("model", index, event);
          }
        }}
        aria-pressed={selected}
        style={{
          background: selected
            ? "var(--mantine-color-default-hover)"
            : "var(--mantine-color-body)",
          borderTop:
            index === 0
              ? "none"
              : `${rem(1)} solid var(--mantine-color-default-border)`,
          display: "block",
          padding: `${rem(9)} ${rem(12)}`,
          textAlign: "left",
          width: "100%",
        }}
      >
        <Group gap="sm" justify="space-between" wrap="nowrap">
          <Stack gap={rem(1)} style={{ minWidth: 0 }}>
            <Text size="sm" fw={600} lh={rem(18)} truncate>
              {option.label}
            </Text>
            <Text size="xs" c="dimmed" lh={rem(16)} truncate>
              {option.model_selection.model_identifier}
            </Text>
          </Stack>
          {selected && (
            <IconCheck
              aria-hidden="true"
              size={16}
              color="var(--mantine-color-blue-6)"
              style={{ flexShrink: 0 }}
            />
          )}
        </Group>
      </UnstyledButton>
    );
  });
  const effortOptionRows = selectableEfforts.map((effort, index) => {
    const selected = effort === inferenceProfile.reasoning_effort;
    return (
      <UnstyledButton
        key={effort}
        ref={(node) => {
          if (node === null) {
            desktopEffortOptionRefs.current.delete(index);
          } else {
            desktopEffortOptionRefs.current.set(index, node);
          }
        }}
        onClick={() => handleEffortChange(effort)}
        onKeyDown={(event) => {
          if (!isMobile) {
            handleDesktopProfileOptionKeyDown("effort", index, event);
          }
        }}
        aria-pressed={selected}
        style={{
          background: selected
            ? "var(--mantine-color-default-hover)"
            : "var(--mantine-color-body)",
          borderTop:
            index === 0
              ? "none"
              : `${rem(1)} solid var(--mantine-color-default-border)`,
          display: "block",
          padding: `${rem(12)}`,
          textAlign: "left",
          width: "100%",
        }}
      >
        <Group gap="sm" justify="space-between" wrap="nowrap">
          <Text size="sm" fw={600} lh={rem(18)}>
            {effort}
          </Text>
          {selected && (
            <IconCheck
              aria-hidden="true"
              size={16}
              color="var(--mantine-color-blue-6)"
              style={{ flexShrink: 0 }}
            />
          )}
        </Group>
      </UnstyledButton>
    );
  });
  const mobileProfilePickerContent = (
    <Stack gap="md">
      {inferenceProfileSelectionEnabled ? (
        <>
          <Stack
            gap={0}
            style={{
              border: `${rem(1)} solid var(--mantine-color-default-border)`,
              borderRadius: rem(12),
              overflow: "hidden",
            }}
          >
            {modelOptionRows}
          </Stack>
          {selectableEfforts.length > 0 ? (
            <Stack gap={rem(6)}>
              <Text size="sm" fw={600}>
                {t("composerProfile.effortLabel")}
              </Text>
              <Stack
                gap={0}
                style={{
                  border: `${rem(1)} solid var(--mantine-color-default-border)`,
                  borderRadius: rem(12),
                  overflow: "hidden",
                }}
              >
                {effortOptionRows}
              </Stack>
            </Stack>
          ) : null}
        </>
      ) : null}
      {contextUsageEnabled ? (
        <Box ref={contextUsageDetailsRef}>
          {inferenceProfileSelectionEnabled ? <Divider mb="sm" /> : null}
          <TokenUsageDetails
            activeRun={contextUsageActiveRun}
            usage={contextUsage}
          />
        </Box>
      ) : null}
    </Stack>
  );
  const desktopProfileMenu = (
    <Group gap={rem(4)} align="flex-end" wrap="nowrap">
      <Paper
        id={desktopProfileDialogId}
        role="dialog"
        aria-label={t("composerProfile.model")}
        withBorder
        radius={rem(12)}
        shadow="md"
        p={rem(6)}
        w={rem(260)}
        style={{ maxHeight: "70dvh", overflowY: "auto" }}
      >
        <Stack gap={rem(2)}>
          {contextUsageEnabled ? (
            <>
              <Box ref={contextUsageDetailsRef} px={rem(10)} pb={rem(6)}>
                <TokenUsageDetails
                  activeRun={contextUsageActiveRun}
                  usage={contextUsage}
                />
              </Box>
              {inferenceProfileSelectionEnabled ? <Divider my="xs" /> : null}
            </>
          ) : null}
          {inferenceProfileSelectionEnabled ? (
            <>
              <UnstyledButton
                ref={(node) => {
                  if (node === null) {
                    desktopProfileSectionRefs.current.delete("model");
                  } else {
                    desktopProfileSectionRefs.current.set("model", node);
                  }
                }}
                onMouseEnter={() => setDesktopProfileSection("model")}
                onClick={() => setDesktopProfileSection("model")}
                onKeyDown={(event) =>
                  handleDesktopProfileSectionKeyDown("model", event)
                }
                aria-expanded={desktopProfileSection === "model"}
                aria-controls={desktopProfileModelPanelId}
                aria-haspopup="true"
                style={{
                  background:
                    desktopProfileSection === "model"
                      ? "var(--mantine-color-default-hover)"
                      : "transparent",
                  borderRadius: rem(8),
                  padding: `${rem(8)} ${rem(10)}`,
                  width: "100%",
                }}
              >
                <Group justify="space-between" gap="md" wrap="nowrap">
                  <Text size="sm" fw={500}>
                    {t("composerProfile.model")}
                  </Text>
                  <Group gap={rem(6)} wrap="nowrap" style={{ minWidth: 0 }}>
                    <Text size="sm" c="dimmed" truncate>
                      {selectedModelLabel}
                    </Text>
                    <IconChevronRight
                      aria-hidden="true"
                      size={16}
                      color="var(--mantine-color-dimmed)"
                      style={{ flexShrink: 0 }}
                    />
                  </Group>
                </Group>
              </UnstyledButton>
              {selectableEfforts.length > 0 && (
                <UnstyledButton
                  ref={(node) => {
                    if (node === null) {
                      desktopProfileSectionRefs.current.delete("effort");
                    } else {
                      desktopProfileSectionRefs.current.set("effort", node);
                    }
                  }}
                  onMouseEnter={() => setDesktopProfileSection("effort")}
                  onClick={() => setDesktopProfileSection("effort")}
                  onKeyDown={(event) =>
                    handleDesktopProfileSectionKeyDown("effort", event)
                  }
                  aria-expanded={desktopProfileSection === "effort"}
                  aria-controls={desktopProfileEffortPanelId}
                  aria-haspopup="true"
                  style={{
                    background:
                      desktopProfileSection === "effort"
                        ? "var(--mantine-color-default-hover)"
                        : "transparent",
                    borderRadius: rem(8),
                    padding: `${rem(8)} ${rem(10)}`,
                    width: "100%",
                  }}
                >
                  <Group justify="space-between" gap="md" wrap="nowrap">
                    <Text size="sm" fw={500}>
                      {t("composerProfile.effortLabel")}
                    </Text>
                    <Group gap={rem(6)} wrap="nowrap">
                      <Text size="sm" c="dimmed">
                        {selectedEffortLabel}
                      </Text>
                      <IconChevronRight
                        aria-hidden="true"
                        size={16}
                        color="var(--mantine-color-dimmed)"
                      />
                    </Group>
                  </Group>
                </UnstyledButton>
              )}
            </>
          ) : null}
        </Stack>
      </Paper>
      {inferenceProfileSelectionEnabled &&
        desktopProfileSection === "model" && (
          <Paper
            id={desktopProfileModelPanelId}
            role="group"
            aria-label={t("composerProfile.model")}
            withBorder
            radius={rem(12)}
            shadow="md"
            w={rem(280)}
            style={{ maxHeight: rem(280), overflowY: "auto" }}
          >
            <Stack gap={0}>{modelOptionRows}</Stack>
          </Paper>
        )}
      {inferenceProfileSelectionEnabled &&
        desktopProfileSection === "effort" &&
        selectableEfforts.length > 0 && (
          <Paper
            id={desktopProfileEffortPanelId}
            role="group"
            aria-label={t("composerProfile.effortLabel")}
            withBorder
            radius={rem(12)}
            shadow="md"
            p={rem(6)}
            w={rem(220)}
          >
            <Text size="xs" c="dimmed" fw={600} px={rem(8)} py={rem(4)}>
              {t("composerProfile.effortLabel")}
            </Text>
            <Stack gap={rem(2)}>
              {selectableEfforts.map((effort, index) => {
                const selected = effort === inferenceProfile.reasoning_effort;
                return (
                  <UnstyledButton
                    key={effort}
                    ref={(node) => {
                      if (node === null) {
                        desktopEffortOptionRefs.current.delete(index);
                      } else {
                        desktopEffortOptionRefs.current.set(index, node);
                      }
                    }}
                    onClick={() => handleEffortChange(effort)}
                    onKeyDown={(event) =>
                      handleDesktopProfileOptionKeyDown("effort", index, event)
                    }
                    aria-pressed={selected}
                    style={{
                      background: selected
                        ? "var(--mantine-color-default-hover)"
                        : "transparent",
                      borderRadius: rem(8),
                      padding: `${rem(8)} ${rem(10)}`,
                      width: "100%",
                    }}
                  >
                    <Group justify="space-between" gap="sm" wrap="nowrap">
                      <Text size="sm">{effort}</Text>
                      {selected && <IconCheck aria-hidden="true" size={16} />}
                    </Group>
                  </UnstyledButton>
                );
              })}
            </Stack>
          </Paper>
        )}
    </Group>
  );
  const modelOnlyApplyAvailable =
    hasPendingInferenceProfileChange &&
    !inputValue.trim() &&
    pendingFiles.length === 0 &&
    selectedAction === null &&
    !inputDisabled &&
    !editSendDisabled &&
    onApplyInferenceProfile != null;
  const stopAvailableAlongsideApply =
    isStopAvailable &&
    (inputDisabled || (!inputValue.trim() && selectedAction === null));

  return (
    <>
      {/* hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        style={{ display: "none" }}
        onChange={handleFileChange}
      />
      {/* command blocked notice during Run */}
      {wasCommandBlocked && (
        <Text size="xs" c="orange" mb={4}>
          {t("commandBlockedDuringRun")}
        </Text>
      )}
      <Stack gap="xs">
        {sendErrorVisible && (
          <Text size="xs" c="red">
            {selectedAction
              ? `${selectedAction.label} action failed. Edit it or try again.`
              : "Message failed to send. Try again."}
          </Text>
        )}
        {editingMessageId && (
          <Paper withBorder radius="sm" px="sm" py="2xs">
            <Group justify="space-between" gap="sm" wrap="nowrap">
              <Text size="xs" c="dimmed" fw={500}>
                {editSendDisabled
                  ? t("editBlockedDuringRun")
                  : t("editingMessage")}
              </Text>
              <ActionIcon
                variant="subtle"
                size="sm"
                c="dimmed"
                onClick={handleCancelEdit}
                aria-label={t("cancelEdit")}
              >
                <IconX size={14} />
              </ActionIcon>
            </Group>
          </Paper>
        )}
        {visibleInputActions.length > 0 && (
          <Paper
            id={inputActionListboxId}
            role="listbox"
            aria-label={t("slashCommands.title")}
            withBorder
            radius="md"
            p="xs"
            mb={todoPreviewVisible ? rem(22) : 0}
            style={{
              maxHeight: `min(40dvh, ${rem(320)})`,
              overflowY: "auto",
              overflowX: "hidden",
              overscrollBehavior: "contain",
            }}
          >
            <Stack gap={rem(2)}>
              <Text size="xs" c="dimmed" px="xs">
                {t("slashCommands.title")}
              </Text>
              {visibleInputActions.map((ranked, index) => (
                <UnstyledButton
                  key={ranked.action.id}
                  ref={(node) => {
                    if (node === null) {
                      inputActionOptionRefs.current.delete(index);
                    } else {
                      inputActionOptionRefs.current.set(index, node);
                    }
                  }}
                  id={`${inputActionListboxId}-option-${index}`}
                  role="option"
                  aria-selected={index === activeInputActionIndex}
                  tabIndex={-1}
                  onClick={() => handleSelectInputAction(ranked.action)}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseMove={() => {
                    setActiveInputActionIndex(index);
                  }}
                  px="xs"
                  py={rem(7)}
                  style={{
                    background:
                      index === activeInputActionIndex
                        ? "var(--mantine-color-default-hover)"
                        : "transparent",
                    borderRadius: rem(8),
                    width: "100%",
                  }}
                >
                  <Stack gap={rem(3)} style={{ minWidth: 0 }}>
                    <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
                      <Text
                        size="sm"
                        fw={500}
                        style={{ flex: "0 0 auto", whiteSpace: "nowrap" }}
                      >
                        <HighlightedKeyword
                          keyword={ranked.action.keyword}
                          ranges={ranked.ranges}
                        />
                      </Text>
                      {(ranked.action.source_label ||
                        ranked.action.relative_hint) && (
                        <Text
                          size="xs"
                          c="dimmed"
                          truncate
                          style={{ flex: "1 1 auto", minWidth: 0 }}
                        >
                          {[
                            ranked.action.source_label,
                            ranked.action.relative_hint,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </Text>
                      )}
                    </Group>
                    <Text
                      size="xs"
                      c="dimmed"
                      lineClamp={2}
                      style={{ overflowWrap: "anywhere" }}
                    >
                      {ranked.action.description}
                    </Text>
                    {ranked.action.availability_hint?.message && (
                      <Text size="xs" c="orange" lineClamp={2}>
                        {ranked.action.availability_hint.message}
                      </Text>
                    )}
                  </Stack>
                </UnstyledButton>
              ))}
            </Stack>
          </Paper>
        )}
        <Paper
          withBorder
          radius={rem(12)}
          px="xs"
          py={rem(6)}
          style={{
            position: "relative",
            border: `${rem(1)} solid var(--mantine-color-default-border)`,
            background: "var(--mantine-color-body)",
          }}
        >
          <Stack gap={rem(4)}>
            {pendingFiles.length > 0 && !editingMessageId && (
              <AttachmentPreviewBarContainer
                pendingFiles={pendingFiles}
                onRemove={removeFile}
              />
            )}
            {todoPreviewVisible && todo !== null && (
              <TodoPreviewBar
                goal={goal}
                isMobile={isMobile}
                todo={todo}
                onClearGoal={onClearGoal}
                onUpdateGoal={onUpdateGoal}
                onPauseGoal={onPauseGoal}
                onResumeGoal={onResumeGoal}
              />
            )}
            {selectedAction !== null && !editingMessageId && !inputDisabled && (
              <Stack gap={rem(2)} align="flex-start">
                <Group
                  gap={rem(4)}
                  wrap="nowrap"
                  px={rem(8)}
                  py={rem(3)}
                  style={{
                    borderRadius: rem(999),
                    background: "var(--mantine-color-blue-light)",
                    width: "fit-content",
                    maxWidth: "100%",
                  }}
                >
                  <Text size="xs" fw={700} c="blue" truncate>
                    /{selectedAction.keyword}
                  </Text>
                  <ActionIcon
                    variant="transparent"
                    size={rem(16)}
                    c="dimmed"
                    onClick={() => {
                      setSelectedAction(null);
                      persistDraft(inputValue, null);
                      textareaRef.current?.focus();
                    }}
                    aria-label={t("cancelEdit")}
                  >
                    <IconX size={12} />
                  </ActionIcon>
                </Group>
                {selectedAction.availability_hint?.message && (
                  <Text size="xs" c="orange" pl={rem(2)}>
                    {selectedAction.availability_hint.message}
                  </Text>
                )}
              </Stack>
            )}
            <Textarea
              ref={textareaRef}
              name="message"
              inputMode="text"
              autoCorrect="on"
              autoCapitalize="sentences"
              spellCheck
              variant="unstyled"
              placeholder={
                inputDisabled
                  ? (disabledPlaceholder ?? t("inputDisabledPlaceholder"))
                  : (selectedAction?.message.placeholder ??
                    (isMobile
                      ? t("inputPlaceholder")
                      : t("inputPlaceholderDesktop")))
              }
              value={inputDisabled ? "" : inputValue}
              onChange={(event) => updateInputValue(event.currentTarget.value)}
              onKeyDown={handleKeyDown}
              onFocus={handleInputFocus}
              onBlur={handleInputBlur}
              aria-autocomplete={inputActionQuery === null ? void 0 : "list"}
              aria-controls={
                visibleInputActions.length > 0 ? inputActionListboxId : void 0
              }
              aria-expanded={visibleInputActions.length > 0}
              aria-haspopup="listbox"
              aria-activedescendant={
                activeInputAction === null ? void 0 : activeInputActionOptionId
              }
              disabled={inputDisabled}
              autosize
              minRows={1}
              maxRows={5}
              classNames={{ input: classes.composerTextarea }}
              styles={{
                input: {
                  fontSize: rem(16),
                  lineHeight: 1.45,
                  paddingInline: rem(6),
                  paddingBlock: rem(4),
                },
              }}
            />
            <Group gap="xs" wrap="nowrap">
              <ActionIcon
                size={rem(36)}
                radius={rem(12)}
                variant="subtle"
                onClick={() => fileInputRef.current?.click()}
                disabled={
                  inputDisabled ||
                  isUploading ||
                  Boolean(editingMessageId) ||
                  selectedAction?.attachments.policy === "unsupported"
                }
                aria-label={t("attachment.attach")}
              >
                <IconPaperclip size={17} />
              </ActionIcon>
              {isMobile ? (
                <>
                  {inferenceProfileSelectionEnabled ? profileTrigger : null}
                  {contextUsageTrigger}
                  {inferenceProfileSelectionEnabled || contextUsageEnabled ? (
                    <Drawer
                      opened={profilePickerOpened}
                      onClose={() => {
                        setProfilePickerOpened(false);
                        setScrollToContextUsageOnOpen(false);
                      }}
                      transitionProps={{
                        onEntered: handleProfilePickerEnterTransitionEnd,
                      }}
                      title={
                        inferenceProfileSelectionEnabled
                          ? t("composerProfile.model")
                          : t("tokenUsage.title")
                      }
                      closeButtonProps={{
                        "aria-label": t("composerProfile.done"),
                        icon: (
                          <Text component="span" size="sm" fw={500}>
                            {t("composerProfile.done")}
                          </Text>
                        ),
                        onClick: () => setScrollToContextUsageOnOpen(false),
                        style: {
                          color: "var(--mantine-color-blue-6)",
                          paddingInline: rem(8),
                          width: "auto",
                        },
                      }}
                      position="bottom"
                      size={`min(80dvh, ${rem(720)})`}
                      keepMounted
                      styles={{
                        title: { flex: 1 },
                        content: {
                          borderTopLeftRadius: rem(12),
                          borderTopRightRadius: rem(12),
                        },
                        body: {
                          overflowY: "auto",
                          paddingBottom:
                            "max(var(--mantine-spacing-md), env(safe-area-inset-bottom))",
                        },
                      }}
                    >
                      {mobileProfilePickerContent}
                    </Drawer>
                  ) : null}
                </>
              ) : inferenceProfileSelectionEnabled || contextUsageEnabled ? (
                <Popover
                  opened={profilePickerOpened}
                  onChange={(opened) => {
                    setProfilePickerOpened(opened);
                    if (!opened) {
                      setDesktopProfileSection(null);
                      setScrollToContextUsageOnOpen(false);
                    }
                  }}
                  position="top-start"
                  width="auto"
                  shadow="none"
                  withinPortal
                >
                  <Popover.Target>
                    <Group gap="xs" wrap="nowrap">
                      {inferenceProfileSelectionEnabled ? profileTrigger : null}
                      {contextUsageTrigger}
                    </Group>
                  </Popover.Target>
                  <Popover.Dropdown
                    p={0}
                    style={{
                      background: "transparent",
                      border: 0,
                      boxShadow: "none",
                      overflow: "visible",
                    }}
                  >
                    {desktopProfileMenu}
                  </Popover.Dropdown>
                </Popover>
              ) : null}
              <Box style={{ flex: "1 1 auto" }} />
              {stopAvailableAlongsideApply && (
                <ActionIcon
                  size={rem(36)}
                  radius={rem(12)}
                  variant="filled"
                  color="red"
                  onClick={onStopRequest}
                  onMouseDown={(event) => event.preventDefault()}
                  loading={isStopPending}
                  aria-label={t("stopRun")}
                >
                  <IconPlayerStop size={17} />
                </ActionIcon>
              )}
              {(!stopAvailableAlongsideApply || modelOnlyApplyAvailable) && (
                <ActionIcon
                  size={rem(36)}
                  radius={rem(12)}
                  variant="filled"
                  onClick={handleSend}
                  onMouseDown={(event) => event.preventDefault()}
                  disabled={
                    inputDisabled ||
                    editSendDisabled ||
                    (!inputValue.trim() &&
                      pendingFiles.length === 0 &&
                      selectedAction?.message.policy === "required")
                  }
                  loading={isUploading}
                  aria-label={
                    modelOnlyApplyAvailable
                      ? "Apply model change"
                      : t("composerProfile.send")
                  }
                  style={{
                    boxShadow: modelOnlyApplyAvailable
                      ? `0 0 0 ${rem(2)} var(--mantine-color-blue-light)`
                      : void 0,
                  }}
                >
                  {modelOnlyApplyAvailable ? (
                    <IconCheck size={17} />
                  ) : (
                    <IconSend size={17} />
                  )}
                </ActionIcon>
              )}
            </Group>
          </Stack>
        </Paper>
      </Stack>
    </>
  );
}
