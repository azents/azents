"""Temporary content-free SDK phase instrumentation, not acceptance evidence."""

import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path


def sample_gpu(marker: Path, output: Path) -> None:
    """Observe startup CPU/state; sampling delays never gate browser behavior."""
    deadline = time.monotonic() + 300
    while not marker.exists():
        if time.monotonic() >= deadline:
            return
        time.sleep(0.05)
    deadline = time.monotonic() + 15
    with output.open("w") as stream:
        stream.write(
            json.dumps(
                {
                    "stage": "sampler_started",
                    "monotonic_ms": time.monotonic_ns() / 1_000_000,
                    "ticks_per_second": os.sysconf("SC_CLK_TCK"),
                }
            )
            + "\n"
        )
        while time.monotonic() < deadline:
            observed = 0
            for proc in Path("/proc").glob("[0-9]*"):
                try:
                    arguments = (proc / "cmdline").read_bytes()
                    # Chromium rewrites argv into one space-delimited title.
                    if not re.search(
                        rb"(?:^|[\0\s])--type=gpu-process(?:[\0\s]|$)", arguments
                    ):
                        continue
                    fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
                    state = fields[0] if fields[0] in "RSDTZtWXPI" else "unknown"
                    try:
                        wait = (proc / "wchan").read_text().strip()
                    except PermissionError:
                        wait = "unavailable"
                    if "futex" in wait:
                        wait_kind = "futex"
                    elif "poll" in wait:
                        wait_kind = "poll"
                    elif any(
                        name in wait
                        for name in ("folio_wait", "filemap", "wait_on_page")
                    ):
                        wait_kind = "page_io"
                    elif "io_schedule" in wait or "wait_on_buffer" in wait:
                        wait_kind = "io_schedule"
                    elif wait == "0":
                        wait_kind = "running_or_unavailable"
                    elif wait == "unavailable":
                        wait_kind = "unavailable"
                    else:
                        wait_kind = "other"
                    read_bytes = None
                    read_calls = None
                    try:
                        for line in (proc / "io").read_text().splitlines():
                            key, value = line.split(":", 1)
                            if key == "read_bytes":
                                read_bytes = int(value)
                            elif key == "syscr":
                                read_calls = int(value)
                    except PermissionError:
                        # Preserve missing evidence instead of assuming zero I/O.
                        pass
                    record = {
                        "stage": "gpu_cpu_sample",
                        "monotonic_ms": time.monotonic_ns() / 1_000_000,
                        "pid": int(proc.name),
                        "ppid": int(fields[1]),
                        "state": state,
                        "user_ticks": int(fields[11]),
                        "system_ticks": int(fields[12]),
                        "minor_faults": int(fields[7]),
                        "major_faults": int(fields[9]),
                        "read_bytes": read_bytes,
                        "read_calls": read_calls,
                        "wait_kind": wait_kind,
                    }
                    stream.write(json.dumps(record) + "\n")
                    observed += 1
                except FileNotFoundError, ProcessLookupError, PermissionError:
                    # Process churn/containment is missing diagnostic evidence.
                    continue
            stream.write(
                json.dumps(
                    {
                        "stage": "sampler_tick",
                        "monotonic_ms": time.monotonic_ns() / 1_000_000,
                        "gpu_processes": observed,
                    }
                )
                + "\n"
            )
            stream.flush()
            time.sleep(0.05)
        stream.write(
            json.dumps(
                {
                    "stage": "sampler_finished",
                    "monotonic_ms": time.monotonic_ns() / 1_000_000,
                }
            )
            + "\n"
        )


