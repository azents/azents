"""Mitmdump script entrypoint for the Azents policy addon."""

from azents_runtime_proxy.addon import AzentsProxyAddon
from azents_runtime_proxy.main import load_environment_policy, readiness_port

addons = [
    AzentsProxyAddon(
        load_environment_policy(),
        readiness_port=readiness_port(),
    )
]
