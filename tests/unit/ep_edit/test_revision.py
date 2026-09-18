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


BASE_SPEC = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: keep-a

<<<<<<< SEARCH
# keep-a
old_a()
=======
# keep-a
new_a()
>>>>>>> REPLACE

FILE: src/b.py
EDIT: revise-b

<<<<<<< SEARCH
old_b()
=======
new_b()
>>>>>>> REPLACE

FILE: tests/test_a.py
EDIT: remove-test

<<<<<<< SEARCH
old_test()
=======
new_test()
>>>>>>> REPLACE
"""


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


def test_parse_revise_edit() -> None:
    revision = (
        parse_revision_specification(
            """REVISION_SPEC_VERSION: 1

REVISE_EDIT: revise-b

<<<<<<< EDIT
FILE: src/b.py
EDIT: revise-b

<<<<<<< SEARCH
old_b()
=======
better_b()
>>>>>>> REPLACE
>>>>>>> EDIT
"""
        )
    )

    assert revision.version == 1
    assert len(
        revision.operations
    ) == 1
    assert (
        revision.operations[0].kind
        is RevisionOperationKind.REVISE
    )
    assert (
        revision.operations[0].edit_id
        == "revise-b"
    )


def test_parse_remove_edit() -> None:
    revision = (
        parse_revision_specification(
            """REVISION_SPEC_VERSION: 1

REMOVE_EDIT: remove-test
"""
        )
    )

    assert (
        revision.operations[0].kind
        is RevisionOperationKind.REMOVE
    )
    assert (
        revision.operations[0].edit_block
        is None
    )


def test_parse_add_edit() -> None:
    revision = (
        parse_revision_specification(
            """REVISION_SPEC_VERSION: 1

ADD_EDIT: add-test

<<<<<<< EDIT
FILE: tests/test_b.py
EDIT: add-test

<<<<<<< SEARCH
old()
=======
new()
>>>>>>> REPLACE
>>>>>>> EDIT
"""
        )
    )

    assert (
        revision.operations[0].kind
        is RevisionOperationKind.ADD
    )


def test_revision_requires_explicit_version() -> None:
    _assert_error(
        "REVISION_PARSE_ERROR",
        lambda: parse_revision_specification(
            "REMOVE_EDIT: remove-test\n"
        ),
    )


def test_unknown_revision_version_fails_closed() -> None:
    _assert_error(
        "UNSUPPORTED_REVISION_SPEC_VERSION",
        lambda: parse_revision_specification(
            """REVISION_SPEC_VERSION: 3

REMOVE_EDIT: remove-test
"""
        ),
    )


def test_duplicate_revision_target_fails_closed() -> None:
    _assert_error(
        "REVISION_DUPLICATE_TARGET",
        lambda: parse_revision_specification(
            """REVISION_SPEC_VERSION: 1

REVISE_EDIT: revise-b

<<<<<<< EDIT
FILE: src/b.py
EDIT: revise-b

<<<<<<< SEARCH
old_b()
=======
better_b()
>>>>>>> REPLACE
>>>>>>> EDIT

REMOVE_EDIT: revise-b
"""
        ),
    )


def test_revise_edit_id_must_match_embedded_id() -> None:
    _assert_error(
        "REVISION_EDIT_ID_MISMATCH",
        lambda: parse_revision_specification(
            """REVISION_SPEC_VERSION: 1

REVISE_EDIT: revise-b

<<<<<<< EDIT
FILE: src/b.py
EDIT: other-id

<<<<<<< SEARCH
old_b()
=======
better_b()
>>>>>>> REPLACE
>>>>>>> EDIT
"""
        ),
    )


def test_add_edit_id_must_match_embedded_id() -> None:
    _assert_error(
        "REVISION_EDIT_ID_MISMATCH",
        lambda: parse_revision_specification(
            """REVISION_SPEC_VERSION: 1

ADD_EDIT: add-test

<<<<<<< EDIT
FILE: tests/test_b.py
EDIT: other-id

<<<<<<< SEARCH
old()
=======
new()
>>>>>>> REPLACE
>>>>>>> EDIT
"""
        ),
    )


def test_revise_preserves_keep_block_exactly() -> None:
    keep_block = """FILE: src/a.py
EDIT: keep-a

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
        """REVISION_SPEC_VERSION: 1

REVISE_EDIT: revise-b

<<<<<<< EDIT
FILE: src/b.py
EDIT: revise-b

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
        == ("revise-b",)
    )
    assert (
        result.removed_edit_ids
        == ()
    )
    assert (
        result.added_edit_ids
        == ()
    )


def test_remove_edit_removes_whole_edit_block() -> None:
    result = revise_edit_specification(
        BASE_SPEC,
        """REVISION_SPEC_VERSION: 1

