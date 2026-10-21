import { useTranslations } from "next-intl";
import { expect, fn, within } from "storybook/test";
import { RuntimeProfileDeleteModalView } from "./RuntimeProfileDeleteModal";
import type { WorkspaceRuntimeProfileResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const profile: WorkspaceRuntimeProfileResponse = {
  id: "runtime-preview",
  provider_id: "provider-preview",
  infrastructure_profile_id: "infra-preview",
  display_name: "Preview Runtime",
  description: "",
  lifecycle: "active",
  policy: { schema_version: 1, network_restriction: null },
  infrastructure_network: null,
  effective_network: null,
  terminal_enabled: true,
  infrastructure_terminal_enabled: true,
  effective_terminal_enabled: true,
  version: 1,
  digest: "preview",
  available: true,
  availability_reason_code: null,
  capability_revision_id: null,
  infrastructure_profile_version: 1,
  compatible: true,
  missing_capabilities: [],
  incompatible_constraints: [],
  created_at: "2026-10-22T00:00:00Z",
  updated_at: "2026-10-22T00:00:00Z",
};
function Fixture(): React.ReactElement {
  const t = useTranslations("workspace.runtimeProfiles");
  return (
    <RuntimeProfileDeleteModalView
      t={t}
      profile={profile}
      onClose={fn()}
      onConfirm={fn()}
      isSubmitting
      confirmationName={profile.display_name}
      setConfirmationName={fn()}
      acknowledged
      setAcknowledged={fn()}
      isConfirmed
      error={null}
    />
  );
}
const meta = { component: Fixture, tags: ["ci-contract"] } satisfies Meta<
  typeof Fixture
>;
export default meta;
export const Submitting = {
  play: async ({ canvasElement }) => {
    const dialog = within(canvasElement.ownerDocument.body).getByRole("dialog");
    for (const input of dialog.querySelectorAll("input")) {
      await expect(input).toBeDisabled();
    }
  },
} satisfies StoryObj<typeof meta>;
