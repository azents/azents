"""Temporary content-free SDK phase instrumentation, not acceptance evidence."""

import sys
from pathlib import Path


def main() -> None:
    bundle = Path(sys.argv[1])
    source = bundle.read_text()
    helper = """
function azCaptureTrace(stage, elapsed) {
  if (!process.env.AZ_CAPTURE_TRACE) return;
  try {
    require('node:fs').appendFileSync(process.env.AZ_CAPTURE_TRACE, JSON.stringify({
      diagnostic_only:true, pid:process.pid, stage,
      monotonic_ms:Number(process.hrtime.bigint())/1000000,
      elapsed_ms:elapsed === undefined ? null : elapsed
    })+'\\n');
  } catch {
    // Missing diagnostic evidence invalidates the experiment, not the SDK call.
  }
}
"""
    replacements = {
        "      async screenshotPage(progress2, options) {": (
            "      async screenshotPage(progress2, options) {\n"
            '        azCaptureTrace("sdk_screenshot_enter");'
        ),
        '          progress2.log("taking page screenshot");': (
            '          progress2.log("taking page screenshot");\n'
            '          azCaptureTrace("sdk_queue_enter");'
        ),
        '            progress2.log("waiting for fonts to load...");': (
            '            azCaptureTrace("sdk_font_wait_start");\n'
            '            progress2.log("waiting for fonts to load...");'
        ),
        '            progress2.log("fonts loaded");': (
            '            azCaptureTrace("sdk_font_wait_end");\n'
            '            progress2.log("fonts loaded");'
        ),
    }
    for old, new in replacements.items():
        if source.count(old) != 1:
            raise RuntimeError("Pinned SDK diagnostic anchor mismatch")
        source = source.replace(old, new)
    session = source.index("CRSession = class _CRSession")
    start = source.index("      async send(method2, params2) {", session)
    end = source.index("      _sendMayFail(method2, params2)", start)
    original = source[start:end]
    if "this._connection._rawSend" not in original:
        raise RuntimeError("Pinned SDK diagnostic send mismatch")
    replacement = """      async send(method2, params2) {
        if (this._crashed || this._closed || this._connection._closed ||
            this._connection._browserDisconnectedLogs)
          throw new ProtocolError(this._crashed ? "crashed" : "closed", void 0,
            this._connection._browserDisconnectedLogs);
        const traced = method2 === "Page.captureScreenshot" ||
          method2 === "Page.getLayoutMetrics";
        const started = Number(process.hrtime.bigint())/1000000;
        if (traced) azCaptureTrace(method2+"_send");
        const id = this._connection._rawSend(this._sessionId, method2, params2);
        try {
          return await new Promise((resolve, reject) => {
            this._callbacks.set(id, { resolve, reject,
              error: new ProtocolError("error", method2) });
          });
        } finally {
          if (traced) azCaptureTrace(method2+"_complete",
            Number(process.hrtime.bigint())/1000000-started);
        }
      }
"""
    source = source[:start] + replacement + source[end:]
    directive = '"use strict";'
    if not source.startswith(directive):
        raise RuntimeError("Pinned SDK directive prologue mismatch")
    source = directive + helper + source[len(directive) :]
    # uv may hardlink installed files to its shared cache; replace only this copy.
    temporary = bundle.with_suffix(".diagnostic.tmp")
    temporary.write_text(source)
    temporary.replace(bundle)


if __name__ == "__main__":
    main()