def sanitize_startup(raw_path: Path, output: Path) -> None:
    """Export reviewed engine event names and numeric fields, never trace args."""
    if raw_path.stat().st_size > 32 * 1024 * 1024:
        raise RuntimeError("Diagnostic startup trace exceeds extraction bound")
    events = json.loads(raw_path.read_text())["traceEvents"]
    allowed = {
        "Collect Graphics Info",
        "CommandBufferProxyImpl::Initialize",
        "CopyOutputRequest",
        "Create GpuWatchdog",
        "Damage not visible.",
        "DirectRenderer::DrawFrame",
        "Display::DrawAndSwap",
        "DisplayScheduler::DrawAndSwap",
        "DriverEGL::InitializeClientExtensionSettings",
        "DriverEGL::InitializeExtensionSettings",
        "DriverEGL::InitializeStaticBindings",
        "DriverGL::InitializeStaticBindings",
        "GLContextEGL::MakeCurrent",
        "Gpu::EstablishGpuChannelSync",
        "GpuChannel::CreateCommandBuffer",
        "GpuChannelHost::CreateViewCommandBuffer",
        "GpuHostImpl::ConnectFrameSinkManager",
        "GpuHostImpl::DidInitialize",
        "GpuHostImpl::EstablishGpuChannel",
        "GpuHostImpl::OnChannelEstablished",
        "GpuMain",
        "ImplementationBase::Initialize",
        "Initialize sandbox",
        "LaunchGpuProcess",
        "LayerTreeHost::InitializeForReal",
        "LayerTreeHost::SetLayerTreeFrameSink",
        "LayerTreeHost::WaitForCommitCompletion",
        "LayerTreeHostImpl::ActivateSyncTree",
        "LayerTreeHostImpl::BeginCommit",
        "LayerTreeHostImpl::CommitComplete",
        "LayerTreeHostImpl::DidNotProduceFrame",
        "LayerTreeHostImpl::InitializeFrameSink",
        "LayerTreeHostImpl::PrepareToDraw",
        "LayerTreeHostImpl::SetVisible",
        "PipelineReporter",
        "ProxyMain::BeginMainFrame",
        "ProxyMain::RequestNewLayerTreeFrameSink",
        "RasterBufferStub::Initialize",
        "RasterDecoderImpl::Initialize",
        "RasterImplementation::Initialize",
        "RenderThreadImpl::EstablishGpuChannel",
        "RenderThreadImpl::EstablishGpuChannel callback",
        "RenderThreadImpl::EstablishGpuChannelSync",
        "Scheduler::BeginFrame",
        "Scheduler::BeginImplFrame",
        "Scheduler::OnBeginImplFrameDeadline",
        "SkiaOutputSurfaceImpl::Reshape",
        "SkiaOutputSurfaceImplOnGpu::Initialize",
        "Surface deadline passed",
        "SurfaceSynchronizationEvent",
        "Warm up rand",
        "WidgetBase::DidCommitAndDrawCompositorFrame",
        "WidgetBase::WillBeginMainFrame",
        "eglInitializeFn display",
        "gl::GLDisplayEGL::InitializeCommon",
        "gl::GLDisplayEGL::InitializeDisplay",
        "gl::init::CreateGLContext",
        "gl::init::CreateOffscreenGLSurface",
        "gl::init::InitializeGLOneOffPlatformHelper",
        "gl::init::InitializeNoExtensionsOneOff",
        "gl::init::InitializeStaticGLBindingsOneOff",
        "gl_display::GetPlatformANGLEDisplay",
        "gl_display_initializer::GetEGLInitDisplays",
        "gpu::GpuInit::InitializeAndStartSandbox",
        "gpu_info_collector::CollectBasicGraphicsInfo",
        "gpu_info_collector::CollectGpuExtraInfo",
        "gpu_info_collector::CollectGraphicsInfo",
        "gpu_info_collector::CollectGraphicsInfoGL",
        "gpu_info_collector::InitializeGLContext",
        "gpu_init::InitializeDawnProcs",
        "gpu_main::EnsureSandboxInitialized",
        "gpu_main::InitializeSkia",
        "gpu_main::PreSandboxStartup",
        "gpu_util::ComputeGpuFeatureInfo",
        "ui::OzonePlatform::InitializeForGPU",
    }
    selected = []
    for event in events:
        if event.get("name") not in allowed:
            continue
        if not {"gpu", "viz", "cc"}.intersection(event.get("cat", "").split(",")):
            continue
        phase = event.get("ph")
        if phase not in {"B", "E", "X", "I", "b", "e", "n", "s", "t", "f"}:
            continue
        record = {"name": event["name"], "ph": phase}
        for field in ("ts", "dur", "pid", "tid"):
            value = event.get(field)
            if value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise RuntimeError("Invalid diagnostic numeric trace field")
            record[field] = value
        args = event.get("args", {})
        success = args.get("success")
        if type(success) is bool:
            record["success"] = success
        selected.append(record)
    if not selected:
        raise RuntimeError("Diagnostic startup trace has no reviewed events")
    output.write_text(
        json.dumps(
            {
                "diagnostic_only": True,
                "source_events": len(events),
                "selected_events": len(selected),
                "events": selected,
            }
        )
    )


