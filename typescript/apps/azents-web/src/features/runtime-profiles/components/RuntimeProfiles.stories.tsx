import { rem } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RuntimeProfiles } from "./RuntimeProfiles";
import type { RuntimeProfilesContainerOutput } from "../containers/useRuntimeProfilesContainer";
import type {
  RuntimeRecreationOperationResponse,
  SelectableInfrastructureProfileResponse,
  WorkspaceRuntimeProfileResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};

const infrastructureProfile: SelectableInfrastructureProfileResponse = {
  id: "infrastructure-profile-docker-standard",
  provider_id: "runtime-provider-docker",
  provider_display_name: "Docker production",
  provider_kind: "docker",
  profile_kind: "docker_container",
  display_name: "Standard container",
  description: "Balanced resources for general agent workloads.",
  spec: {
    profile_kind: "docker_container",
    contract_family: "docker.container-profile",
    schema_version: 1,
    runner_resources: {
      cpu_reservation_millicores: 500,
      cpu_limit_millicores: 2000,
      memory_reservation_bytes: 1_073_741_824,
      memory_limit_bytes: 4_294_967_296,
    },
    network_name: "azents-runtimes",
  },
  infrastructure_network: {
    mode: "direct",
    allowed_cidrs: ["0.0.0.0/0", "::/0"],
    denied_cidrs: ["169.254.169.254/32"],
    domain_mode: null,
    allowed_domains: [],
    denied_domains: [],
  },
  required_capabilities: ["runtime.docker.container-profile.v1"],
  terminal_enabled: true,
  version: 3,
  digest: "sha256:infrastructure-profile-digest",
  capability_revision_id: "capability-revision-9",
};

const proxyAllowlistInfrastructureProfile: SelectableInfrastructureProfileResponse =
  {
    ...infrastructureProfile,
    id: "infrastructure-profile-kubernetes-proxy",
    provider_id: "runtime-provider-kubernetes",
    provider_display_name: "Kubernetes production",
    provider_kind: "kubernetes",
    profile_kind: "kubernetes_pod",
    display_name: "Restricted proxy",
    spec: {
      profile_kind: "kubernetes_pod",
      contract_family: "kubernetes.pod-profile",
      schema_version: 3,
      runner_resources: {
        cpu_request_millicores: 500,
        cpu_limit_millicores: 2000,
        memory_request_bytes: 1_073_741_824,
        memory_limit_bytes: 4_294_967_296,
      },
      workspace_volume: {
        storage_class_name: "runtime-workspaces",
        storage_request_bytes: 10_737_418_240,
      },
      network_access: {
        mode: "proxy_required",
        allowed_cidrs: ["10.0.0.0/8"],
        denied_cidrs: [],
        domain_policy: {
          mode: "allowlist",
          allowed_domains: ["*.example.com"],
          denied_domains: [],
        },
      },
      service_account_name: null,
      scheduling: {
        node_selector: {},
        tolerations: [],
      },
      dind: null,
    },
    infrastructure_network: {
      mode: "proxy_required",
      allowed_cidrs: ["10.0.0.0/8"],
      denied_cidrs: [],
      domain_mode: "allowlist",
      allowed_domains: ["*.example.com"],
      denied_domains: [],
    },
    required_capabilities: ["runtime.kubernetes.pod-profile.v3"],
  };

const availableProfile: WorkspaceRuntimeProfileResponse = {
  id: "workspace-runtime-profile-standard",
  provider_id: infrastructureProfile.provider_id,
  infrastructure_profile_id: infrastructureProfile.id,
  display_name: "Standard runtime",
  description: "Default runtime for general workspace agents.",
  lifecycle: "active",
  policy: {
    schema_version: 1,
    network_restriction: {
      allowed_cidrs: ["10.0.0.0/8"],
      denied_cidrs: [],
    },
  },
  infrastructure_network: infrastructureProfile.infrastructure_network,
  effective_network: {
    mode: "direct",
    allowed_cidrs: ["10.0.0.0/8"],
    denied_cidrs: ["169.254.169.254/32"],
    domain_mode: null,
    allowed_domains: [],
    denied_domains: [],
  },
  terminal_enabled: true,
  infrastructure_terminal_enabled: true,
  effective_terminal_enabled: true,
  version: 7,
  digest: "sha256:workspace-runtime-profile-digest",
  available: true,
  availability_reason_code: null,
  capability_revision_id: infrastructureProfile.capability_revision_id,
  infrastructure_profile_version: infrastructureProfile.version,
  compatible: true,
  missing_capabilities: [],
  incompatible_constraints: [],
  created_at: "2026-07-31T06:00:00Z",
  updated_at: "2026-07-31T06:00:00Z",
};

const unavailableProfile: WorkspaceRuntimeProfileResponse = {
  ...availableProfile,
  id: "workspace-runtime-profile-gpu",
  display_name: "GPU runtime",
  description: "Preserved selection whose provider is currently unavailable.",
  version: 4,
  available: false,
  availability_reason_code: "provider_unavailable",
  capability_revision_id: null,
  compatible: false,
  missing_capabilities: ["runtime.gpu"],
};

