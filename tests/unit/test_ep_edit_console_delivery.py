from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

from ep_edit.cli import main


pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project_metadata() -> dict[str, object]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_pyproject_declares_standalone_ep_edit_delivery() -> None:
    metadata = _project_metadata()

    assert metadata["project"]["name"] == "ep-edit"
    assert metadata["project"]["version"] == "0.1.0"
    assert metadata["project"]["requires-python"] == ">=3.12,<3.13"
    assert metadata["project"]["dependencies"] == []
    assert metadata["project"]["scripts"] == {
        "ep-edit": "ep_edit.cli:main",
    }
    assert metadata["build-system"]["build-backend"] == "uv_build"


def test_console_script_target_resolves_to_public_cli_main() -> None:
    metadata = _project_metadata()
    target = metadata["project"]["scripts"]["ep-edit"]

    assert target == f"{main.__module__}:{main.__name__}"
