from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ep_edit.cli import main
from ep_edit.errors import (
    DeterministicEditError,
    EditPreflightError,
)
from ep_edit.planner import (
    plan_edit_text,
)


pytestmark = pytest.mark.unit

_SEARCH_OPEN = "<" * 7 + " SEARCH"
_REPLACE_SEPARATOR = "=" * 7
_REPLACE_CLOSE = ">" * 7 + " REPLACE"


def test_all_search_failures_on_target_are_collected(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "alpha()\nsame()\nsame()\n",
        encoding="utf-8",
    )

    specification = f"""EDIT_SPEC_VERSION: 2

FILE: example.py
LABEL: first zero

{_SEARCH_OPEN}
missing_one()
{_REPLACE_SEPARATOR}
replacement_one()
{_REPLACE_CLOSE}

FILE: example.py
LABEL: second zero

{_SEARCH_OPEN}
missing_two()
{_REPLACE_SEPARATOR}
replacement_two()
{_REPLACE_CLOSE}

FILE: example.py
LABEL: multiple

{_SEARCH_OPEN}
same()
{_REPLACE_SEPARATOR}
replacement_three()
{_REPLACE_CLOSE}
"""

    with pytest.raises(
        EditPreflightError
    ) as raised:
        plan_edit_text(
            tmp_path,
            specification,
        )

    error = raised.value

    assert error.code == (
        "EDIT_PREFLIGHT_FAILED"
    )
    assert len(
        error.diagnostics
    ) == 3
    assert {
        diagnostic.code
        for diagnostic in error.diagnostics
    } == {
        "SEARCH_ZERO_MATCH",
        "SEARCH_MULTIPLE_MATCH",
    }
    assert {
        diagnostic.label
        for diagnostic in error.diagnostics
    } == {
        "first zero",
        "second zero",
        "multiple",
    }

    assert target.read_text(
        encoding="utf-8"
    ) == (
        "alpha()\nsame()\nsame()\n"
    )


def test_failure_on_one_target_does_not_hide_later_target(
    tmp_path: Path,
) -> None:
    first = tmp_path / "a.py"
    first.write_text(
        "actual()\n",
        encoding="utf-8",
    )

    specification = f"""EDIT_SPEC_VERSION: 2

FILE: a.py
LABEL: zero match

{_SEARCH_OPEN}
missing()
{_REPLACE_SEPARATOR}
replacement()
{_REPLACE_CLOSE}

FILE: z_missing.py
LABEL: missing target

{_SEARCH_OPEN}
anything()
{_REPLACE_SEPARATOR}
replacement()
{_REPLACE_CLOSE}
"""

    with pytest.raises(
        EditPreflightError
    ) as raised:
        plan_edit_text(
            tmp_path,
            specification,
        )

    diagnostics = (
        raised.value.diagnostics
    )

    assert len(diagnostics) == 2
    assert {
        diagnostic.code
        for diagnostic in diagnostics
    } == {
        "SEARCH_ZERO_MATCH",
        "TARGET_NOT_FOUND",
    }
    assert {
        diagnostic.target
        for diagnostic in diagnostics
    } == {
        "a.py",
        "z_missing.py",
    }


def test_single_preflight_failure_preserves_error_code(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "actual()\n",
        encoding="utf-8",
    )

    with pytest.raises(
        EditPreflightError
    ) as raised:
        plan_edit_text(
            tmp_path,
            f"""EDIT_SPEC_VERSION: 2

FILE: example.py
LABEL: single

{_SEARCH_OPEN}
missing()
{_REPLACE_SEPARATOR}
replacement()
{_REPLACE_CLOSE}
""",
        )

    assert (
        raised.value.code
        == "SEARCH_ZERO_MATCH"
    )
    assert len(
        raised.value.diagnostics
    ) == 1


def test_parse_failure_remains_fail_fast(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        DeterministicEditError
    ) as raised:
        plan_edit_text(
            tmp_path,
            f"""EDIT_SPEC_VERSION: 2

THIS IS NOT A FILE BLOCK
""",
        )

    assert not isinstance(
        raised.value,
        EditPreflightError,
    )
    assert (
        raised.value.code
        == "INPUT_PARSE_ERROR"
    )


def test_cli_check_renders_all_preflight_failures(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "actual()\n",
        encoding="utf-8",
    )

    specification_path = (
        tmp_path / "edits.txt"
    )
    specification_path.write_text(
        f"""EDIT_SPEC_VERSION: 2

FILE: example.py
LABEL: first problem

{_SEARCH_OPEN}
missing_one()
{_REPLACE_SEPARATOR}
replacement_one()
{_REPLACE_CLOSE}

FILE: example.py
LABEL: second problem

{_SEARCH_OPEN}
missing_two()
{_REPLACE_SEPARATOR}
replacement_two()
{_REPLACE_CLOSE}
""",
        encoding="utf-8",
    )

    stdout = StringIO()
    stderr = StringIO()

    result = main(
        [
            "check",
            "--root",
            str(tmp_path),
            str(specification_path),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""

    rendered = stderr.getvalue()

    assert (
        "ERROR EDIT_PREFLIGHT_FAILED: "
        "2 edit preflight error(s)"
        in rendered
    )
    assert (
        "[SEARCH_ZERO_MATCH]"
        in rendered
    )
    assert "Label: first problem" in rendered
    assert "Label: second problem" in rendered

    assert target.read_text(
        encoding="utf-8"
    ) == "actual()\n"


def test_cli_apply_preflight_failure_never_requests_approval(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "actual()\n",
        encoding="utf-8",
    )

    specification_path = (
        tmp_path / "edits.txt"
    )
    specification_path.write_text(
        f"""EDIT_SPEC_VERSION: 2

FILE: example.py
LABEL: cannot apply

{_SEARCH_OPEN}
missing()
{_REPLACE_SEPARATOR}
replacement()
{_REPLACE_CLOSE}
""",
        encoding="utf-8",
    )

    def fail_if_called(
        _prompt: str,
    ) -> str:
        raise AssertionError(
            "approval must not be requested"
        )

    stdout = StringIO()
    stderr = StringIO()

    result = main(
        [
            "apply",
            "--root",
            str(tmp_path),
            str(specification_path),
        ],
        stdout=stdout,
        stderr=stderr,
        approval_reader=fail_if_called,
    )

    assert result == 1
    assert (
        "ERROR SEARCH_ZERO_MATCH:"
        in stderr.getvalue()
    )
    assert target.read_text(
        encoding="utf-8"
    ) == "actual()\n"
