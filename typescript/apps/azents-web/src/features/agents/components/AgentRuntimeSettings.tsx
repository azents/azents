"use client";

/** Capability-aware Agent Runtime settings UI. */

import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Checkbox,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  Progress,
  rem,
  Select,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconPlayerPlay,
  IconRefresh,
  IconRotateClockwise,
  IconSquare,
  IconTerminal2,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { RuntimeLifecycleStatus } from "@/shared/components/runtime/RuntimeLifecycleStatus";
import { RuntimeSystemMetricsOverview } from "@/shared/runtime-metrics/components/RuntimeSystemMetricsOverview";
import type { AgentRuntimeSettingsState } from "../containers/useAgentRuntimeSettingsContainer";
import type { RuntimeSystemMetricsOverviewState } from "@/shared/runtime-metrics/types";
import type {
  AgentResponse,
  AgentRuntimeRemovalImpactResponse,
  AgentRuntimeRemovalStage,
  AgentRuntimeResponse,
  WorkspaceRuntimeProfileResponse,
} from "@azents/public-client";

interface AgentRuntimeSettingsProps {
  handle: string;
  agent: AgentResponse;
  state: AgentRuntimeSettingsState;
  metricsState: RuntimeSystemMetricsOverviewState;
  selectedProfileId: string | null;
  actionError: string | null;
  actionNotice: "added" | "profileUpdated" | null;
  addConfirmOpen: boolean;
  removeConfirmOpen: boolean;
  restartConfirmOpen: boolean;
  resetConfirmOpen: boolean;
  removalAcknowledged: boolean;
  isAdding: boolean;
  isUpdatingProfile: boolean;
  isRemoving: boolean;
  lifecycleAction: "start" | "stop" | "restart" | "reset" | null;
  onSelectProfile: (profileId: string | null) => void;
  onOpenAddConfirm: () => void;
  onCloseAddConfirm: () => void;
  onConfirmAdd: () => void;
  onUpdateProfile: () => void;
  onOpenRemoveConfirm: () => void;
  onCloseRemoveConfirm: () => void;
  onRemovalAcknowledgedChange: (acknowledged: boolean) => void;
  onConfirmRemove: () => void;
  onOpenRestartConfirm: () => void;
  onCloseRestartConfirm: () => void;
  onOpenResetConfirm: () => void;
  onCloseResetConfirm: () => void;
  onStart: () => void;
  onStop: () => void;
  onConfirmRestart: () => void;
  onConfirmReset: () => void;
  onRefresh: () => void;
}

function profileOptions(
  profiles: WorkspaceRuntimeProfileResponse[],
  unavailableLabel: string,
): { value: string; label: string; disabled: boolean }[] {
  return profiles.map((profile) => ({
    value: profile.id,
    label: profile.available
      ? profile.display_name
      : `${profile.display_name} · ${unavailableLabel}`,
    disabled: !profile.available,
  }));
}

function stageProgress(stage: AgentRuntimeRemovalStage): number {
  switch (stage) {
    case "fencing":
      return 10;
    case "interrupting_work":
      return 30;
    case "cleaning_product_state":
      return 50;
    case "deleting_runtime":
      return 70;
    case "finalizing":
      return 90;
    case "completed":
      return 100;
  }
}