const recreation: RuntimeRecreationOperationResponse = {
  id: "runtime-recreation-operation",
  target_kind: "workspace_runtime_profile",
  target_id: availableProfile.id,
  target_version: availableProfile.version.toString(),
  status: "running",
  concurrency_limit: 4,
  total_count: 5,
  pending_count: 1,
  running_count: 1,
  succeeded_count: 2,
  skipped_count: 0,
  failed_count: 1,
  created_at: "2026-07-31T06:05:00Z",
  started_at: "2026-07-31T06:05:01Z",
  completed_at: null,
  items: [
    {
      runtime_id: "runtime-failed",
      status: "failed",
      attempt: 1,
      dispatched_generation: 24,
      failure_code: "provider_rejected",
      failure_message: "The provider rejected the replacement request.",
      updated_at: "2026-07-31T06:06:00Z",
    },
  ],
};

const baseArgs: RuntimeProfilesContainerOutput = {
  handle: "acme",
  state: {
    type: "READY",
    profiles: [availableProfile, unavailableProfile],
    infrastructureProfiles: [infrastructureProfile],
    defaultProfile: {
      runtime_profile_id: availableProfile.id,
      version: 5,
      profile: availableProfile,
    },
  },
  editorState: { type: "CLOSED" },
  mutationState: { type: "IDLE", error: null },
  operationState: { type: "IDLE" },
  deletionState: { type: "CLOSED" },
  deletionFeedbackState: { type: "NONE" },
  canManage: true,
  canDelete: true,
  onOpenCreate: noop,
  onOpenEdit: noop,
  onCloseEditor: noop,
  onSubmit: noop,
  onSetDefault: noop,
  onRecreate: noop,
  onOpenDelete: noop,
  onCloseDelete: noop,
  onConfirmDelete: noop,
  onDismissDeletionFeedback: noop,
};

const meta = {
  component: RuntimeProfiles,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(1080)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: baseArgs,
} satisfies Meta<typeof RuntimeProfiles>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Populated = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Runtime profiles")).toBeVisible();
    await expect(canvas.getByText("Standard runtime")).toBeVisible();
    await expect(canvas.getByText("GPU runtime")).toBeVisible();
    await expect(canvas.getByText("Default")).toBeVisible();
  },
} satisfies Story;

export const Empty = {
  args: {
    state: {
      type: "READY",
      profiles: [],
      infrastructureProfiles: [infrastructureProfile],
      defaultProfile: {
        runtime_profile_id: null,
        version: 1,
        profile: null,
      },
    },
  },
} satisfies Story;

export const NoInfrastructureProfiles = {
  args: {
    state: {
      type: "READY",
      profiles: [],
      infrastructureProfiles: [],
      defaultProfile: {
        runtime_profile_id: null,
        version: 1,
        profile: null,
      },
    },
  },
} satisfies Story;

export const UnavailableDefaultPreserved = {
  args: {
    state: {
      type: "READY",
      profiles: [availableProfile, unavailableProfile],
      infrastructureProfiles: [infrastructureProfile],
      defaultProfile: {
        runtime_profile_id: unavailableProfile.id,
        version: 6,
        profile: unavailableProfile,
      },
    },
  },
} satisfies Story;

export const UnavailableProxyProfileEdit = {
  args: {
    state: {
      type: "READY",
      profiles: [
        {
          ...unavailableProfile,
          policy: {
            schema_version: 2,
            network_restriction: {
              mode: "proxy_required",
              allowed_cidrs: ["10.0.0.0/8"],
              denied_cidrs: [],
              domain_policy: {
                mode: "allowlist",
                allowed_domains: ["*.example.com"],
                denied_domains: ["blocked.example.com"],
              },
            },
          },
          infrastructure_network: {
            mode: "proxy_required",
            allowed_cidrs: ["10.0.0.0/8"],
            denied_cidrs: [],
            domain_mode: "unrestricted",
            allowed_domains: [],
            denied_domains: [],
          },
          effective_network: {
            mode: "proxy_required",
            allowed_cidrs: ["10.0.0.0/8"],
            denied_cidrs: [],
            domain_mode: "allowlist",
            allowed_domains: ["*.example.com"],
            denied_domains: ["blocked.example.com"],
          },
        },
      ],
      infrastructureProfiles: [],
      defaultProfile: {
        runtime_profile_id: null,
        version: 6,
        profile: null,
      },
    },
    editorState: {
      type: "EDIT",
      profile: {
        ...unavailableProfile,
        policy: {
          schema_version: 2,
          network_restriction: {
            mode: "proxy_required",
            allowed_cidrs: ["10.0.0.0/8"],
            denied_cidrs: [],
            domain_policy: {
              mode: "allowlist",
              allowed_domains: ["*.example.com"],
              denied_domains: ["blocked.example.com"],
            },
          },
        },
        infrastructure_network: {
          mode: "proxy_required",
          allowed_cidrs: ["10.0.0.0/8"],
          denied_cidrs: [],
          domain_mode: "unrestricted",
          allowed_domains: [],
          denied_domains: [],
        },
        effective_network: {
          mode: "proxy_required",
          allowed_cidrs: ["10.0.0.0/8"],
          denied_cidrs: [],
          domain_mode: "allowlist",
          allowed_domains: ["*.example.com"],
          denied_domains: ["blocked.example.com"],
        },
      },
    },
  },
} satisfies Story;

