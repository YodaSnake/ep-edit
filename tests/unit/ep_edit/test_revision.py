from __future__ import annotations

import pytest

from ep_edit.errors import DeterministicEditError
from ep_edit.revision import (
    RevisionOperationKind,
    parse_revision_specification,
    revise_edit_specification,
)
from ep_edit.specification import (
    parse_edit_specification,
)


pytestmark = pytest.mark.unit


BASE_SPEC = """

FILE: src/a.py
LABEL: keep-a

<<<<<<< SEARCH
# keep-a
old_a()
=======
# keep-a
new_a()
>>>>>>> REPLACE

FILE: src/b.py
LABEL: revise-b

<<<<<<< SEARCH
old_b()
=======
new_b()
>>>>>>> REPLACE

FILE: tests/test_a.py
LABEL: remove-test

<<<<<<< SEARCH
old_test()
=======
new_test()
>>>>>>> REPLACE
"""


def _base_refs() -> tuple[
    str,
    str,
    str,
]:
    parsed = parse_edit_specification(
        BASE_SPEC
    )

    return tuple(
        edit.edit_id
        for edit in parsed.edits
    )


KEEP_REF, REVISE_REF, REMOVE_REF = (
    _base_refs()
)


MISSING_SPEC = """

FILE: src/missing.py
LABEL: missing

<<<<<<< SEARCH
old()
=======
new()
>>>>>>> REPLACE
"""