function ImpactGrid({
  impact,
}: {
  impact: AgentRuntimeRemovalImpactResponse;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.runtimeSettings");
  const items = [
    ["activeRootSessions", impact.active_root_session_count],
    ["activeSubagents", impact.active_subagent_count],
    ["activeRuns", impact.active_run_count],
    ["queuedActions", impact.queued_runtime_action_count],
  ] as const;

  return (
    <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
      {items.map(([key, count]) => (
        <Paper key={key} withBorder radius="md" p="sm">
          <Text fw={700} size="xl">
            {count}
          </Text>
          <Text c="dimmed" size="xs">
            {t(`impact.${key}`)}
          </Text>
        </Paper>
      ))}
    </SimpleGrid>
  );
}

function RuntimeProfileSelect({
  runtime,
  profiles,
  selectedProfileId,
  disabled,
  onSelectProfile,
}: {
  runtime: AgentRuntimeResponse;
  profiles: WorkspaceRuntimeProfileResponse[];
  selectedProfileId: string | null;
  disabled: boolean;
  onSelectProfile: (profileId: string | null) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.runtimeSettings");
  const availableCount = profiles.filter((profile) => profile.available).length;

  return (
    <Stack gap="xs">
      <Select
        allowDeselect={false}
        data={profileOptions(profiles, t("profileUnavailable"))}
        disabled={disabled || availableCount === 0}
        label={t("profileLabel")}
        description={t("profileDescription")}
        placeholder={
          availableCount === 0 ? t("noProfiles") : t("profilePlaceholder")
        }
        searchable
        value={selectedProfileId}
        onChange={onSelectProfile}
      />
      {runtime.runtime_profile_status === "unavailable" ? (
        <Alert color="yellow" title={t("selectedProfileUnavailableTitle")}>
          {t("selectedProfileUnavailableDescription")}
        </Alert>
      ) : null}
    </Stack>
  );
}

function RuntimeFreeView({
  runtime,
  profiles,
  selectedProfileId,
  addConfirmOpen,
  isAdding,
  onSelectProfile,
  onOpenAddConfirm,
  onCloseAddConfirm,
  onConfirmAdd,
}: {
  runtime: AgentRuntimeResponse;
  profiles: WorkspaceRuntimeProfileResponse[];
  selectedProfileId: string | null;
  addConfirmOpen: boolean;
  isAdding: boolean;
  onSelectProfile: (profileId: string | null) => void;
  onOpenAddConfirm: () => void;
  onCloseAddConfirm: () => void;
  onConfirmAdd: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.runtimeSettings");
  const selectedProfile =
    profiles.find((profile) => profile.id === selectedProfileId) ?? null;
  const canAdd =
    runtime.actions.add &&
    selectedProfile !== null &&
    selectedProfile.available;

  return (
    <>
      <Paper withBorder radius="lg" p="lg">
        <Stack gap="lg">
          <Group align="flex-start" wrap="nowrap">
            <ThemeIcon variant="light" radius="xl" size="xl">
              <IconTerminal2 size={rem(22)} />
            </ThemeIcon>
            <Stack gap={4}>
              <Text fw={700} size="lg">
                {t("none.title")}
              </Text>
              <Text c="dimmed" size="sm">
                {t("none.description")}
              </Text>
            </Stack>
          </Group>
          <Alert color="blue" title={t("none.retainedTitle")}>
            {t("none.retainedDescription")}
          </Alert>
          <RuntimeProfileSelect
            runtime={runtime}
            profiles={profiles}
            selectedProfileId={selectedProfileId}
            disabled={isAdding}
            onSelectProfile={onSelectProfile}
          />
          <Group justify="flex-end">
            <Button
              disabled={!canAdd}
              loading={isAdding}
              onClick={onOpenAddConfirm}
            >
              {t("addAction")}
            </Button>
          </Group>
        </Stack>
      </Paper>
      <Modal
        centered
        opened={addConfirmOpen}
        title={t("addConfirmTitle")}
        onClose={onCloseAddConfirm}
      >
        <Stack gap="md">
          <Text size="sm">
            {t("addConfirmDescription", {
              profile: selectedProfile?.display_name ?? t("unknownProfile"),
            })}
          </Text>
          <Alert color="blue">{t("addStoppedNotice")}</Alert>
          <Group justify="flex-end">
            <Button variant="default" onClick={onCloseAddConfirm}>
              {t("cancel")}
            </Button>
            <Button loading={isAdding} onClick={onConfirmAdd}>
              {t("confirmAdd")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}

function LifecycleControls({
  runtime,
  lifecycleAction,
  restartConfirmOpen,
  resetConfirmOpen,
  onStart,
  onStop,
  onOpenRestartConfirm,
  onCloseRestartConfirm,
  onConfirmRestart,
  onOpenResetConfirm,
  onCloseResetConfirm,
  onConfirmReset,
}: {
  runtime: AgentRuntimeResponse;
  lifecycleAction: "start" | "stop" | "restart" | "reset" | null;
  restartConfirmOpen: boolean;
  resetConfirmOpen: boolean;
  onStart: () => void;
  onStop: () => void;
  onOpenRestartConfirm: () => void;
  onCloseRestartConfirm: () => void;
  onConfirmRestart: () => void;
  onOpenResetConfirm: () => void;
  onCloseResetConfirm: () => void;
  onConfirmReset: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.runtimeSettings");
  const busy = lifecycleAction !== null;

  return (
    <>
      <Paper withBorder radius="lg" p="lg">
        <Stack gap="md">
          <Stack gap={4}>
            <Text fw={700}>{t("lifecycle.title")}</Text>
            <Text c="dimmed" size="sm">
              {t("lifecycle.description")}
            </Text>
          </Stack>
          <Group gap="sm">
            {runtime.actions.start ? (
              <Button
                disabled={busy}
                leftSection={<IconPlayerPlay size={rem(16)} />}
                loading={lifecycleAction === "start"}
                variant="light"
                onClick={onStart}
              >
                {t("lifecycle.start")}
              </Button>
            ) : null}
            {runtime.actions.stop ? (
              <Button
                disabled={busy}
                leftSection={<IconSquare size={rem(16)} />}
                loading={lifecycleAction === "stop"}
                variant="light"
                onClick={onStop}
              >
                {t("lifecycle.stop")}
              </Button>
            ) : null}
            {runtime.actions.restart ? (
              <Button
                disabled={busy}
                leftSection={<IconRotateClockwise size={rem(16)} />}
                loading={lifecycleAction === "restart"}
                variant="light"
                onClick={onOpenRestartConfirm}
              >
                {t("lifecycle.restart")}
              </Button>
            ) : null}
            {runtime.actions.reset ? (
              <Button
                color="red"
                disabled={busy}
                leftSection={<IconRefresh size={rem(16)} />}
                loading={lifecycleAction === "reset"}
                variant="light"
                onClick={onOpenResetConfirm}
              >
                {t("lifecycle.reset")}
              </Button>
            ) : null}
          </Group>
        </Stack>
      </Paper>
      <Modal
        centered
        opened={restartConfirmOpen}
        title={t("lifecycle.restartConfirmTitle")}
        onClose={onCloseRestartConfirm}
      >
        <Stack gap="md">
          <Text size="sm">{t("lifecycle.restartConfirmDescription")}</Text>
          <Alert color="blue">{t("lifecycle.restartPreservationNotice")}</Alert>
          <Group justify="flex-end">
            <Button variant="default" onClick={onCloseRestartConfirm}>
              {t("cancel")}
            </Button>
            <Button
              loading={lifecycleAction === "restart"}
              onClick={onConfirmRestart}
            >
              {t("lifecycle.confirmRestart")}
            </Button>
          </Group>
        </Stack>
      </Modal>
      <Modal
        centered
        opened={resetConfirmOpen}
        title={t("lifecycle.resetConfirmTitle")}
        onClose={onCloseResetConfirm}
      >
        <Stack gap="md">
          <Alert
            color="red"
            icon={<IconAlertTriangle size={rem(18)} />}
            title={t("lifecycle.resetDestructiveTitle")}
          >
            {t("lifecycle.resetConfirmDescription")}
          </Alert>
          <Group justify="flex-end">
            <Button variant="default" onClick={onCloseResetConfirm}>
              {t("cancel")}
            </Button>
            <Button
              color="red"
              loading={lifecycleAction === "reset"}
              onClick={onConfirmReset}
            >
              {t("lifecycle.confirmReset")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}

function ManagedView({
  runtime,
  profiles,
  selectedProfileId,
  isUpdatingProfile,
  isRemoving,
  removeConfirmOpen,
  restartConfirmOpen,
  resetConfirmOpen,
  removalAcknowledged,
  lifecycleAction,
  onSelectProfile,
  onUpdateProfile,
  onOpenRemoveConfirm,
  onCloseRemoveConfirm,
  onRemovalAcknowledgedChange,
  onConfirmRemove,
  onOpenRestartConfirm,
  onCloseRestartConfirm,
  onOpenResetConfirm,
  onCloseResetConfirm,
  onStart,
  onStop,
  onConfirmRestart,
  onConfirmReset,
}: {
  runtime: AgentRuntimeResponse;
  profiles: WorkspaceRuntimeProfileResponse[];
  selectedProfileId: string | null;
  isUpdatingProfile: boolean;
  isRemoving: boolean;
  removeConfirmOpen: boolean;
  restartConfirmOpen: boolean;
  resetConfirmOpen: boolean;
  removalAcknowledged: boolean;
  lifecycleAction: "start" | "stop" | "restart" | "reset" | null;
  onSelectProfile: (profileId: string | null) => void;
  onUpdateProfile: () => void;
  onOpenRemoveConfirm: () => void;
  onCloseRemoveConfirm: () => void;
  onRemovalAcknowledgedChange: (acknowledged: boolean) => void;
  onConfirmRemove: () => void;
  onOpenRestartConfirm: () => void;
  onCloseRestartConfirm: () => void;
  onOpenResetConfirm: () => void;
  onCloseResetConfirm: () => void;
  onStart: () => void;
  onStop: () => void;
  onConfirmRestart: () => void;
  onConfirmReset: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.runtimeSettings");
  const impact = runtime.removal_impact;
  const profileChanged =
    selectedProfileId !== null &&
    selectedProfileId !== runtime.runtime_profile_id;

  return (
    <>
      <Paper withBorder radius="lg" p="lg">
        <Stack gap="md">
          <Stack gap={4}>
            <Text fw={700}>{t("managed.profileTitle")}</Text>
            <Text c="dimmed" size="sm">
              {t("managed.profileDescription")}
            </Text>
          </Stack>
          <RuntimeProfileSelect
            runtime={runtime}
            profiles={profiles}
            selectedProfileId={selectedProfileId}
            disabled={isUpdatingProfile}
            onSelectProfile={onSelectProfile}
          />
          <Group justify="flex-end">
            <Button
              disabled={!profileChanged}
              loading={isUpdatingProfile}
              onClick={onUpdateProfile}
            >
              {t("managed.saveProfile")}
            </Button>
          </Group>
        </Stack>
      </Paper>

      {runtime.lifecycle ? (
        <RuntimeLifecycleStatus lifecycle={runtime.lifecycle} />
      ) : null}

      <LifecycleControls
        runtime={runtime}
        lifecycleAction={lifecycleAction}
        restartConfirmOpen={restartConfirmOpen}
        resetConfirmOpen={resetConfirmOpen}
        onStart={onStart}
        onStop={onStop}
        onOpenRestartConfirm={onOpenRestartConfirm}
        onCloseRestartConfirm={onCloseRestartConfirm}
        onConfirmRestart={onConfirmRestart}
        onOpenResetConfirm={onOpenResetConfirm}
        onCloseResetConfirm={onCloseResetConfirm}
        onConfirmReset={onConfirmReset}
      />

      <Paper withBorder radius="lg" p="lg">
        <Stack gap="md">
          <Group align="flex-start" wrap="nowrap">
            <ThemeIcon color="red" variant="light" radius="xl" size="lg">
              <IconTrash size={rem(18)} />
            </ThemeIcon>
            <Stack gap={4}>
              <Text c="red" fw={700}>
                {t("removal.title")}
              </Text>
              <Text c="dimmed" size="sm">
                {t("removal.description")}
              </Text>
            </Stack>
          </Group>
          <Group justify="flex-end">
            <Button
              color="red"
              disabled={!runtime.actions.remove || impact === null}
              loading={isRemoving}
              variant="light"
              onClick={onOpenRemoveConfirm}
            >
              {t("removal.action")}
            </Button>
          </Group>
        </Stack>
      </Paper>

      <Modal
        centered
        opened={removeConfirmOpen}
        size="lg"
        title={t("removal.confirmTitle")}
        onClose={onCloseRemoveConfirm}
      >
        <Stack gap="md">
          <Alert
            color="red"
            icon={<IconAlertTriangle size={rem(18)} />}
            title={t("removal.irreversibleTitle")}
          >
            {t("removal.irreversibleDescription")}
          </Alert>
          {impact ? <ImpactGrid impact={impact} /> : null}
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
            <Paper withBorder radius="md" p="md">
              <Text fw={700} size="sm">
                {t("removal.deletedTitle")}
              </Text>
              <Text c="dimmed" size="sm" mt="xs">
                {t("removal.deletedDescription")}
              </Text>
            </Paper>
            <Paper withBorder radius="md" p="md">
              <Text fw={700} size="sm">
                {t("removal.retainedTitle")}
              </Text>
              <Text c="dimmed" size="sm" mt="xs">
                {t("removal.retainedDescription")}
              </Text>
            </Paper>
          </SimpleGrid>
          <Checkbox
            checked={removalAcknowledged}
            label={t("removal.acknowledgement")}
            onChange={(event) =>
              onRemovalAcknowledgedChange(event.currentTarget.checked)
            }
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={onCloseRemoveConfirm}>
              {t("cancel")}
            </Button>
            <Button
              color="red"
              disabled={!removalAcknowledged}
              loading={isRemoving}
              onClick={onConfirmRemove}
            >
              {t("removal.confirmAction")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}

function RemovingView({
  runtime,
  onRefresh,
}: {
  runtime: AgentRuntimeResponse;
  onRefresh: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.runtimeSettings");
  const removal = runtime.removal;
  const impact = runtime.removal_impact;

  return (
    <Paper withBorder radius="lg" p="lg">
      <Stack gap="lg">
        <Group align="flex-start" wrap="nowrap">
          <Loader size="sm" mt="xs" />
          <Stack gap={4}>
            <Text fw={700} size="lg">
              {t("removing.title")}
            </Text>
            <Text c="dimmed" size="sm">
              {t("removing.description")}
            </Text>
          </Stack>
        </Group>
        {removal ? (
          <Stack gap="xs">
            <Group justify="space-between">
              <Text fw={600} size="sm">
                {t(`removing.stages.${removal.stage}`)}
              </Text>
              <Badge variant="light">
                {t(`removing.status.${removal.status}`)}
              </Badge>
            </Group>
            <Progress value={stageProgress(removal.stage)} animated />
            <Text c="dimmed" size="xs">
              {t("removing.cleanupProgress", {
                scanned: removal.cleanup_scanned_context_count,
                invalidated: removal.cleanup_invalidated_context_count,
                attempts: removal.attempt_count,
              })}
            </Text>
          </Stack>
        ) : null}
        {impact ? <ImpactGrid impact={impact} /> : null}
        <Alert color="blue">{t("removing.noCancellation")}</Alert>
        <Group justify="flex-end">
          <Button variant="default" onClick={onRefresh}>
            {t("refresh")}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

export function AgentRuntimeSettings({
  state,
  metricsState,
  selectedProfileId,
  actionError,
  actionNotice,
  addConfirmOpen,
  removeConfirmOpen,
  restartConfirmOpen,
  resetConfirmOpen,
  removalAcknowledged,
  isAdding,
  isUpdatingProfile,
  isRemoving,
  lifecycleAction,
  onSelectProfile,
  onOpenAddConfirm,
  onCloseAddConfirm,
  onConfirmAdd,
  onUpdateProfile,
  onOpenRemoveConfirm,
  onCloseRemoveConfirm,
  onRemovalAcknowledgedChange,
  onConfirmRemove,
  onOpenRestartConfirm,
  onCloseRestartConfirm,
  onOpenResetConfirm,
  onCloseResetConfirm,
  onStart,
  onStop,
  onConfirmRestart,
  onConfirmReset,
  onRefresh,
}: AgentRuntimeSettingsProps): React.ReactElement {
  const t = useTranslations("workspace.agents.runtimeSettings");

  if (state.type === "LOADING") {
    return (
      <Center style={{ flex: 1 }}>
        <Loader size="sm" />
      </Center>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Box p="md">
        <Alert color="red" title={t("loadErrorTitle")}>
          {state.message}
        </Alert>
      </Box>
    );
  }

  const { runtime, profiles } = state;
  return (
    <Box style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
      <Stack gap="lg" p="md" maw={rem(960)} mx="auto" w="100%">
        <Paper withBorder radius="lg" p="lg">
          <Group justify="space-between" align="flex-start" gap="lg">
            <Stack gap={4}>
              <Text fw={700} size="xl">
                {t("title")}
              </Text>
              <Text c="dimmed" size="sm">
                {t("description")}
              </Text>
            </Stack>
            <Badge
              color={
                runtime.capability === "managed"
                  ? "green"
                  : runtime.capability === "removing"
                    ? "yellow"
                    : "gray"
              }
              variant="light"
            >
              {t(`capability.${runtime.capability}`)}
            </Badge>
          </Group>
        </Paper>

        {runtime.capability !== "none" ? (
          <RuntimeSystemMetricsOverview state={metricsState} />
        ) : null}

        {actionError ? (
          <Alert color="red" title={t("actionErrorTitle")}>
            {actionError}
          </Alert>
        ) : null}
        {actionNotice ? (
          <Alert color="green">{t(`notices.${actionNotice}`)}</Alert>
        ) : null}

        {runtime.capability === "none" ? (
          <RuntimeFreeView
            runtime={runtime}
            profiles={profiles}
            selectedProfileId={selectedProfileId}
            addConfirmOpen={addConfirmOpen}
            isAdding={isAdding}
            onSelectProfile={onSelectProfile}
            onOpenAddConfirm={onOpenAddConfirm}
            onCloseAddConfirm={onCloseAddConfirm}
            onConfirmAdd={onConfirmAdd}
          />
        ) : null}
        {runtime.capability === "managed" ? (
          <ManagedView
            runtime={runtime}
            profiles={profiles}
            selectedProfileId={selectedProfileId}
            isUpdatingProfile={isUpdatingProfile}
            isRemoving={isRemoving}
            removeConfirmOpen={removeConfirmOpen}
            restartConfirmOpen={restartConfirmOpen}
            resetConfirmOpen={resetConfirmOpen}
            removalAcknowledged={removalAcknowledged}
            lifecycleAction={lifecycleAction}
            onSelectProfile={onSelectProfile}
            onUpdateProfile={onUpdateProfile}
            onOpenRemoveConfirm={onOpenRemoveConfirm}
            onCloseRemoveConfirm={onCloseRemoveConfirm}
            onRemovalAcknowledgedChange={onRemovalAcknowledgedChange}
            onConfirmRemove={onConfirmRemove}
            onOpenRestartConfirm={onOpenRestartConfirm}
            onCloseRestartConfirm={onCloseRestartConfirm}
            onOpenResetConfirm={onOpenResetConfirm}
            onCloseResetConfirm={onCloseResetConfirm}
            onStart={onStart}
            onStop={onStop}
            onConfirmRestart={onConfirmRestart}
            onConfirmReset={onConfirmReset}
          />
        ) : null}
        {runtime.capability === "removing" ? (
          <RemovingView runtime={runtime} onRefresh={onRefresh} />
        ) : null}
        <Divider />
        <Text c="dimmed" size="xs">
          {t("authorityNotice")}
        </Text>
      </Stack>
    </Box>
  );
}