def main() -> None:
    if sys.argv[1] == "--sample-gpu":
        sample_gpu(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    if sys.argv[1] == "--sanitize-startup":
        sanitize_startup(Path(sys.argv[2]), Path(sys.argv[3]))
        return
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
                    "experiment_sdk_legacy_surface": (
                        os.environ.get("PLAYWRIGHT_LEGACY_SCREENSHOT") == "1"
                    ),
                    "experiment_startup_trace": bool(
                        os.environ.get("AZ_CAPTURE_STARTUP_TRACE")
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
    if os.environ.get("AZ_CAPTURE_STARTUP_TRACE"):
        old = """        const chromeArguments = this._innerDefaultArgs(options);
        chromeArguments.push(`--user-data-dir=${userDataDir}`);"""
        new = """        const chromeArguments = this._innerDefaultArgs(options);
        // Diagnostic scope: the first synthetic field test, not the sandbox probe.
        if (isPersistent && process.env.AZ_CAPTURE_STARTUP_TRACE &&
            process.env.PYTEST_CURRENT_TEST?.startsWith(
              "tests/browser_field_viewer_test.py::"+
              "test_private_field_read_and_single_replace[<input>-text-Changed value]"
            )) {
          try {
            require("node:fs").writeFileSync(
              process.env.AZ_CAPTURE_STARTUP_TRACE+".selected", "1");
          } catch {}
          chromeArguments.push(
            "--trace-startup=viz,cc,gpu,benchmark,disabled-by-default-viz.debug,disabled-by-default-gpu.service",
            "--trace-startup-duration=15",
            "--trace-startup-format=json",
            "--trace-startup-file="+process.env.AZ_CAPTURE_STARTUP_TRACE
          );
        }
        chromeArguments.push(`--user-data-dir=${userDataDir}`);"""
        chromium = source.index("Chromium = class extends BrowserType")
        method_end = source.index("      _innerDefaultArgs(options) {", chromium)
        scoped = source[chromium:method_end]
        if scoped.count(old) != 1:
            raise RuntimeError("Pinned Chromium startup-trace anchor mismatch")
        source = source[:chromium] + scoped.replace(old, new) + source[method_end:]
    helper = """
let azCaptureOrdinal = 0;
const azCaptureOrdinals = new WeakMap();
function azCaptureTrace(stage, elapsed, outcome, ordinal, requestId) {
  if (!process.env.AZ_CAPTURE_TRACE) return;
  try {
    require('node:fs').appendFileSync(process.env.AZ_CAPTURE_TRACE, JSON.stringify({
      diagnostic_only:true, pid:process.pid, stage,
      monotonic_ms:Number(process.hrtime.bigint())/1000000,
      elapsed_ms:elapsed === undefined ? null : elapsed,
      outcome:outcome === undefined ? null : outcome,
      capture_ordinal:ordinal === undefined ? null : ordinal,
      request_id:requestId === undefined ? null : requestId
    })+'\\n');
  } catch {
    // Missing diagnostic evidence invalidates the experiment, not the SDK call.
  }
}
function azCaptureGpuFacts(info) {
  try {
    const gpu = info.gpu || {};
    const device = gpu.devices?.[0] || {};
    const renderer = gpu.auxAttributes?.glRenderer || "";
    const implementation = gpu.auxAttributes?.displayType || "";
    const allowed = new Set(["ANGLE_OPENGL", "ANGLE_VULKAN", "ANGLE_SWIFTSHADER",
      "ANGLE_OPENGLES", "ANGLE_D3D11", "ANGLE_METAL"]);
    const version = device.driverVersion || "";
    require("node:fs").appendFileSync(process.env.AZ_CAPTURE_TRACE,
      JSON.stringify({
        diagnostic_only:true, stage:"gpu_facts_after_capture", pid:process.pid,
        monotonic_ms:Number(process.hrtime.bigint())/1000000,
        renderer:renderer.toLowerCase().includes("llvmpipe") ? "llvmpipe" :
          renderer.toLowerCase().includes("swiftshader") ? "swiftshader" : "other",
        implementation:allowed.has(implementation) ? implementation : "other",
        driver_version:/^[0-9.]{1,40}$/.test(version) ? version : "unknown"
      })+"\\n");
  } catch {
    // No raw response or error text belongs in the diagnostic artifact.
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
            "        const azOrdinal = ++azCaptureOrdinal;\n"
            "        azCaptureOrdinals.set(progress2, azOrdinal);\n"
            '        azCaptureTrace("sdk_screenshot_enter", undefined,\n'
            "          undefined, azOrdinal);\n"
            '        progress2.signal.addEventListener("abort", () => {\n'
            '          azCaptureTrace("sdk_capture_abort", undefined,\n'
            "            progress2.signal.reason instanceof TimeoutError ?\n"
            '              "timeout" : "aborted", azOrdinal);\n'
            "        }, {once:true});"
        ),
        '          progress2.log("taking page screenshot");': (
            '          progress2.log("taking page screenshot");\n'
            '          azCaptureTrace("sdk_queue_enter", undefined,\n'
            "            undefined, azCaptureOrdinals.get(progress2));"
        ),
        '            progress2.log("waiting for fonts to load...");': (
            '            azCaptureTrace("sdk_font_wait_start", undefined,\n'
            "              undefined, azCaptureOrdinals.get(progress2));\n"
            '            progress2.log("waiting for fonts to load...");'
        ),
        '            progress2.log("fonts loaded");': (
            '            azCaptureTrace("sdk_font_wait_end", undefined,\n'
            "              undefined, azCaptureOrdinals.get(progress2));\n"
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
        // Snapshot the latest entry, not a concurrent-capture ownership claim.
        const ordinal = azCaptureOrdinal;
        const id = this._connection._rawSend(this._sessionId, method2, params2);
        if (traced) azCaptureTrace(method2+"_send", undefined,
          undefined, ordinal, id);
        let outcome = "rejected";
        try {
          const result = await new Promise((resolve, reject) => {
            this._callbacks.set(id, { resolve, reject,
              error: new ProtocolError("error", method2) });
          });
          outcome = "resolved";
          return result;
        } finally {
          if (traced) azCaptureTrace(method2+"_complete",
            Number(process.hrtime.bigint())/1000000-started,
            outcome, ordinal, id);
          if (method2 === "Page.captureScreenshot" && ordinal === 1 &&
              process.env.AZ_CAPTURE_STARTUP_TRACE &&
              process.env.PYTEST_CURRENT_TEST?.startsWith(
                "tests/browser_field_viewer_test.py::"+
                "test_private_field_read_and_single_replace[<input>-text-Changed value]"
              )) {
            // Observe graphics facts after settlement; never initialize it early.
            void this._connection.rootSession.send("SystemInfo.getInfo")
              .then(azCaptureGpuFacts)
              .catch(() => azCaptureTrace("gpu_facts_unavailable"));
          }
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
        old = "            outcome, ordinal, id);"
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