REMOVE_EDIT: remove-test
""",
    )

    parsed = parse_edit_specification(
        result.revised_text
    )

    assert [
        edit.edit_id
        for edit in parsed.edits
    ] == [
        "keep-a",
        "revise-b",
    ]
    assert (
        "EDIT: remove-test"
        not in result.revised_text
    )


def test_add_edit_appends_valid_edit() -> None:
    result = revise_edit_specification(
        BASE_SPEC,
        """REVISION_SPEC_VERSION: 1

ADD_EDIT: add-test

<<<<<<< EDIT
FILE: tests/test_b.py
EDIT: add-test

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
        edit.edit_id
        for edit in parsed.edits
    ] == [
        "keep-a",
        "revise-b",
        "remove-test",
        "add-test",
    ]
    assert (
        result.added_edit_ids
        == ("add-test",)
    )


def test_missing_revise_target_fails_closed() -> None:
    _assert_error(
        "REVISION_EDIT_NOT_FOUND",
        lambda: revise_edit_specification(
            BASE_SPEC,
            """REVISION_SPEC_VERSION: 1

REVISE_EDIT: missing

<<<<<<< EDIT
FILE: src/missing.py
EDIT: missing

<<<<<<< SEARCH
old()
=======
new()
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
            """REVISION_SPEC_VERSION: 1

REMOVE_EDIT: missing
""",
        ),
    )


def test_add_existing_edit_fails_closed() -> None:
    _assert_error(
        "REVISION_EDIT_ALREADY_EXISTS",
        lambda: revise_edit_specification(
            BASE_SPEC,
            """REVISION_SPEC_VERSION: 1

ADD_EDIT: keep-a

<<<<<<< EDIT
FILE: src/a.py
EDIT: keep-a

<<<<<<< SEARCH
old()
=======
new()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
        ),
    )


def test_removing_only_edit_fails_reparse() -> None:
    base = """FILE: src/a.py
EDIT: only

<<<<<<< SEARCH
old()
=======
new()
>>>>>>> REPLACE
"""

    _assert_error(
        "REVISION_PARSE_ERROR",
        lambda: revise_edit_specification(
            base,
            """REVISION_SPEC_VERSION: 1

REMOVE_EDIT: only
""",
        ),
    )


def test_revision_batch_order_does_not_change_output() -> None:
    revision_a = """REVISION_SPEC_VERSION: 1

REVISE_EDIT: revise-b

<<<<<<< EDIT
FILE: src/b.py
EDIT: revise-b

<<<<<<< SEARCH
old_b()
=======
better_b()
>>>>>>> REPLACE
>>>>>>> EDIT

REMOVE_EDIT: remove-test

ADD_EDIT: add-z

<<<<<<< EDIT
FILE: src/z.py
EDIT: add-z

<<<<<<< SEARCH
old_z()
=======
new_z()
>>>>>>> REPLACE
>>>>>>> EDIT

ADD_EDIT: add-a

<<<<<<< EDIT
FILE: src/new_a.py
EDIT: add-a

<<<<<<< SEARCH
old_new_a()
=======
new_new_a()
>>>>>>> REPLACE
>>>>>>> EDIT
"""

    revision_b = """REVISION_SPEC_VERSION: 1

ADD_EDIT: add-a

<<<<<<< EDIT
FILE: src/new_a.py
EDIT: add-a

<<<<<<< SEARCH
old_new_a()
=======
new_new_a()
>>>>>>> REPLACE
>>>>>>> EDIT

ADD_EDIT: add-z

<<<<<<< EDIT
FILE: src/z.py
EDIT: add-z

<<<<<<< SEARCH
old_z()
=======
new_z()
>>>>>>> REPLACE
>>>>>>> EDIT

REMOVE_EDIT: remove-test

REVISE_EDIT: revise-b

<<<<<<< EDIT
FILE: src/b.py
EDIT: revise-b

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
        """REVISION_SPEC_VERSION: 1

REVISE_EDIT: revise-b

<<<<<<< EDIT
FILE: src/b.py
EDIT: revise-b

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
        """REVISION_SPEC_VERSION: 1

REVISE_EDIT: revise-b

<<<<<<< EDIT
FILE: src/b.py
EDIT: revise-b

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
