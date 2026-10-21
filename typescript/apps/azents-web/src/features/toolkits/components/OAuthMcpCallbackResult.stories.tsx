import { useTranslations } from "next-intl";
import { OAuthMcpCallbackResultView } from "./OAuthMcpCallbackResult";
import type { OAuthMcpCallbackResultViewProps } from "../containers/useOAuthMcpCallbackResultController";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
function Fixture(
  props: Omit<OAuthMcpCallbackResultViewProps, "t">,
): React.ReactElement {
  const t = useTranslations("oauth");
  return <OAuthMcpCallbackResultView {...props} t={t} />;
}
const meta = {
  tags: ["ci-contract"],
  component: Fixture,
  args: { success: true, message: null, returnHref: null },
} satisfies Meta<typeof Fixture>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Success = {} satisfies Story;
export const Failure = {
  args: { success: false, message: "Authorization was declined." },
} satisfies Story;
export const ReturnLink = {
  args: {
    returnHref: "/w/preview/settings/toolkits",
    message: "Toolkit connected.",
  },
} satisfies Story;
