from __future__ import annotations

import codecs
import hashlib
from pathlib import Path

import pytest

from ep_edit.errors import DeterministicEditError
from ep_edit.planner import (
    FileMutationOperation,
    plan_edit_text as _plan_edit_text,
)
from ep_edit.snapshot import NewlineStyle
from ep_edit.specification import (
    BomDirective,
    FinalNewlineDirective,
    NewlineDirective,
    WholeFileEdit,
    WholeFileMode,
    parse_edit_specification as _parse_edit_specification,
)


pytestmark = pytest.mark.unit


def parse_edit_specification(
    text: str,
):
    return _parse_edit_specification(
        text
    )


def plan_edit_text(
    root: Path,
    text: str,
):
    return _plan_edit_text(
        root,
        text,
    )


def _assert_error(
    expected_code: str,
    callable_,
) -> DeterministicEditError:
    with pytest.raises(
        DeterministicEditError
    ) as raised:
        callable_()

    assert raised.value.code == expected_code
    return raised.value


def _write(
    root: Path,
    target: str,
    raw: bytes,
) -> Path:
    file_path = root / target
    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    file_path.write_bytes(raw)
    return file_path


def test_parse_create_uses_documented_defaults() -> None:
    specification = parse_edit_specification(
        """FILE: src/new.py
LABEL: create-new
MODE: CREATE

<<<<<<< CONTENT
def hello():
    return "hello"
>>>>>>> CONTENT
"""
    )
    edit = specification.edits[0]

    assert isinstance(edit, WholeFileEdit)
    assert edit.mode is WholeFileMode.CREATE
    assert edit.label == "create-new"
    assert edit.edit_ref.startswith("e_")
    assert len(edit.edit_ref) == 18
    assert edit.content_lines == (
        "def hello():",
        '    return "hello"',
    )
    assert edit.newline is NewlineDirective.LF
    assert (
        edit.final_newline
        is FinalNewlineDirective.YES
    )
    assert edit.bom is BomDirective.NO


def test_parse_create_accepts_explicit_representation() -> None:
    edit = parse_edit_specification(
        """FILE: src/new.txt
LABEL: create-new
MODE: CREATE
BOM: YES
FINAL_NEWLINE: NO
NEWLINE: CRLF
<<<<<<< CONTENT
alpha
beta
>>>>>>> CONTENT
"""
    ).edits[0]

    assert isinstance(edit, WholeFileEdit)
    assert edit.newline is NewlineDirective.CRLF
    assert (
        edit.final_newline
        is FinalNewlineDirective.NO
    )
    assert edit.bom is BomDirective.YES


def test_parse_replace_file_uses_preserve_defaults() -> None:
    edit = parse_edit_specification(
        """FILE: config/example.toml
LABEL: replace-config
MODE: REPLACE_FILE
<<<<<<< CONTENT
value = 2
>>>>>>> CONTENT
"""
    ).edits[0]

    assert isinstance(edit, WholeFileEdit)
    assert edit.mode is WholeFileMode.REPLACE_FILE
    assert edit.newline is NewlineDirective.PRESERVE
    assert (
        edit.final_newline
        is FinalNewlineDirective.PRESERVE
    )
    assert edit.bom is BomDirective.PRESERVE


def test_parse_delete_has_no_content_or_representation() -> None:
    edit = parse_edit_specification(
        """FILE: src/obsolete.py
LABEL: remove-obsolete
MODE: DELETE
"""
    ).edits[0]

    assert isinstance(edit, WholeFileEdit)
    assert edit.mode is WholeFileMode.DELETE
    assert edit.content_lines is None
    assert edit.newline is None
    assert edit.final_newline is None
    assert edit.bom is None


def test_whole_file_operation_generates_edit_ref_without_label() -> None:
    edit = parse_edit_specification(
        """FILE: src/new.py
MODE: CREATE
<<<<<<< CONTENT
value = 1
>>>>>>> CONTENT
"""
    ).edits[0]

    assert isinstance(edit, WholeFileEdit)
    assert edit.label is None
    assert edit.edit_ref.startswith("e_")
    assert len(edit.edit_ref) == 18