export const RecreationRunning = {
  args: {
    operationState: { type: "LOADED", operation: recreation },
  },
} satisfies Story;

export const CreateModal = {
  args: {
    editorState: { type: "CREATE" },
  },
} satisfies Story;

export const ProxyAllowlistCreateModal = {
  args: {
    state: {
      type: "READY",
      profiles: [],
      infrastructureProfiles: [proxyAllowlistInfrastructureProfile],
      defaultProfile: {
        runtime_profile_id: null,
        version: 1,
        profile: null,
      },
    },
    editorState: { type: "CREATE" },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      page.getByRole("textbox", {
        name: "Network mode",
      }),
    );
    await userEvent.click(
      page.getByRole("option", {
        name: "Managed proxy required",
      }),
    );
    const domainAuthority = page.getByRole("textbox", {
      name: "Proxy domain authority",
    });
    await expect(domainAuthority).toHaveValue(
      "Only explicitly allowed domains",
    );
    await userEvent.click(domainAuthority);
    await expect(
      page.queryByRole("option", {
        name: "All domains except explicit denials",
      }),
    ).not.toBeInTheDocument();
    await expect(
      page.getByRole("option", {
        name: "Only explicitly allowed domains",
      }),
    ).toBeVisible();
  },
} satisfies Story;

export const ManagerCannotDelete = {
  args: {
    canManage: true,
    canDelete: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getAllByRole("button", { name: "Edit" })[0],
    ).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: "Delete Standard runtime" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const DeleteConfirmation = {
  args: {
    deletionState: {
      type: "CONFIRMING",
      profile: availableProfile,
      error: null,
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    const confirmButton = page.getByRole("button", {
      name: "Delete profile permanently",
    });
    await expect(confirmButton).toBeDisabled();
    await userEvent.type(
      page.getByRole("textbox", { name: "Runtime profile name" }),
      availableProfile.display_name,
    );
    await userEvent.click(
      page.getByRole("checkbox", {
        name: /I understand that this deletion is permanent/,
      }),
    );
    await expect(confirmButton).toBeEnabled();
  },
} satisfies Story;

export const DeleteConflict = {
  args: {
    deletionState: {
      type: "CONFIRMING",
      profile: availableProfile,
      error: {
        kind: "CONFLICT",
        message: "Runtime Profile version conflict.",
      },
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await expect(page.getByText("The profile changed")).toBeVisible();
    await expect(
      page.getByText(/This deletion used a stale profile version/),
    ).toBeVisible();
  },
} satisfies Story;

export const DeleteFailure = {
  args: {
    deletionState: {
      type: "CONFIRMING",
      profile: availableProfile,
      error: {
        kind: "UNKNOWN",
        message: "The Runtime Profile service is unavailable.",
      },
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await expect(
      page.getByText("Runtime profile deletion failed"),
    ).toBeVisible();
    await expect(
      page.getByText("The Runtime Profile service is unavailable."),
    ).toBeVisible();
  },
} satisfies Story;

export const DeleteSuccess = {
  args: {
    state: {
      type: "READY",
      profiles: [unavailableProfile],
      infrastructureProfiles: [infrastructureProfile],
      defaultProfile: {
        runtime_profile_id: null,
        version: 6,
        profile: null,
      },
    },
    deletionFeedbackState: {
      type: "SUCCESS",
      profileName: availableProfile.display_name,
      result: {
        profile_id: availableProfile.id,
        cleared_workspace_default: true,
        cleared_agent_count: 2,
        affected_running_runtime_count: 1,
        superseded_recreation_operation_count: 1,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("Standard runtime was permanently deleted"),
    ).toBeVisible();
    await expect(
      canvas.getByText("The workspace default was cleared."),
    ).toBeVisible();
    await expect(
      canvas.getByText("2 agent selections were cleared."),
    ).toBeVisible();
    await expect(
      canvas.getByText(
        "1 running runtime kept its applied configuration and storage.",
      ),
    ).toBeVisible();
    await expect(
      canvas.getByText("1 active recreation operation was superseded."),
    ).toBeVisible();
  },
} satisfies Story;

export const Loading = {
  args: {
    state: { type: "LOADING" },
  },
} satisfies Story;

export const Error = {
  args: {
    state: {
      type: "ERROR",
      message: "Runtime Profiles could not be loaded.",
    },
  },
} satisfies Story;
