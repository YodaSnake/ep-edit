from __future__ import annotations

import io
from pathlib import Path

import pytest

import ep_edit.cli as cli_module
from ep_edit.cli import main
from ep_edit.specification import parse_edit_specification


pytestmark = pytest.mark.unit


VALID_SPEC = """

FILE: example.py
<<<<<<< SEARCH
value = 1
=======
value = 2
>>>>>>> REPLACE
"""


def _write(
    root: Path,
    target: str,
    raw: bytes,
) -> Path:
    file_path = (
        root
        / target
    )
    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    file_path.write_bytes(
        raw
    )
    return file_path


def _write_spec(
    root: Path,
    text: str = VALID_SPEC,
) -> Path:
    path = (
        root
        / "edits.txt"
    )
    path.write_text(
        text,
        encoding="utf-8",
    )
    return path


def test_missing_file_input_does_not_expose_absolute_path(
    tmp_path: Path,
) -> None:
    missing = (
        tmp_path
        / "private-parent-marker"
        / "missing-specification.txt"
    )
    error = io.StringIO()

    result = main(
        [
            "check",
            "--root",
            str(tmp_path),
            str(missing),
        ],
        stdout=io.StringIO(),
        stderr=error,
    )

    assert result == 1
    assert "INPUT_PARSE_ERROR" in error.getvalue()
    assert "missing-specification.txt" in error.getvalue()
    assert str(tmp_path) not in error.getvalue()
    assert "private-parent-marker" not in error.getvalue()


