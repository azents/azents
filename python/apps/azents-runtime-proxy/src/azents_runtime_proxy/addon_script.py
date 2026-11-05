"""Mitmdump script entrypoint for the Azents policy addon."""

from azents_runtime_proxy.addon import AzentsProxyAddon, configure_decision_logging
from azents_runtime_proxy.main import load_environment_policy, readiness_port

configure_decision_logging()

addons = [
    AzentsProxyAddon(
        load_environment_policy(),
        readiness_port=readiness_port(),
    )
]
