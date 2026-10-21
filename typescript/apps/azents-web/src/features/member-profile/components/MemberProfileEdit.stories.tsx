import { useTranslations } from "next-intl";
import { fn } from "storybook/test";
import { ProfileFormView } from "./MemberProfileEdit";
import type { ProfileFormViewProps } from "../containers/useProfileFormController";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
function Fixture(props: Omit<ProfileFormViewProps, "t">): React.ReactElement {
  const t = useTranslations("memberProfile");
  return <ProfileFormView {...props} t={t} />;
}
const meta = {
  tags: ["ci-contract"],
  component: Fixture,
  args: {
    formState: { type: "IDLE" },
    name: "Preview Member",
    onSubmit: fn(),
    setName: fn(),
    nameError: null,
    setNameError: fn(),
    handleSubmit: fn((event: React.FormEvent): void => event.preventDefault()),
    isSubmitting: false,
  },
} satisfies Meta<typeof Fixture>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Ready = {} satisfies Story;
export const ValidationError = {
  args: { nameError: "Name is required." },
} satisfies Story;
export const ServerError = {
  args: { formState: { type: "ERROR", message: "Unable to update profile." } },
} satisfies Story;
export const Success = {
  args: { formState: { type: "SUCCESS" } },
} satisfies Story;
export const Submitting = {
  args: { formState: { type: "SUBMITTING" }, isSubmitting: true },
} satisfies Story;
