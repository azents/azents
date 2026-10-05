"""Native generator probe for alias/model-map surfaces absent from current APIs."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


class TestTemplateCompatibility(unittest.TestCase):
    def test_native_alias_nested_maps_defaults_and_required_fields(self) -> None:
        """Generate a disposable client with the same pinned tool and shared template."""
        tests = Path(__file__).resolve().parent
        template = tests.parent / "python"
        with tempfile.TemporaryDirectory(prefix="python-template-probe-") as directory:
            generated = Path(directory)
            subprocess.run(
                [
                    "uvx",
                    "openapi-generator-cli[jdk4py]@7.17.0",
                    "generate",
                    "-g",
                    "python",
                    "-i",
                    str(tests / "fixtures" / "compatibility.yaml"),
                    "-o",
                    str(generated),
                    "-t",
                    str(template),
                    "--additional-properties",
                    (
                        "packageName=templateprobe,generateSourceCodeOnly=true,"
                        "disallowAdditionalPropertiesIfNotPresent=false"
                    ),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            probe = textwrap.dedent(
                """\
                import json
                from pydantic import ValidationError
                from templateprobe.models.patch import Patch
                from templateprobe.models.child import Child
                from templateprobe.api_client import ApiClient

                required = {"expected-version": 0}
                patch = Patch.from_dict(required)
                assert patch.model_fields_set == {"expected_version"}
                assert patch.retry_count == 3
                assert patch.to_dict() == {"expected-version": 0, "retry-count": 3}
                explicit = Patch.from_dict({**required, "display-label": None})
                assert explicit.to_dict()["display-label"] is None
                assert "display_label" in explicit.model_fields_set
                try:
                    Patch.from_dict({})
                except ValidationError:
                    pass
                else:
                    raise AssertionError("required alias was silently defaulted")
                child = {"required-name": "", "extension": {"value": False}}
                payload = {**required, "child-map": {"first": child}, "children": [child]}
                nested = Patch.from_json(json.dumps(payload))
                assert isinstance(nested.child_map["first"], Child)
                assert isinstance(nested.children[0], Child)
                assert nested.child_map["first"].model_fields_set == {"required_name"}
                assert nested.children[0].additional_properties == {"extension": {"value": False}}
                assert "optional-note" not in nested.to_dict()["child-map"]["first"]
                assert ApiClient().sanitize_for_serialization(nested) == nested.to_dict()
                unknown = Patch.from_dict({**required, "ignored-extension": 1})
                assert unknown.model_fields_set == {"expected_version"}
                assert "ignored-extension" not in unknown.to_dict()
                """
            )
            environment = {**os.environ, "PYTHONPATH": str(generated)}
            subprocess.run(
                [sys.executable, "-c", probe],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )


if __name__ == "__main__":
    unittest.main()
