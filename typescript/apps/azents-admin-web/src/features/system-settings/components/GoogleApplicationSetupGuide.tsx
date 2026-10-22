import { Anchor, Code, List, Stack, Text } from "@mantine/core";

export function GoogleApplicationSetupGuide(): React.ReactElement {
  return (
    <Stack gap="sm">
      <Text size="sm">
        Set up one operator-owned OAuth application, then let users connect
        their Google accounts from Google Toolkit settings.
      </Text>
      <List type="ordered" spacing="md" size="sm">
        <List.Item>
          <Text size="sm" fw={600}>
            Choose a Cloud project and enable the APIs
          </Text>
          In the{" "}
          <Anchor
            href="https://console.cloud.google.com/"
            target="_blank"
            rel="noopener noreferrer"
          >
            Google Cloud console
          </Anchor>
          , create or select the project that owns the OAuth application. In
          APIs &amp; Services → Library, enable Google Calendar API, Google
          Drive API and Gmail API for the services you need. Azents uses their
          supported direct APIs. Optional file selection also requires the
          Google Picker API in the same project.
        </List.Item>
        <List.Item>
          <Text size="sm" fw={600}>
            Configure the OAuth consent screen
          </Text>
          In Google Auth Platform, configure Branding, Audience and Data Access.
          Choose Internal for eligible Workspace organizations or External. For
          an External application in Testing, add each connecting account under
          Test users. Follow Google&apos;s{" "}
          <Anchor
            href="https://developers.google.com/workspace/guides/configure-oauth-consent"
            target="_blank"
            rel="noopener noreferrer"
          >
            consent setup instructions
          </Anchor>
          . Configure the supported scopes for the services you offer, plus
          openid and email for account identity. Toolkit connection
          automatically requests the supported read and write scopes for enabled
          services; users choose which permissions to grant on Google&apos;s
          consent screen. Publishing, restricted-scope verification and
          account-policy eligibility remain separate Google requirements; saving
          these settings does not verify them.
          <details>
            <summary>
              Examples of access requests and their consequences
            </summary>
            <Stack gap="xs" mt="xs">
              <Text size="sm">
                Google consent is where users choose their permissions. Actual
                returned scopes determine supported actions in each enabled
                service.
              </Text>
              <Text size="sm" fw={600}>
                Calendar
              </Text>
              <Code
                block
                style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
              >{`https://www.googleapis.com/auth/calendar.events.readonly
https://www.googleapis.com/auth/calendar.calendarlist.readonly
https://www.googleapis.com/auth/calendar.events.freebusy
https://www.googleapis.com/auth/calendar.events
https://www.googleapis.com/auth/calendar.app.created`}</Code>
              <Text size="sm">
                Event editing includes deletion and supported status changes.
                Secondary-calendar creation is a separate request.
              </Text>
              <Text size="sm" fw={600}>
                Drive
              </Text>
              <Code
                block
                style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
              >{`https://www.googleapis.com/auth/drive
https://www.googleapis.com/auth/drive.readonly
https://www.googleapis.com/auth/drive.file`}</Code>
              <Text size="sm">
                Drive connection offers supported read and write permissions on
                Google&apos;s consent screen. App-file access is read/write, not
                read-only. Whole-Drive read plus app-file access permits whole
                reads but only app-file writes; selecting a folder does not
                authorize every descendant.
              </Text>
              <Text size="sm" fw={600}>
                Gmail
              </Text>
              <Code
                block
                style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
              >{`https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/gmail.compose
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/gmail.send
https://www.googleapis.com/auth/gmail.settings.basic`}</Code>
              <Text size="sm">
                Compose and modify grants include supported sending; they are
                not drafts-only or organize-only. Filter management can affect
                future automatic forwarding.
              </Text>
            </Stack>
          </details>
        </List.Item>
        <List.Item>
          <Text size="sm" fw={600}>
            Create a Web application client and register the callback
          </Text>
          Go to Google Auth Platform → Clients → Create Client, choose Web
          application, and add the exact Registered callback URL under
          Authorized redirect URIs. The scheme, host and path must match. If
          unavailable, configure the public Web URL first.
        </List.Item>
        <List.Item>
          <Text size="sm" fw={600}>
            Optionally prepare Google Picker
          </Text>
          Enable the Google Picker API. Create a browser API key restricted to
          the public Web origin using HTTP referrers and restrict its API use to
          Google Picker. Enter the key and numeric Cloud project number below.
          Use the same project as the OAuth application. See the{" "}
          <Anchor
            href="https://developers.google.com/workspace/drive/picker/guides/web-picker"
            target="_blank"
            rel="noopener noreferrer"
          >
            official Picker integration guide
          </Anchor>
          . Picker needs an actual drive.file grant and a renewable saved
          connection. No main account token is delivered to the browser;
          unavailable minimal credentials leave other Google tools unaffected.
        </List.Item>
        <List.Item>
          <Text size="sm" fw={600}>
            Save credentials, then connect a Toolkit
          </Text>
          Save Client ID and Client secret replacement below. Do not share the
          secret or paste a downloaded client JSON file. In Toolkit settings,
          choose services, connect a Google account, choose permissions on
          Google&apos;s consent screen, review actual access, then explicitly
          save. Later service switches save locally without new consent. To
          grant additional permissions, explicitly reconnect through Google.
        </List.Item>
      </List>
      <Text size="sm" c="dimmed">
        Environment-managed installations can set{" "}
        <Code>AZ_GOOGLE_OAUTH_CLIENT_ID</Code>,{" "}
        <Code>AZ_GOOGLE_OAUTH_CLIENT_SECRET</Code>, and optional{" "}
        <Code>AZ_GOOGLE_PICKER_API_KEY</Code> /{" "}
        <Code>AZ_GOOGLE_PICKER_APP_ID</Code>. Environment-owned fields are
        read-only here.
      </Text>
      <Text size="sm" c="dimmed">
        This screen saves application preparation, not an account connection,
        and does not test live service access or Google verification. Actual
        account and resource restrictions continue to apply.
      </Text>
    </Stack>
  );
}