def test_check_file_input_validates_without_write(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path
    )
    output = io.StringIO()
    error = io.StringIO()

    result = main(
        [
            "check",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=output,
        stderr=error,
    )

    assert result == 0
    assert (
        "CHECK OK:"
        in output.getvalue()
    )
    assert (
        target.read_bytes()
        == b"value = 1\n"
    )
    assert error.getvalue() == ""


def test_preview_file_input_renders_without_write(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path
    )
    output = io.StringIO()

    result = main(
        [
            "preview",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=output,
        stderr=io.StringIO(),
    )

    assert result == 0
    assert (
        "Root: ."
        in output.getvalue()
    )
    assert (
        str(tmp_path)
        not in output.getvalue()
    )
    assert (
        "Target: example.py"
        in output.getvalue()
    )
    assert (
        "-value = 1"
        in output.getvalue()
    )
    assert (
        "+value = 2"
        in output.getvalue()
    )
    assert (
        target.read_bytes()
        == b"value = 1\n"
    )


def test_apply_file_input_yes_publishes(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path
    )
    output = io.StringIO()

    result = main(
        [
            "apply",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=output,
        stderr=io.StringIO(),
        approval_reader=lambda _: "y",
    )

    assert result == 0
    assert (
        target.read_bytes()
        == b"value = 2\n"
    )
    assert (
        "APPLIED: 1 target(s)."
        in output.getvalue()
    )


def test_apply_yes_is_case_insensitive(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path
    )

    result = main(
        [
            "apply",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        approval_reader=lambda _: "YES",
    )

    assert result == 0
    assert (
        target.read_bytes()
        == b"value = 2\n"
    )


def test_apply_default_no_does_not_write(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path
    )
    output = io.StringIO()

    result = main(
        [
            "apply",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=output,
        stderr=io.StringIO(),
        approval_reader=lambda _: "",
    )

    assert result == 0
    assert (
        target.read_bytes()
        == b"value = 1\n"
    )
    assert (
        "NOT APPLIED"
        in output.getvalue()
    )


def test_apply_eof_does_not_write(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path
    )

    def eof_reader(
        _: str,
    ) -> str:
        raise EOFError

    result = main(
        [
            "apply",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        approval_reader=eof_reader,
    )

    assert result == 0
    assert (
        target.read_bytes()
        == b"value = 1\n"
    )


def test_apply_keyboard_interrupt_does_not_write(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path
    )

    def interrupted_reader(
        _: str,
    ) -> str:
        raise KeyboardInterrupt

    result = main(
        [
            "apply",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        approval_reader=interrupted_reader,
    )

    assert result == 0
    assert (
        target.read_bytes()
        == b"value = 1\n"
    )


def test_file_backed_specification_change_during_prompt_is_stale(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path
    )
    error = io.StringIO()

    def change_spec_then_approve(
        _: str,
    ) -> str:
        specification.write_text(
            VALID_SPEC.replace(
                "value = 2",
                "value = 3",
            ),
            encoding="utf-8",
        )
        return "y"

    result = main(
        [
            "apply",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=io.StringIO(),
        stderr=error,
        approval_reader=change_spec_then_approve,
    )

    assert result == 1
    assert (
        "STALE_SPECIFICATION"
        in error.getvalue()
    )
    assert (
        target.read_bytes()
        == b"value = 1\n"
    )


def test_target_change_during_prompt_is_stale(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path
    )
    error = io.StringIO()

    def change_target_then_approve(
        _: str,
    ) -> str:
        target.write_bytes(
            b"value = 9\n"
        )
        return "yes"

    result = main(
        [
            "apply",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=io.StringIO(),
        stderr=error,
        approval_reader=change_target_then_approve,
    )

    assert result == 1
    assert (
        "STALE_PREVIEW"
        in error.getvalue()
    )
    assert (
        target.read_bytes()
        == b"value = 9\n"
    )


def test_stdin_apply_uses_immutable_received_specification(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )

    result = main(
        [
            "apply",
            "--root",
            str(tmp_path),
            "-",
        ],
        stdin_binary=io.BytesIO(
            VALID_SPEC.encode(
                "utf-8"
            )
        ),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        approval_reader=lambda _: "yes",
    )

    assert result == 0
    assert (
        target.read_bytes()
        == b"value = 2\n"
    )


def test_stdin_preview_works_without_target_write(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    output = io.StringIO()

    result = main(
        [
            "preview",
            "--root",
            str(tmp_path),
            "-",
        ],
        stdin_binary=io.BytesIO(
            VALID_SPEC.encode(
                "utf-8"
            )
        ),
        stdout=output,
        stderr=io.StringIO(),
    )

    assert result == 0
    assert (
        "Target: example.py"
        in output.getvalue()
    )
    assert (
        target.read_bytes()
        == b"value = 1\n"
    )


def test_clipboard_preview_uses_complete_specification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    output = io.StringIO()

    monkeypatch.setattr(
        cli_module,
        "_read_clipboard_bytes",
        lambda: VALID_SPEC.encode(
            "utf-8"
        ),
    )

    result = main(
        [
            "preview",
            "--root",
            str(tmp_path),
            "--clipboard",
        ],
        stdout=output,
        stderr=io.StringIO(),
    )

    assert result == 0
    assert (
        "Target: example.py"
        in output.getvalue()
    )
    assert (
        target.read_bytes()
        == b"value = 1\n"
    )


def test_clipboard_unavailable_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = io.StringIO()

    monkeypatch.setattr(
        cli_module.shutil,
        "which",
        lambda _: None,
    )

    result = main(
        [
            "preview",
            "--root",
            str(tmp_path),
            "--clipboard",
        ],
        stdout=io.StringIO(),
        stderr=error,
    )

    assert result == 1
    assert (
        "INPUT_PARSE_ERROR"
        in error.getvalue()
    )


def test_explicit_root_is_not_silently_widened(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    inner = (
        tmp_path
        / "inner"
    )
    inner.mkdir()
    specification = _write_spec(
        tmp_path
    )
    error = io.StringIO()

    result = main(
        [
            "check",
            "--root",
            str(inner),
            str(specification),
        ],
        stdout=io.StringIO(),
        stderr=error,
    )

    assert result == 1
    assert (
        "TARGET_NOT_FOUND"
        in error.getvalue()
    )


def test_invalid_candidate_check_fails_validation(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path,
        """

FILE: example.py
<<<<<<< SEARCH
value = 1
=======
def broken(:
>>>>>>> REPLACE
""",
    )
    error = io.StringIO()

    result = main(
        [
            "check",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=io.StringIO(),
        stderr=error,
    )

    assert result == 1
    assert (
        "VALIDATION_FAILED"
        in error.getvalue()
    )


def test_revise_updates_draft_only(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _write_spec(
        tmp_path
    )
    base_ref = (
        parse_edit_specification(
            VALID_SPEC
        )
        .edits[0]
        .edit_id
    )
    revision = (
        tmp_path
        / "revision.txt"
    )
    revision.write_text(
        f"""

REVISE_EDIT: {base_ref}

<<<<<<< EDIT
FILE: example.py
<<<<<<< SEARCH
value = 1
=======
value = 3
>>>>>>> REPLACE
>>>>>>> EDIT
""",
        encoding="utf-8",
    )
    output = io.StringIO()

    result = main(
        [
            "revise",
            str(specification),
            str(revision),
        ],
        stdout=output,
        stderr=io.StringIO(),
    )

    assert result == 0
    assert (
        "value = 3"
        in specification.read_text(
            encoding="utf-8"
        )
    )
    assert (
        target.read_bytes()
        == b"value = 1\n"
    )
    assert (
        "REVISED DRAFT: edits.txt"
        in output.getvalue()
    )
    assert (
        str(tmp_path)
        not in output.getvalue()
    )
    assert (
        f"Revised edits: {base_ref}"
        in output.getvalue()
    )
    assert (
        "Specification fingerprint:"
        in output.getvalue()
    )


def test_clipboard_and_path_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    specification = _write_spec(
        tmp_path
    )
    error = io.StringIO()

    result = main(
        [
            "preview",
            "--root",
            str(tmp_path),
            "--clipboard",
            str(specification),
        ],
        stdout=io.StringIO(),
        stderr=error,
    )

    assert result == 1
    assert (
        "INPUT_PARSE_ERROR"
        in error.getvalue()
    )


def test_invalid_utf8_input_fails_closed(
    tmp_path: Path,
) -> None:
    specification = (
        tmp_path
        / "invalid.txt"
    )
    specification.write_bytes(
        b"\xff\xfe\x00"
    )
    error = io.StringIO()

    result = main(
        [
            "check",
            "--root",
            str(tmp_path),
            str(specification),
        ],
        stdout=io.StringIO(),
        stderr=error,
    )

    assert result == 1
    assert (
        "UNSUPPORTED_ENCODING"
        in error.getvalue()
    )