def test_unknown_whole_file_mode_fails_closed() -> None:
    _assert_error(
        "INPUT_PARSE_ERROR",
        lambda: parse_edit_specification(
            """FILE: src/a.py
LABEL: bad-mode
MODE: OVERWRITE
<<<<<<< CONTENT
value
>>>>>>> CONTENT
"""
        ),
    )


def test_duplicate_representation_directive_fails_closed() -> None:
    _assert_error(
        "INPUT_PARSE_ERROR",
        lambda: parse_edit_specification(
            """FILE: src/a.py
LABEL: duplicate-newline
MODE: CREATE
NEWLINE: LF
NEWLINE: CRLF
<<<<<<< CONTENT
value
>>>>>>> CONTENT
"""
        ),
    )


@pytest.mark.parametrize(
    "directive",
    [
        "NEWLINE: PRESERVE",
        "FINAL_NEWLINE: PRESERVE",
        "BOM: PRESERVE",
    ],
)
def test_create_cannot_preserve_absent_representation(
    directive: str,
) -> None:
    _assert_error(
        "INPUT_PARSE_ERROR",
        lambda: parse_edit_specification(
            (
                "FILE: src/a.py\n"
                "LABEL: create-a\n"
                "MODE: CREATE\n"
                f"{directive}\n"
                "<<<<<<< CONTENT\n"
                "value\n"
                ">>>>>>> CONTENT\n"
            )
        ),
    )


@pytest.mark.parametrize(
    "unexpected",
    [
        "NEWLINE: LF",
        "<<<<<<< CONTENT\nvalue\n>>>>>>> CONTENT",
    ],
)
def test_delete_rejects_representation_or_content(
    unexpected: str,
) -> None:
    _assert_error(
        "INPUT_PARSE_ERROR",
        lambda: parse_edit_specification(
            (
                "FILE: src/a.py\n"
                "LABEL: delete-a\n"
                "MODE: DELETE\n"
                f"{unexpected}\n"
            )
        ),
    )


def test_content_rejects_nul() -> None:
    _assert_error(
        "UNSUPPORTED_ENCODING",
        lambda: parse_edit_specification(
            (
                "FILE: src/a.py\n"
                "LABEL: create-a\n"
                "MODE: CREATE\n"
                "<<<<<<< CONTENT\n"
                "bad\x00value\n"
                ">>>>>>> CONTENT\n"
            )
        ),
    )


def test_whole_file_and_partial_edit_cannot_share_target() -> None:
    _assert_error(
        "INPUT_PARSE_ERROR",
        lambda: parse_edit_specification(
            """FILE: src/a.py
LABEL: whole
MODE: REPLACE_FILE
<<<<<<< CONTENT
whole
>>>>>>> CONTENT

FILE: src/a.py
LABEL: partial
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE
"""
        ),
    )


def test_two_whole_file_edits_cannot_share_target() -> None:
    _assert_error(
        "INPUT_PARSE_ERROR",
        lambda: parse_edit_specification(
            (
                "FILE: src/a.py\n"
                "LABEL: first\n"
                "MODE: DELETE\n"
                "\n"
                "FILE: src/a.py\n"
                "LABEL: second\n"
                "MODE: REPLACE_FILE\n"
                + "<" * 7
                + " CONTENT\n"
                + "replacement\n"
                + ">" * 7
                + " CONTENT\n"
            )
        ),
    )


