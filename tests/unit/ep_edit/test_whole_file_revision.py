from __future__ import annotations

from pathlib import Path

import pytest

from ep_edit.errors import DeterministicEditError
from ep_edit.planner import (
    FileMutationOperation,
    plan_edit_text,
)
from ep_edit.revision import (
    revise_edit_specification,
)
from ep_edit.specification import (
    SearchReplaceEdit,
    WholeFileEdit,
    WholeFileMode,
    parse_edit_specification,
)


pytestmark = pytest.mark.unit


def _edit_refs(
    text: str,
) -> tuple[str, ...]:
    return tuple(
        edit.edit_ref
        for edit in parse_edit_specification(
            text
        ).edits
    )


PARTIAL_BLOCK = """FILE: src/a.py
LABEL: update-a

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE
"""


WHOLE_CREATE_BLOCK = """FILE: src/new.py
LABEL: create-new
MODE: CREATE
FINAL_NEWLINE: NO
<<<<<<< CONTENT
created()
>>>>>>> CONTENT
"""


PARTIAL_BASE = PARTIAL_BLOCK

MIXED_BASE = (
    WHOLE_CREATE_BLOCK
    + "\n"
    + PARTIAL_BLOCK
)

CREATE_REF, PARTIAL_REF = (
    _edit_refs(
        MIXED_BASE
    )
)


def _assert_error(
    expected_code: str,
    callable_,
) -> DeterministicEditError:
    with pytest.raises(
        DeterministicEditError
    ) as raised:
        callable_()

    assert (
        raised.value.code
        == expected_code
    )

    return raised.value


