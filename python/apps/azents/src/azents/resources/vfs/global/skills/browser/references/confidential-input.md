# Delegated confidential input

Use this path for authorized Browser `fill` using a configured Agent Runtime
environment value. Environment provisioning delegates reading and use; it is not
a prohibition against the Agent accessing the value. Avoid unnecessarily echoing
that value into tool arguments, output, files or diagnostics.

1. Obtain the current task/page/incarnation and DOM field reference plus its
   observation ID. Keep existing Browser and site authority checks.
2. Import `azents://skills/azents/browser/scripts/encrypt.py` with `import_file`.
   Save the returned absolute Runtime path. A VFS URI is not a shell path.
3. Execute the imported script with `exec_command`, substituting its actual path:

   ```console
   uv run --no-project --script '<returned Runtime path>' --env NAVER_PASSWORD
   ```

   Pass the environment variable **name**, never `$NAVER_PASSWORD`, command
   substitution, a plaintext argument or a plaintext `echo`. The script reads the
   source value and current `AZENTS_BROWSER_INPUT_PUBLIC_KEY` internally.
   Inline dependency metadata prepares PyNaCl in a Runtime-side uv environment;
   the Runner application interpreter is not used. If uv is missing, follow the
   existing Runtime user-space tool provisioning policy. Package downloads must
   respect Runtime network policy; unavailable dependencies stop this workflow.
4. If still running, use `wait` for interruptible completion waiting, then collect
   output with `write_stdin` (`yield_time_ms=0` for immediate collection). Waiting
   may return for user input or other work; check the process result and repeat
   only if completion is still needed. Require exit code zero and exactly one
   complete ciphertext line from stdout. Package messages
   or errors on stderr are not the ciphertext. Do not display the source value
   to diagnose errors.
5. Call `browser_act` with `action="fill"`, the current identities/reference,
   `encrypted_text` equal to that stdout line unchanged, and `text` null/omitted.
   Exactly one of `text` and `encrypted_text` is allowed. Only fill accepts
   encrypted input; ordinary `text` remains literal, including Base64-like text.
6. Repeat with the authorized account environment variable for another field.
   Verify the site outcome through observation without requesting the input
   value back. Human CAPTCHA/MFA/sign-in help remains available when needed.

The script accepts explicitly empty values and at most 4096 UTF-8 bytes.
Import, missing key/value, dependency and encryption failures do not authorize a
plaintext fallback. An older Run may not contain this projected script; a
compatible new Run and Runner are required for the feature.

Runner process replacement loses its private key. Old ciphertext then fails;
prepare again in a new command with the current public key and refresh stale
Browser references. A timeout or lost fill result can mean the field was already
changed: observe before deciding another action and never replay automatically.

The receiving site necessarily sees the value and may echo it in later content.
This is low-retention input delivery, not a vault, site-output filter, one-use
token or new permission grant. Keep native tabs and profiles intact on failure.
