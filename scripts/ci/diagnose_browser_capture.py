"""Temporary content-free SDK phase instrumentation, not acceptance evidence."""

import hashlib
import json
import os
import sys
from pathlib import Path


def main() -> None:
    bundle = Path(sys.argv[1])
    source = bundle.read_text()
    trace_path = os.environ.get("AZ_CAPTURE_TRACE")
    if trace_path:
        Path(trace_path).with_name("sdk-source-facts.json").write_text(
            json.dumps(
                {
                    "original_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "field_trial_config_disabled_by_sdk": (
                        '"--disable-field-trial-config",' in source
                    ),
                    "experiment_surface_deadline_zero": (
                        os.environ.get("AZ_CAPTURE_SURFACE_DEADLINE_ZERO") == "1"
                    ),
                }
            )
        )
    if os.environ.get("AZ_CAPTURE_SURFACE_DEADLINE_ZERO") == "1":
        old = (
            'process.env.PLAYWRIGHT_LEGACY_SCREENSHOT ? "" : '
            '"--enable-features=CDPScreenshotNewSurface",'
        )
        new = (
            'process.env.PLAYWRIGHT_LEGACY_SCREENSHOT ? "" : '
            '"--enable-features=CDPScreenshotNewSurface,'
            'InitialWebUISurfaceSync:deadline_in_frames/0",'
        )
        if source.count(old) != 1:
            raise RuntimeError("Pinned Chromium feature argument mismatch")
        source = source.replace(old, new)
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
function azNativeTraceEvent(message) {
  if (message.method === "Tracing.tracingComplete") {
    azCaptureTrace("native_trace_complete");
    return;
  }
  if (message.method !== "Tracing.dataCollected") return;
  const allowed = new Set([
    "Surface deadline passed", "SurfaceSynchronizationEvent",
    "CopyOutputRequest", "Damage not visible.",
    "LayerTreeHostImpl::DidNotProduceFrame",
    "LayerTreeHostImpl::ActivateSyncTree", "Display::DrawAndSwap",
    "DisplayScheduler::DrawAndSwap", "DirectRenderer::DrawFrame",
    "Scheduler::OnBeginImplFrameDeadline", "PipelineReporter",
    "GpuChannelHost::CreateViewCommandBuffer", "GPUProcessHost::Init",
    "GpuProcessHost::Init", "SkiaOutputSurfaceImpl::Reshape",
    "SkiaOutputSurfaceImplOnGpu::Initialize", "CopyOutputResult"
  ]);
  const categories = new Set([
    "viz", "cc", "gpu", "benchmark", "disabled-by-default-viz.debug"
  ]);
  for (const event of message.params.value) {
    if (!allowed.has(event.name) || typeof event.cat !== "string" ||
        !event.cat.split(",").some(value => categories.has(value))) continue;
    const args = event.args || {};
    const record = {diagnostic_only:true, stage:"native_trace",
      name:event.name, ts:event.ts, dur:event.dur || 0,
      ph:event.ph, pid:event.pid, tid:event.tid,
      duration_ms:typeof args.duration_ms === "number" ? args.duration_ms : null,
      success:typeof args.success === "boolean" ? args.success : null};
    try {
      require("node:fs").appendFileSync(process.env.AZ_CAPTURE_TRACE,
        JSON.stringify(record)+"\\n");
    } catch {}
  }
}
function azClaimNativeTrace() {
  if (!process.env.AZ_CAPTURE_NATIVE_ONCE) return false;
  try {
    const fs = require("node:fs");
    fs.closeSync(fs.openSync(process.env.AZ_CAPTURE_TRACE+".native-once", "wx"));
    return true;
  } catch { return false; }
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
    if os.environ.get("AZ_CAPTURE_NATIVE_ONCE") == "1":
        old = "      async _onMessage(message) {\n        this._protocolLogger"
        connection = source.index("CRConnection = class")
        event_start = source.index(old, connection)
        if event_start >= source.index("CRSession = class", connection):
            raise RuntimeError("Pinned Chromium trace event anchor mismatch")
        source = source[:event_start] + source[event_start:].replace(
            old,
            "      async _onMessage(message) {\n"
            "        azNativeTraceEvent(message);\n        this._protocolLogger",
            1,
        )
        old = "        const started = Number(process.hrtime.bigint())/1000000;"
        source = source.replace(
            old,
            """        let nativeTrace = false;
        if (method2 === "Page.captureScreenshot" && azClaimNativeTrace()) {
          try {
            await this._connection.rootSession.send("Tracing.start", {
              categories:"viz,cc,gpu,benchmark,disabled-by-default-viz.debug",
              transferMode:"ReportEvents", options:"record-until-full"
            });
            nativeTrace = true;
            azCaptureTrace("native_trace_started");
          } catch { azCaptureTrace("native_trace_start_failed"); }
        }
"""
            + old,
        )
        old = "            Number(process.hrtime.bigint())/1000000-started);"
        source = source.replace(
            old,
            old
            + """
          if (nativeTrace) {
            try {
              await this._connection.rootSession.send("Tracing.end");
              azCaptureTrace("native_trace_end_sent");
            } catch { azCaptureTrace("native_trace_end_failed"); }
          }""",
        )
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
