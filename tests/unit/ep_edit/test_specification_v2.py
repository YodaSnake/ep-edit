from __future__ import annotations

import pytest

from ep_edit.errors import DeterministicEditError
from ep_edit.specification import (
    SearchReplaceEdit,
    WholeFileEdit,
    WholeFileMode,
    parse_edit_specification,
)


pytestmark = pytest.mark.unit

_SEARCH_OPEN = "<" * 7 + " SEARCH"
_REPLACE_SEPARATOR = "=" * 7
_REPLACE_CLOSE = ">" * 7 + " REPLACE"

_CONTENT_OPEN = "<" * 7 + " CONTENT"
_CONTENT_CLOSE = ">" * 7 + " CONTENT"


SEARCH_SPEC = f"""EDIT_SPEC_VERSION: 2

FILE: src/a.py

{_SEARCH_OPEN}
old_a()
{_REPLACE_SEPARATOR}
new_a()
{_REPLACE_CLOSE}
"""


def _assert_error(
    code: str,
    callable_,
) -> DeterministicEditError:
    with pytest.raises(
        DeterministicEditError
    ) as raised:
        callable_()

    assert raised.value.code == code
    return raised.value


def test_v2_search_edit_generates_deterministic_ref() -> None:
    first = parse_edit_specification(
        SEARCH_SPEC
    )
    second = parse_edit_specification(
        SEARCH_SPEC
    )

    assert first.version == 2

    first_edit = first.edits[0]
    second_edit = second.edits[0]

    assert isinstance(
        first_edit,
        SearchReplaceEdit,
    )
    assert (
        first_edit.edit_id
        == second_edit.edit_id
    )
    assert first_edit.edit_id.startswith(
        "e_"
    )
    assert (
        len(first_edit.edit_id)
        == 18
    )


def test_v2_label_is_optional_and_not_part_of_identity() -> None:
    unlabeled = parse_edit_specification(
        SEARCH_SPEC
    ).edits[0]

    labeled = parse_edit_specification(
        SEARCH_SPEC.replace(
            "FILE: src/a.py\n",
            (
                "FILE: src/a.py\n"
                "LABEL: update a\n"
            ),
        )
    ).edits[0]

    assert labeled.label == "update a"
    assert (
        labeled.edit_id
        == unlabeled.edit_id
    )


def test_v2_content_change_changes_edit_ref() -> None:
    original = parse_edit_specification(
        SEARCH_SPEC
    ).edits[0]

    changed = parse_edit_specification(
        SEARCH_SPEC.replace(
            "new_a()",
            "better_a()",
        )
    ).edits[0]

    assert (
        original.edit_id
        != changed.edit_id
    )


def test_v2_target_change_changes_edit_ref() -> None:
    original = parse_edit_specification(
        SEARCH_SPEC
    ).edits[0]

    changed = parse_edit_specification(
        SEARCH_SPEC.replace(
            "src/a.py",
            "src/b.py",
        )
    ).edits[0]

    assert (
        original.edit_id
        != changed.edit_id
    )


def test_v2_rejects_authored_edit_id() -> None:
    error = _assert_error(
        "INPUT_PARSE_ERROR",
        lambda: parse_edit_specification(
            SEARCH_SPEC.replace(
                "FILE: src/a.py\n",
                (
                    "FILE: src/a.py\n"
                    "EDIT: authored-name\n"
                ),
            )
        ),
    )

    assert (
        "EditRef is generated"
        in error.message
    )


def test_v2_duplicate_identical_edit_ref_fails_closed() -> None:
    duplicate_block = (
        SEARCH_SPEC
        .partition(
            "\n\n"
        )[2]
    )

    error = _assert_error(
        "DUPLICATE_EDIT_REF",
        lambda: parse_edit_specification(
            SEARCH_SPEC
            + "\n"
            + duplicate_block
        ),
    )

    assert (
        "duplicate generated EditRef"
        in error.message
    )


def test_v2_create_generates_edit_ref() -> None:
    specification = (
        parse_edit_specification(
            f"""EDIT_SPEC_VERSION: 2

FILE: generated/example.txt
LABEL: create example
MODE: CREATE
FINAL_NEWLINE: NO
{_CONTENT_OPEN}
created
{_CONTENT_CLOSE}
"""
        )
    )

    edit = specification.edits[0]

    assert isinstance(
        edit,
        WholeFileEdit,
    )
    assert (
        edit.mode
        is WholeFileMode.CREATE
    )
    assert edit.edit_id.startswith(
        "e_"
    )
    assert (
        edit.label
        == "create example"
    )


def test_v1_authored_edit_id_remains_supported() -> None:
    specification = (
        parse_edit_specification(
            f"""EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: legacy-id

{_SEARCH_OPEN}
old_a()
{_REPLACE_SEPARATOR}
new_a()
{_REPLACE_CLOSE}
"""
        )
    )

    assert (
        specification.edits[0].edit_id
        == "legacy-id"
    )
