"""Installed artifact composition checks, without changing license gates."""

import importlib.metadata
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath

import litellm.proxy.proxy_server as proxy
from pydantic import BaseModel


class VcsProvenance(BaseModel):
    vcs: str
    commit_id: str


class SourceProvenance(BaseModel):
    url: str
    vcs_info: VcsProvenance


@dataclass(frozen=True)
class CoreComposition:
    version: str
    file_count: int
    license_files: tuple[str, ...]


def verify_core_composition() -> CoreComposition:
    """Inspect actual installed files; this is not third-party legal certification."""
    if (
        importlib.util.find_spec("litellm_enterprise") is not None
        or importlib.util.find_spec("enterprise") is not None
    ):
        raise RuntimeError("Enterprise modules are not part of the Proxy artifact.")
    if proxy.premium_user or proxy.enterprise_proxy_config is not None:
        raise RuntimeError("Unexpected Enterprise configuration in the Proxy artifact.")
    distribution = importlib.metadata.distribution("litellm")
    if distribution.version != "1.109.0":
        raise RuntimeError("The installed Proxy version differs from the audited pin.")
    files = distribution.files
    if files is None:
        raise RuntimeError("Installed Proxy file inventory is unavailable.")
    for file in files:
        parts = PurePosixPath(str(file)).parts
        if "enterprise" in parts or "litellm_enterprise" in parts:
            raise RuntimeError("Enterprise source is present in the Proxy package.")
    licenses = tuple(str(file) for file in files if file.name == "LICENSE")
    if not licenses or not any(
        "MIT License" in distribution.locate_file(file).read_text() for file in licenses
    ):
        raise RuntimeError("The Proxy MIT license notice is missing.")
    return CoreComposition(
        version=distribution.version, file_count=len(files), license_files=licenses
    )


def main() -> None:
    """Emit nonsecret provenance for the exact installed runtime artifact."""
    composition = verify_core_composition()
    distribution = importlib.metadata.distribution("litellm")
    direct = distribution.read_text("direct_url.json")
    if direct is None:
        raise RuntimeError("Pinned Proxy source provenance is unavailable.")
    provenance = SourceProvenance.model_validate_json(direct)
    if (
        provenance.url != "https://github.com/BerriAI/litellm"
        or provenance.vcs_info.vcs != "git"
        or provenance.vcs_info.commit_id != "c7c895db456eda349a7be9661b4b21f578f9b589"
    ):
        raise RuntimeError("Installed Proxy source differs from the audited revision.")
    sys.stdout.write(
        json.dumps(
            {
                "litellm_version": composition.version,
                "litellm_source": provenance.model_dump(),
                "litellm_file_count": composition.file_count,
                "litellm_license_files": composition.license_files,
                "distributions": sorted(
                    (
                        {"name": item.metadata["Name"], "version": item.version}
                        for item in importlib.metadata.distributions()
                    ),
                    key=lambda item: item["name"].lower(),
                ),
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