MISSING_REF = (
    parse_edit_specification(
        MISSING_SPEC
    ).edits[0].edit_id
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


def test_parse_revision_operation_kinds() -> None:
    revision = parse_revision_specification(
        f"""
REVISE_EDIT: {REVISE_REF}

<<<<<<< EDIT
FILE: src/b.py
LABEL: revise-b

<<<<<<< SEARCH
old_b()
=======
better_b()
>>>>>>> REPLACE
>>>>>>> EDIT

REMOVE_EDIT: {REMOVE_REF}

ADD_EDIT:

<<<<<<< EDIT
FILE: src/c.py
LABEL: add-c

<<<<<<< SEARCH
old_c()
=======
new_c()
>>>>>>> REPLACE
>>>>>>> EDIT
"""
    )

    assert [
        operation.kind
        for operation in revision.operations
    ] == [
        RevisionOperationKind.REVISE,
        RevisionOperationKind.REMOVE,
        RevisionOperationKind.ADD,
    ]
    assert (
        revision.operations[0].edit_id
        == REVISE_REF
    )
    assert (
        revision.operations[1].edit_block
        is None
    )
    assert (
        revision.operations[2]
        .edit_id
        .startswith("e_")
    )


def test_revise_preserves_keep_block_exactly() -> None:
    keep_block = """FILE: src/a.py
LABEL: keep-a

<<<<<<< SEARCH
# keep-a
old_a()
=======
# keep-a
new_a()
>>>>>>> REPLACE
"""

    result = revise_edit_specification(
        BASE_SPEC,
        f"""
REVISE_EDIT: {REVISE_REF}

<<<<<<< EDIT
FILE: src/b.py
LABEL: revise-b

<<<<<<< SEARCH
old_b()
=======
better_b()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    assert keep_block in result.revised_text
    assert "better_b()" in result.revised_text
    assert (
        result.revised_edit_ids
        == (REVISE_REF,)
    )
    assert result.removed_edit_ids == ()
    assert result.added_edit_ids == ()


def test_remove_edit_removes_whole_edit_block() -> None:
    result = revise_edit_specification(
        BASE_SPEC,
        f"""
REMOVE_EDIT: {REMOVE_REF}
""",
    )

    parsed = parse_edit_specification(
        result.revised_text
    )

    assert [
        edit.target
        for edit in parsed.edits
    ] == [
        "src/a.py",
        "src/b.py",
    ]
    assert (
        result.removed_edit_ids
        == (REMOVE_REF,)
    )
    assert (
        "LABEL: remove-test"
        not in result.revised_text
    )


def test_add_edit_appends_valid_edit() -> None:
    result = revise_edit_specification(
        BASE_SPEC,
        """
ADD_EDIT:

<<<<<<< EDIT
FILE: tests/test_b.py
LABEL: add-test

<<<<<<< SEARCH
old()
=======
new()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    parsed = parse_edit_specification(
        result.revised_text
    )

    assert [
        edit.target
        for edit in parsed.edits
    ] == [
        "src/a.py",
        "src/b.py",
        "tests/test_a.py",
        "tests/test_b.py",
    ]
    assert len(
        result.added_edit_ids
    ) == 1
    assert (
        result.added_edit_ids[0]
        == parsed.edits[-1].edit_id
    )


def test_missing_revise_target_fails_closed() -> None:
    _assert_error(
        "REVISION_EDIT_NOT_FOUND",
        lambda: revise_edit_specification(
            BASE_SPEC,
            f"""
REVISE_EDIT: {MISSING_REF}

<<<<<<< EDIT
FILE: src/missing.py
LABEL: missing

<<<<<<< SEARCH
old()
=======
better()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
        ),
    )


def test_missing_remove_target_fails_closed() -> None:
    _assert_error(
        "REVISION_EDIT_NOT_FOUND",
        lambda: revise_edit_specification(
            BASE_SPEC,
            f"""
REMOVE_EDIT: {MISSING_REF}
""",
        ),
    )


def test_add_existing_edit_fails_closed() -> None:
    _assert_error(
        "REVISION_EDIT_ALREADY_EXISTS",
        lambda: revise_edit_specification(
            BASE_SPEC,
            """
ADD_EDIT:

<<<<<<< EDIT
FILE: src/a.py
LABEL: duplicate-keep

<<<<<<< SEARCH
# keep-a
old_a()
=======
# keep-a
new_a()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
        ),
    )


def test_removing_only_edit_fails_reparse() -> None:
    base = """

FILE: src/a.py
LABEL: only

<<<<<<< SEARCH
old()
=======
new()
>>>>>>> REPLACE
"""
    only_ref = (
        parse_edit_specification(
            base
        ).edits[0].edit_id
    )

    _assert_error(
        "REVISION_PARSE_ERROR",
        lambda: revise_edit_specification(
            base,
            f"""
REMOVE_EDIT: {only_ref}
""",
        ),
    )


def test_revision_batch_order_does_not_change_output() -> None:
    revision_a = f"""
REVISE_EDIT: {REVISE_REF}

<<<<<<< EDIT
FILE: src/b.py
LABEL: revise-b

<<<<<<< SEARCH
old_b()
=======
better_b()
>>>>>>> REPLACE
>>>>>>> EDIT

REMOVE_EDIT: {REMOVE_REF}

ADD_EDIT:

<<<<<<< EDIT
FILE: src/z.py
LABEL: add-z

<<<<<<< SEARCH
old_z()
=======
new_z()
>>>>>>> REPLACE
>>>>>>> EDIT

ADD_EDIT:

<<<<<<< EDIT
FILE: src/new_a.py
LABEL: add-a

<<<<<<< SEARCH
old_new_a()
=======
new_new_a()
>>>>>>> REPLACE
>>>>>>> EDIT
"""

    revision_b = f"""
ADD_EDIT:

<<<<<<< EDIT
FILE: src/new_a.py
LABEL: add-a

<<<<<<< SEARCH
old_new_a()
=======
new_new_a()
>>>>>>> REPLACE
>>>>>>> EDIT

ADD_EDIT:

<<<<<<< EDIT
FILE: src/z.py
LABEL: add-z

<<<<<<< SEARCH
old_z()
=======
new_z()
>>>>>>> REPLACE
>>>>>>> EDIT

REMOVE_EDIT: {REMOVE_REF}

REVISE_EDIT: {REVISE_REF}

<<<<<<< EDIT
FILE: src/b.py
LABEL: revise-b

<<<<<<< SEARCH
old_b()
=======
better_b()
>>>>>>> REPLACE
>>>>>>> EDIT
"""

    result_a = revise_edit_specification(
        BASE_SPEC,
        revision_a,
    )
    result_b = revise_edit_specification(
        BASE_SPEC,
        revision_b,
    )

    assert (
        result_a.revised_text
        == result_b.revised_text
    )
    assert (
        result_a.revised_fingerprint
        == result_b.revised_fingerprint
    )


def test_crlf_base_keeps_crlf_for_revised_block() -> None:
    base = BASE_SPEC.replace(
        "\n",
        "\r\n",
    )

    result = revise_edit_specification(
        base,
        f"""
REVISE_EDIT: {REVISE_REF}

<<<<<<< EDIT
FILE: src/b.py
LABEL: revise-b

<<<<<<< SEARCH
old_b()
=======
better_b()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    assert "\r\n" in result.revised_text
    assert (
        "\nbetter_b()\n"
        not in result.revised_text
    )


def test_revision_fingerprint_changes_with_content() -> None:
    result = revise_edit_specification(
        BASE_SPEC,
        f"""
REVISE_EDIT: {REVISE_REF}

<<<<<<< EDIT
FILE: src/b.py
LABEL: revise-b

<<<<<<< SEARCH
old_b()
=======
better_b()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    assert (
        result.base_fingerprint
        != result.revised_fingerprint
    )