def test_create_default_builds_exact_create_mutation(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    text = """FILE: src/new.py
LABEL: create-new
MODE: CREATE
<<<<<<< CONTENT
alpha
beta
>>>>>>> CONTENT
"""

    expected_ref = (
        parse_edit_specification(
            text
        ).edits[0].edit_ref
    )

    plan = plan_edit_text(
        tmp_path,
        text,
    )
    mutation = plan.files[0]

    assert mutation.target == "src/new.py"
    assert (
        mutation.operation
        is FileMutationOperation.CREATE
    )
    assert mutation.before_exists is False
    assert mutation.before_sha256 is None
    assert mutation.before_bytes is None
    assert mutation.after_exists is True
    assert mutation.after_bytes == b"alpha\nbeta\n"
    assert mutation.after_sha256 == (
        hashlib.sha256(
            b"alpha\nbeta\n"
        ).hexdigest()
    )
    assert mutation.newline_style is NewlineStyle.LF
    assert mutation.final_newline is True
    assert mutation.edit_refs == (
        expected_ref,
    )
    assert mutation.changed_ranges == ()
    assert not (
        tmp_path / "src/new.py"
    ).exists()


def test_create_explicit_crlf_no_final_newline_and_bom(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()

    plan = plan_edit_text(
        tmp_path,
        """FILE: src/new.txt
LABEL: create-new
MODE: CREATE
NEWLINE: CRLF
FINAL_NEWLINE: NO
BOM: YES
<<<<<<< CONTENT
alpha
beta
>>>>>>> CONTENT
""",
    )
    mutation = plan.files[0]

    assert mutation.after_bytes == (
        codecs.BOM_UTF8
        + b"alpha\r\nbeta"
    )
    assert (
        mutation.newline_style
        is NewlineStyle.CRLF
    )
    assert mutation.final_newline is False


def test_create_final_newline_no_can_create_empty_file(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        """FILE: empty.txt
LABEL: create-empty
MODE: CREATE
FINAL_NEWLINE: NO
<<<<<<< CONTENT
>>>>>>> CONTENT
""",
    )

    assert plan.files[0].after_bytes == b""
    assert plan.files[0].newline_style is None
    assert plan.files[0].final_newline is False


def test_create_existing_target_fails_closed(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"existing\n",
    )

    _assert_error(
        "TARGET_ALREADY_EXISTS",
        lambda: plan_edit_text(
            tmp_path,
            """FILE: src/a.py
LABEL: create-a
MODE: CREATE
<<<<<<< CONTENT
new
>>>>>>> CONTENT
""",
        ),
    )


def test_create_missing_parent_chain_is_planned_without_write(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        """FILE: missing/deep/a.py
LABEL: create-a
MODE: CREATE
<<<<<<< CONTENT
new
>>>>>>> CONTENT
""",
    )

    mutation = plan.files[0]

    assert mutation.create_parent_directories == (
        "missing",
        "missing/deep",
    )
    assert not (
        tmp_path
        / "missing"
    ).exists()


def test_create_plan_records_root_identity(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: new.txt\n"
            "LABEL: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "created\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    root_stat = tmp_path.lstat()

    assert plan.root_device == root_stat.st_dev
    assert plan.root_inode == root_stat.st_ino


def test_create_existing_parent_identity_is_recorded(
    tmp_path: Path,
) -> None:
    existing = (
        tmp_path
        / "existing"
    )
    existing.mkdir()

    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: existing/missing/new.txt\n"
            "LABEL: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "created\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    mutation = plan.files[0]
    identity = (
        mutation
        .create_existing_parent_identities[0]
    )
    existing_stat = existing.lstat()

    assert identity.relative_path == "existing"
    assert identity.device == existing_stat.st_dev
    assert identity.inode == existing_stat.st_ino
    assert mutation.create_parent_directories == (
        "existing/missing",
    )
    assert not (
        existing
        / "missing"
    ).exists()


def test_create_non_directory_parent_diagnostic_is_privacy_safe(
    tmp_path: Path,
) -> None:
    parent = (
        tmp_path
        / "private-parent-marker"
    )
    parent.write_text(
        "not a directory",
        encoding="utf-8",
    )

    error = _assert_error(
        "TARGET_INVALID_PATH",
        lambda: plan_edit_text(
            tmp_path,
            (

                "FILE: private-parent-marker/new.txt\n"
                "LABEL: create under invalid parent\n"
                "MODE: CREATE\n\n"
                + "<" * 7
                + " CONTENT\n"
                + "new\n"
                + ">" * 7
                + " CONTENT\n"
            ),
        ),
    )

    assert (
        "private-parent-marker/new.txt"
        in error.message
    )
    assert (
        str(tmp_path)
        not in error.message
    )


def test_create_symlink_parent_fails_closed(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"

    try:
        linked_parent.symlink_to(
            real_parent,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip(
            "symbolic links are unavailable"
        )

    _assert_error(
        "TARGET_SYMLINK",
        lambda: plan_edit_text(
            tmp_path,
            """FILE: linked/a.py
LABEL: create-a
MODE: CREATE
<<<<<<< CONTENT
new
>>>>>>> CONTENT
""",
        ),
    )


def test_replace_file_preserves_existing_representation(
    tmp_path: Path,
) -> None:
    before = (
        codecs.BOM_UTF8
        + b"old\r\nlast"
    )
    _write(
        tmp_path,
        "config/example.txt",
        before,
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
<<<<<<< CONTENT
new
next
>>>>>>> CONTENT
""",
    )
    mutation = plan.files[0]

    assert mutation.before_bytes == before
    assert mutation.after_bytes == (
        codecs.BOM_UTF8
        + b"new\r\nnext"
    )
    assert (
        mutation.newline_style
        is NewlineStyle.CRLF
    )
    assert mutation.final_newline is False


def test_replace_file_explicit_representation_can_change_file(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "config/example.txt",
        codecs.BOM_UTF8
        + b"old\r\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
NEWLINE: LF
FINAL_NEWLINE: YES
BOM: NO
<<<<<<< CONTENT
new
>>>>>>> CONTENT
""",
    )

    assert plan.files[0].after_bytes == b"new\n"
    assert (
        plan.files[0].newline_style
        is NewlineStyle.LF
    )
    assert plan.files[0].final_newline is True


def test_replace_file_byte_identical_candidate_is_no_change(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "config/example.txt",
        b"same\n",
    )

    _assert_error(
        "NO_CHANGE",
        lambda: plan_edit_text(
            tmp_path,
            """FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
<<<<<<< CONTENT
same
>>>>>>> CONTENT
""",
        ),
    )


def test_replace_file_preserve_without_existing_newline_style_fails_for_multiline(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "config/example.txt",
        b"single",
    )

    _assert_error(
        "UNSUPPORTED_NEWLINE",
        lambda: plan_edit_text(
            tmp_path,
            """FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
<<<<<<< CONTENT
first
second
>>>>>>> CONTENT
""",
        ),
    )


def test_replace_file_explicit_newline_can_expand_single_line_file(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "config/example.txt",
        b"single",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
NEWLINE: LF
FINAL_NEWLINE: NO
<<<<<<< CONTENT
first
second
>>>>>>> CONTENT
""",
    )

    assert (
        plan.files[0].after_bytes
        == b"first\nsecond"
    )


def test_delete_builds_exact_delete_mutation(
    tmp_path: Path,
) -> None:
    before = b"obsolete\n"
    _write(
        tmp_path,
        "src/obsolete.py",
        before,
    )

    text = """FILE: src/obsolete.py
LABEL: remove-obsolete
MODE: DELETE
"""

    expected_ref = (
        parse_edit_specification(
            text
        ).edits[0].edit_ref
    )

    plan = plan_edit_text(
        tmp_path,
        text,
    )
    mutation = plan.files[0]

    assert (
        mutation.operation
        is FileMutationOperation.DELETE
    )
    assert mutation.before_exists is True
    assert mutation.before_bytes == before
    assert mutation.before_sha256 == (
        hashlib.sha256(before).hexdigest()
    )
    assert mutation.after_exists is False
    assert mutation.after_sha256 is None
    assert mutation.after_bytes is None
    assert mutation.edit_refs == (
        expected_ref,
    )
    assert (
        tmp_path / "src/obsolete.py"
    ).read_bytes() == before


def test_delete_missing_target_fails_closed(
    tmp_path: Path,
) -> None:
    _assert_error(
        "TARGET_NOT_FOUND",
        lambda: plan_edit_text(
            tmp_path,
            """FILE: missing.py
LABEL: remove-missing
MODE: DELETE
""",
        ),
    )


def test_whole_file_and_partial_operations_can_share_bundle_across_targets(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    _write(
        tmp_path,
        "src/existing.py",
        b"old()\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: src/new.py
LABEL: create-new
MODE: CREATE
<<<<<<< CONTENT
created()
>>>>>>> CONTENT

FILE: src/existing.py
LABEL: update-existing
<<<<<<< SEARCH
old()
=======
new()
>>>>>>> REPLACE
""",
    )

    assert [
        mutation.target
        for mutation in plan.files
    ] == [
        "src/existing.py",
        "src/new.py",
    ]
    assert [
        mutation.operation
        for mutation in plan.files
    ] == [
        FileMutationOperation.REPLACE,
        FileMutationOperation.CREATE,
    ]
