import { Anchor, Code, List, Stack, Text } from "@mantine/core";

export function GoogleApplicationSetupGuide(): React.ReactElement {
  return (
    <Stack gap="sm">
      <Text size="sm">
        Set up one operator-owned OAuth application, then let users connect
        their Google accounts from the Google Toolkit setup.
      </Text>
      <List type="ordered" spacing="md" size="sm">
        <List.Item>
          <Text size="sm" fw={600}>
            Get Preview access and choose a Cloud project
          </Text>
          Confirm access to the{" "}
          <Anchor
            href="https://developers.google.com/workspace/preview"
            target="_blank"
            rel="noopener noreferrer"
          >
            Google Workspace Developer Preview Program
          </Anchor>
          . In the{" "}
          <Anchor
            href="https://console.cloud.google.com/"
            target="_blank"
            rel="noopener noreferrer"
          >
            Google Cloud console
          </Anchor>
          , create or select the project that will own this OAuth application.
          Use the same project for the following steps.
        </List.Item>
        <List.Item>
          <Text size="sm" fw={600}>
            Enable the Google services you plan to use
          </Text>
          In APIs &amp; Services → Library, enable Google Calendar API, Google
          Drive API and Gmail API for the services you need. Also enable their
          MCP services: <Code>calendarmcp.googleapis.com</Code>,{" "}
          <Code>drivemcp.googleapis.com</Code> and{" "}
          <Code>gmailmcp.googleapis.com</Code>. Follow Google&apos;s{" "}
          <Anchor
            href="https://developers.google.com/workspace/guides/configure-mcp-servers"
            target="_blank"
            rel="noopener noreferrer"
          >
            Workspace MCP setup guide
          </Anchor>{" "}
          for current Preview enrollment and service-enablement instructions.
          Azents uses Calendar, Drive and Gmail, not every Workspace service
          listed in that guide.
        </List.Item>
        <List.Item>
          <Text size="sm" fw={600}>
            Configure the OAuth consent screen
          </Text>
          Open Google Auth Platform. In Branding, enter the app name, support
          email and developer contact details. In Audience, choose Internal
          (eligible Workspace organizations only) or External. If External is in
          Testing, add each account that will connect under Test users. In Data
          Access, add scopes for the tasks you intend to allow; see
          Google&apos;s{" "}
          <Anchor
            href="https://developers.google.com/workspace/guides/configure-oauth-consent"
            target="_blank"
            rel="noopener noreferrer"
          >
            consent setup instructions
          </Anchor>
          . Azents requests only the selected Toolkit tasks plus account
          identity (openid and email). Publishing and any required Google
          verification are separate from saving these settings.
          <details>
            <summary>OAuth scopes for supported tasks</summary>
            <Stack gap="xs" mt="xs">
              <Text size="sm">
                Add only the scopes for tasks you intend to offer, plus openid
                and email for account identity. These are the exact service
                scope values used by Azents:
              </Text>
              <Text size="sm" fw={600}>
                Calendar: read, availability and edit
              </Text>
              <Code
                block
                style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
              >
                {`https://www.googleapis.com/auth/calendar.calendarlist.readonly
https://www.googleapis.com/auth/calendar.events.readonly
https://www.googleapis.com/auth/calendar.events.freebusy
https://www.googleapis.com/auth/calendar.events`}
              </Code>
              <Text size="sm" fw={600}>
                Drive: read and selected-file access
              </Text>
              <Code
                block
                style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
              >
                {`https://www.googleapis.com/auth/drive.readonly
https://www.googleapis.com/auth/drive.file`}
              </Code>
              <Text size="sm" fw={600}>
                Gmail: read, drafts and modification
              </Text>
              <Code
                block
                style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
              >
                {`https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/gmail.compose
https://www.googleapis.com/auth/gmail.modify`}
              </Code>
            </Stack>
          </details>
        </List.Item>
        <List.Item>
          <Text size="sm" fw={600}>
            Create a Web application client and register the callback
          </Text>
          Go to Google Auth Platform → Clients → Create Client. Choose Web
          application and enter a name. Under Authorized redirect URIs (not
          Authorized JavaScript origins), add the exact Registered callback URL
          displayed below, then create the client. The scheme, host and path
          must all match; do not add a trailing slash. If the URL is
          unavailable, configure Azents&apos; public Web URL first.
        </List.Item>
        <List.Item>
          <Text size="sm" fw={600}>
            Save the credentials here, then connect a Toolkit
          </Text>
          Copy Google&apos;s Client ID into Client ID below and its Client
          secret into Client secret replacement, then select Save application
          settings. Do not paste a downloaded client JSON file or share the
          secret. Next, create a Google Toolkit in Azents, select the tasks you
          need, connect a Google account, review the returned permissions and
          security notice, and explicitly save the connection.
        </List.Item>
      </List>
      <Text size="sm" c="dimmed">
        Environment-managed installations can set{" "}
        <Code>AZ_GOOGLE_OAUTH_CLIENT_ID</Code> and{" "}
        <Code>AZ_GOOGLE_OAUTH_CLIENT_SECRET</Code> instead. A field supplied by
        the process environment is read-only here; update it in the deployment
        configuration.
      </Text>
      <Text size="sm" c="dimmed">
        This screen saves the OAuth application, not a Google account
        connection, and does not test Preview eligibility or live service
        access. Google Toolkits do not expose Gmail sending. Drive selected-file
        access (drive.file) does not enable whole-Drive search.
      </Text>
    </Stack>
  );
}
