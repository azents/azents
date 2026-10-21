import { SystemSettingsPage } from "@/features/system-settings/SystemSettingsPage";

export default function SystemSettingsRouteLayout({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <>
      <SystemSettingsPage />
      {children}
    </>
  );
}
