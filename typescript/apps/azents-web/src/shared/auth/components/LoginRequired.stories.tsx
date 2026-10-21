import { useTranslations } from "next-intl";
import { LoginRequiredView } from "./LoginRequired";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
function Fixture(): React.ReactElement {
  const t = useTranslations("auth");
  return <LoginRequiredView t={t} loginUrl="/login?next=%2Fw%2Fpreview" />;
}
const meta = { component: Fixture, tags: ["ci-contract"] } satisfies Meta<
  typeof Fixture
>;
export default meta;
export const LoginRequired = {} satisfies StoryObj<typeof meta>;
