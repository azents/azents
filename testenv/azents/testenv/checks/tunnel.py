"""External tunnel preflight checks for Tailscale Funnel.

D3 decision (Discussion #2456): testenv live webhook URLs are exposed through
Tailscale Funnel instead of a separate public ingress. This check verifies that
the Funnel is active and that `.env` contains a matching
``TESTENV_AZENTS_FUNNEL_URL`` value.
"""

import subprocess
import urllib.error
import urllib.request

from .base import Check, CheckResult, RunContext, Status


class TailscaleFunnelHealthy(Check):
    """Verify Funnel status and reachability of the configured URL.

    Checks:
    1. ``tailscale`` exists in PATH.
    2. ``tailscale funnel status`` reports an active Funnel.
    3. The status output mentions ``TESTENV_AZENTS_FUNNEL_URL`` from `.env`.
    4. The configured URL accepts a HEAD request.
    """

    def __init__(self) -> None:
        super().__init__(
            id="tailscale-funnel-healthy",
            name="Tailscale Funnel healthy",
            category="infra",
        )

    def run(self, context: RunContext) -> CheckResult:
        # Step 1: tailscale CLI exists
        try:
            version = subprocess.run(
                ["tailscale", "version"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return CheckResult(
                status=Status.FAIL,
                message="tailscale CLI not found",
                fix_hint="Install tailscale: curl -fsSL https://tailscale.com/install.sh | sh",
            )
        if version.returncode != 0:
            return CheckResult(
                status=Status.FAIL,
                message=f"tailscale version exit={version.returncode}",
                fix_hint="Check tailscaled service: sudo systemctl status tailscaled",
            )

        # Step 2: funnel status
        funnel = subprocess.run(
            ["tailscale", "funnel", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        if funnel.returncode != 0 or not funnel.stdout.strip():
            return CheckResult(
                status=Status.FAIL,
                message="tailscale funnel inactive",
                fix_hint="Activate funnel: sudo tailscale funnel --bg 8010",
            )

        # Step 3: ensure the env URL appears in the Funnel status output.
        expected_url = context.env.get("TESTENV_AZENTS_FUNNEL_URL", "").rstrip("/")
        if not expected_url:
            return CheckResult(
                status=Status.FAIL,
                message="TESTENV_AZENTS_FUNNEL_URL not set in .env",
                fix_hint="Add TESTENV_AZENTS_FUNNEL_URL=<funnel url> to testenv/azents/.env",
            )
        if expected_url not in funnel.stdout:
            return CheckResult(
                status=Status.FAIL,
                message=f"funnel status does not mention {expected_url}",
                fix_hint=(
                    "Re-activate funnel: "
                    "sudo tailscale funnel --https=443 off && "
                    "sudo tailscale funnel --bg 8010"
                ),
            )

        # Step 4: URL reachability (HEAD)
        try:
            req = urllib.request.Request(expected_url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                # The 8010 devserver may return 502/503 while booting. Any HTTP response
                # means the Funnel itself is reachable; devserver readiness is checked elsewhere.
                _ = resp.status
        except urllib.error.HTTPError:
            # 5xx/4xx still proves Funnel reachability; devserver state is separate.
            pass
        except (urllib.error.URLError, OSError) as exc:
            return CheckResult(
                status=Status.FAIL,
                message=f"{expected_url} unreachable ({exc})",
                fix_hint="Verify Tailscale funnel and DNS resolution",
            )

        return CheckResult(status=Status.PASS, message=expected_url)
