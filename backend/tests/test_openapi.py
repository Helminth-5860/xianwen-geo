from pathlib import Path

from openapi_spec_validator import validate
from yaml import safe_load


def test_openapi_31_document_is_valid():
    spec_path = Path(__file__).resolve().parents[2] / "openapi" / "openapi-v1.yaml"
    specification = safe_load(spec_path.read_text(encoding="utf-8"))

    assert specification["openapi"] == "3.1.0"
    validate(specification)
