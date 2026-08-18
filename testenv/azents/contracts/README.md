# Prerequisite Contracts

`testenv/azents/contracts/` contains YAML contracts for external credentials and external prerequisite state.

Contract kinds:

- `credential` checks whether a required secret source is available.
- `prerequisite` performs a bounded external or local-state check that may depend on credentials.

The prerequisite prepare phase evaluates the selected contracts and writes a snapshot. Tests and fixture commands consume that snapshot instead of invoking prerequisite checks during test execution.

Current contracts:

- `bedrock-aws.yaml` — verifies that usable AWS shared credentials are available for the Bedrock profile or key configuration.
- `browser-oauth.yaml` — verifies that the browser/OAuth storage-state cache is available.

Snapshots must contain safe metadata and remediation guidance only. Never store raw access keys, secret keys, tokens, passwords, cookies, or browser credentials in a snapshot.
