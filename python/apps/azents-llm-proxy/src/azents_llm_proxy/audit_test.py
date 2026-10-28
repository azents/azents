"""Installed core inventory, not a mocked feature/license-gate assertion."""

from azents_llm_proxy.audit import verify_core_composition


def test_installed_proxy_core_has_audited_pin_and_notice_without_enterprise() -> None:
    composition = verify_core_composition()
    assert composition.version == "1.109.0"
    assert composition.file_count > 0
    assert composition.license_files
