import { Box, rem, ThemeIcon } from "@mantine/core";
import {
  IconBrandAws,
  IconBrandGithub,
  IconBrandGoogleAnalytics,
  IconBrandNotion,
  IconBrandSentry,
  IconTool,
  IconVariable,
} from "@tabler/icons-react";
import type { ReactElement } from "react";

interface ToolkitTypeIconProps {
  toolkitType: string;
  size?: number;
}

/** Release-owned presentation only; the server owns Provider availability. */
export function ToolkitTypeIcon({
  toolkitType,
  size = 40,
}: ToolkitTypeIconProps): ReactElement {
  const markSize = size * 0.6;
  let mark: ReactElement;
  switch (toolkitType) {
    case "github":
      mark = <IconBrandGithub size={markSize} stroke={1.7} />;
      break;
    case "notion":
      mark = <IconBrandNotion size={markSize} stroke={1.7} />;
      break;
    case "sentry":
      mark = <IconBrandSentry size={markSize} stroke={1.7} />;
      break;
    case "aws":
      mark = <IconBrandAws size={markSize} stroke={1.7} />;
      break;
    case "google_analytics":
      mark = <IconBrandGoogleAnalytics size={markSize} stroke={1.7} />;
      break;
    case "envvar":
      mark = <IconVariable size={markSize} stroke={1.7} />;
      break;
    case "gcp":
    case "brave_search":
    case "kubernetes":
    case "mcp": {
      const asset = {
        gcp: "googlecloud",
        brave_search: "brave",
        kubernetes: "kubernetes",
        mcp: "modelcontextprotocol",
      }[toolkitType];
      mark = (
        <Box
          w={rem(markSize)}
          h={rem(markSize)}
          style={{
            backgroundColor: "currentColor",
            mask: `url(/brand/toolkits/${asset}.svg) center / contain no-repeat`,
            WebkitMask: `url(/brand/toolkits/${asset}.svg) center / contain no-repeat`,
          }}
        />
      );
      break;
    }
    default:
      mark = <IconTool size={markSize} stroke={1.7} />;
  }
  return (
    <ThemeIcon
      size={rem(size)}
      variant="default"
      radius="md"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      {mark}
    </ThemeIcon>
  );
}
