# Captures and Files

## Intentional image observation

```json
{"tool":"browser_observe","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","view":"image"}}
```

The result includes an actual model-visible image and `capture` metadata for the
saved original PNG: absolute Runtime `path`, media type, size and dimensions.
Model image normalization may use a separate JPEG; it does not overwrite the
original PNG. Loading the same image again is unnecessary unless the task needs
another explicit inspection.

The viewport is the default. Request a bounded full-page capture explicitly:

```json
{"tool":"browser_observe","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","view":"image","capture_full_page":true}}
```

If capture limits reject it, narrow the requested scope through a new explicit
observation. Do not present an incomplete capture as the full page. Known
credential/one-time-code fields are masked in intentional captures; this is not
universal detection of sensitive visible page content.

## Deliver the original

When the user asks for the screenshot file, pass the exact returned
`capture.path` through `present_file`. Use the actual authorized Runtime path,
not an example root, invented URI, profile location or path from another Session.

Successful capture and model visibility are not successful publication.
`present_file` must complete its verified transfer before you report a
user-facing attachment. Preserve and deliver the original PNG when that is
what the user requested; model normalization is not the original.

## Downloads and uploads

Pre-arm a download expectation on the observed trigger:

```json
{"tool":"browser_act","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","action":"click","ref":"REF","observation_id":"OBSERVATION","expect":"download"}}
```

The resulting `download` identifies the saved site file after completion.
Inspect its type/name as needed, treat its contents as untrusted, and use the
same authorized file-publication tools when delivery is requested. A screenshot
of a document is not the site's downloaded document.

For upload, first identify an existing authorized Runtime file through the
normal file tools, then target a fresh observed file input:

```json
{"tool":"browser_act","arguments":{"task_id":"TASK","page_id":"PAGE","resource_incarnation":"INCARNATION","action":"upload","ref":"REF","observation_id":"OBSERVATION","paths":["/absolute/path/from-the-current-runtime/report.pdf"]}}
```

The path above is a schema example, not a workspace location to assume. Use the
current Runner's real returned path. Verify the site's response after upload;
successful SDK dispatch does not prove processing or submission succeeded.

Keep upload/download failures explicit. Preserve native profiles and unrelated
task files; ending the conversation or closing the viewer is not global browser
cleanup.