def test_keep_whole_file_block_is_preserved_exactly() -> None:
    result = revise_edit_specification(
        MIXED_BASE,
        f"""
REVISE_EDIT: {PARTIAL_REF}

<<<<<<< EDIT
FILE: src/a.py
LABEL: update-a

<<<<<<< SEARCH
old_a()
=======
better_a()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    assert (
        WHOLE_CREATE_BLOCK
        in result.revised_text
    )

    parsed = parse_edit_specification(
        result.revised_text
    )

    create_edit = parsed.edits[0]

    assert isinstance(
        create_edit,
        WholeFileEdit,
    )
    assert (
        create_edit.edit_ref
        == CREATE_REF
    )


def test_revise_whole_file_to_whole_file() -> None:
    base = """FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
<<<<<<< CONTENT
old
>>>>>>> CONTENT
"""
    base_ref = _edit_refs(
        base
    )[0]

    result = revise_edit_specification(
        base,
        f"""
REVISE_EDIT: {base_ref}

<<<<<<< EDIT
FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
NEWLINE: LF
FINAL_NEWLINE: NO
BOM: NO
<<<<<<< CONTENT
better
>>>>>>> CONTENT
>>>>>>> EDIT
""",
    )

    edit = parse_edit_specification(
        result.revised_text
    ).edits[0]

    assert isinstance(
        edit,
        WholeFileEdit,
    )
    assert (
        edit.mode
        is WholeFileMode.REPLACE_FILE
    )
    assert edit.content_lines == (
        "better",
    )


def test_revise_partial_to_whole_file() -> None:
    result = revise_edit_specification(
        PARTIAL_BASE,
        f"""
REVISE_EDIT: {PARTIAL_REF}

<<<<<<< EDIT
FILE: src/new.py
LABEL: update-a
MODE: CREATE
FINAL_NEWLINE: NO
<<<<<<< CONTENT
created()
>>>>>>> CONTENT
>>>>>>> EDIT
""",
    )

    edit = parse_edit_specification(
        result.revised_text
    ).edits[0]

    assert isinstance(
        edit,
        WholeFileEdit,
    )
    assert (
        result.revised_edit_ref_mappings[0][0]
        == PARTIAL_REF
    )
    assert edit.target == "src/new.py"
    assert (
        edit.mode
        is WholeFileMode.CREATE
    )


def test_revise_whole_file_to_partial() -> None:
    base = """FILE: src/a.py
LABEL: update-a
MODE: REPLACE_FILE
<<<<<<< CONTENT
whole replacement
>>>>>>> CONTENT
"""
    base_ref = _edit_refs(
        base
    )[0]

    result = revise_edit_specification(
        base,
        f"""
REVISE_EDIT: {base_ref}

<<<<<<< EDIT
FILE: src/a.py
LABEL: update-a

<<<<<<< SEARCH
old_a()
=======
better_a()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    edit = parse_edit_specification(
        result.revised_text
    ).edits[0]

    assert isinstance(
        edit,
        SearchReplaceEdit,
    )
    assert edit.search_lines == (
        "old_a()",
    )
    assert edit.replace_lines == (
        "better_a()",
    )


def test_remove_whole_file_edit() -> None:
    result = revise_edit_specification(
        MIXED_BASE,
        f"""
REMOVE_EDIT: {CREATE_REF}
""",
    )

    parsed = parse_edit_specification(
        result.revised_text
    )

    assert [
        edit.edit_ref
        for edit in parsed.edits
    ] == [
        PARTIAL_REF,
    ]
    assert (
        "MODE: CREATE"
        not in result.revised_text
    )


def test_add_whole_file_edit() -> None:
    result = revise_edit_specification(
        PARTIAL_BASE,
        """
ADD_EDIT:

<<<<<<< EDIT
FILE: src/new.py
LABEL: create-new
MODE: CREATE
FINAL_NEWLINE: NO
<<<<<<< CONTENT
created()
>>>>>>> CONTENT
>>>>>>> EDIT
""",
    )

    parsed = parse_edit_specification(
        result.revised_text
    )

    assert [
        edit.edit_ref
        for edit in parsed.edits
    ] == [
        PARTIAL_REF,
        CREATE_REF,
    ]
    assert isinstance(
        parsed.edits[1],
        WholeFileEdit,
    )


def test_mixed_revision_is_fully_replanned(
    tmp_path: Path,
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (
        src
        / "a.py"
    ).write_bytes(
        b"old_a()\n"
    )

    revised = revise_edit_specification(
        MIXED_BASE,
        f"""

REVISE_EDIT: {PARTIAL_REF}

<<<<<<< EDIT
FILE: src/a.py
LABEL: update-a

<<<<<<< SEARCH
old_a()
=======
better_a()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    plan = plan_edit_text(
        tmp_path,
        revised.revised_text,
    )

    assert [
        mutation.target
        for mutation in plan.files
    ] == [
        "src/a.py",
        "src/new.py",
    ]
    assert [
        mutation.operation
        for mutation in plan.files
    ] == [
        FileMutationOperation.REPLACE,
        FileMutationOperation.CREATE,
    ]
    assert (
        plan.files[0].after_bytes
        == b"better_a()\n"
    )
    assert (
        plan.files[1].after_bytes
        == b"created()"
    )


def test_keep_create_is_revalidated_after_revision(
    tmp_path: Path,
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (
        src
        / "a.py"
    ).write_bytes(
        b"old_a()\n"
    )

    revised = revise_edit_specification(
        MIXED_BASE,
        f"""

REVISE_EDIT: {PARTIAL_REF}

<<<<<<< EDIT
FILE: src/a.py
LABEL: update-a

<<<<<<< SEARCH
old_a()
=======
better_a()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    (
        src
        / "new.py"
    ).write_bytes(
        b"concurrent\n"
    )

    _assert_error(
        "TARGET_ALREADY_EXISTS",
        lambda: plan_edit_text(
            tmp_path,
            revised.revised_text,
        ),
    )


def test_crlf_whole_file_revision_keeps_draft_newlines() -> None:
    base = """FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
<<<<<<< CONTENT
old
>>>>>>> CONTENT
""".replace(
        "\n",
        "\r\n",
    )
    base_ref = _edit_refs(
        base
    )[0]

    result = revise_edit_specification(
        base,
        f"""
REVISE_EDIT: {base_ref}

<<<<<<< EDIT
FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
<<<<<<< CONTENT
better
>>>>>>> CONTENT
>>>>>>> EDIT
""",
    )

    assert "\r\n" in (
        result.revised_text
    )
    assert "\n" not in (
        result.revised_text.replace(
            "\r\n",
            "",
        )
    )


def test_delete_at_eof_without_final_newline_can_be_removed() -> None:
    base = (
        PARTIAL_BLOCK
        + "\n"
        + "FILE: src/obsolete.py\n"
        + "LABEL: remove-obsolete\n"
        + "MODE: DELETE"
    )
    remove_ref = _edit_refs(
        base
    )[1]

    result = revise_edit_specification(
        base,
        f"""
REMOVE_EDIT: {remove_ref}
""",
    )

    parsed = parse_edit_specification(
        result.revised_text
    )

    assert [
        edit.edit_ref
        for edit in parsed.edits
    ] == [
        PARTIAL_REF,
    ]


def test_whole_file_edit_can_be_revised_repeatedly() -> None:
    base = """FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
<<<<<<< CONTENT
first
>>>>>>> CONTENT
"""
    base_ref = _edit_refs(
        base
    )[0]

    first = revise_edit_specification(
        base,
        f"""
REVISE_EDIT: {base_ref}

<<<<<<< EDIT
FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
<<<<<<< CONTENT
second
>>>>>>> CONTENT
>>>>>>> EDIT
""",
    )

    first_ref = (
        parse_edit_specification(
            first.revised_text
        ).edits[0].edit_ref
    )

    second = revise_edit_specification(
        first.revised_text,
        f"""
REVISE_EDIT: {first_ref}

<<<<<<< EDIT
FILE: config/example.txt
LABEL: replace-config
MODE: REPLACE_FILE
<<<<<<< CONTENT
third
>>>>>>> CONTENT
>>>>>>> EDIT
""",
    )

    edit = parse_edit_specification(
        second.revised_text
    ).edits[0]

    assert isinstance(
        edit,
        WholeFileEdit,
    )
    assert edit.content_lines == (
        "third",
    )
