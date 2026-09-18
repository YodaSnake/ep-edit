from __future__ import annotations

import pytest

from ep_edit.errors import DeterministicEditError
from ep_edit.specification import (
    normalize_target_path,
    parse_edit_specification,
)


pytestmark = pytest.mark.unit


def _current_spec(
    body: str,
) -> str:
    return body


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


def test_parse_single_search_replace_edit() -> None:
    specification = parse_edit_specification(
        _current_spec(
            """FILE: src/a.py
LABEL: update-a

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE
"""
        )
    )

    assert len(
        specification.edits
    ) == 1

    edit = specification.edits[0]

    assert edit.target == "src/a.py"
    assert edit.label == "update-a"
    assert edit.edit_id.startswith("e_")
    assert edit.search_lines == (
        "old_a()",
    )
    assert edit.replace_lines == (
        "new_a()",
    )


def test_crlf_transport_is_accepted() -> None:
    text = _current_spec(
        """FILE: src/a.py
LABEL: update-a

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE
"""
    ).replace(
        "\n",
        "\r\n",
    )

    specification = parse_edit_specification(
        text
    )

    assert (
        specification
        .edits[0]
        .search_lines
        == ("old_a()",)
    )


def test_logical_lines_preserve_comments_blanks_tabs_and_spaces() -> None:
    specification = parse_edit_specification(
        _current_spec(
            "FILE: src/a.py\n"
            "LABEL: preserve-lines\n"
            "\n"
            "<<<<<<< SEARCH\n"
            "# keep this comment\n"
            "\told_call()  \n"
            "\n"
            "=======\n"
            "# keep this comment\n"
            "\tnew_call()  \n"
            "\n"
            ">>>>>>> REPLACE\n"
        )
    )

    edit = specification.edits[0]

    assert edit.search_lines == (
        "# keep this comment",
        "\told_call()  ",
        "",
    )
    assert edit.replace_lines == (
        "# keep this comment",
        "\tnew_call()  ",
        "",
    )


def test_multiple_edits_for_same_file_are_parsed() -> None:
    specification = parse_edit_specification(
        _current_spec(
            """FILE: src/a.py
LABEL: first

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE

FILE: src/a.py
LABEL: second

<<<<<<< SEARCH
old_b()
=======
new_b()
>>>>>>> REPLACE
"""
        )
    )

    assert [
        edit.target
        for edit in specification.edits
    ] == [
        "src/a.py",
        "src/a.py",
    ]
    assert [
        edit.search_lines
        for edit in specification.edits
    ] == [
        ("old_a()",),
        ("old_b()",),
    ]
    assert (
        specification.edits[0].edit_id
        != specification.edits[1].edit_id
    )


def test_multiple_files_are_parsed() -> None:
    specification = parse_edit_specification(
        _current_spec(
            """FILE: src/a.py
LABEL: first

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE

FILE: tests/test_a.py
LABEL: second

<<<<<<< SEARCH
old_test()
=======
new_test()
>>>>>>> REPLACE
"""
        )
    )

    assert [
        edit.target
        for edit in specification.edits
    ] == [
        "src/a.py",
        "tests/test_a.py",
    ]


def test_empty_search_fails_closed() -> None:
    _assert_error(
        "INPUT_PARSE_ERROR",
        lambda: parse_edit_specification(
            _current_spec(
                """FILE: src/a.py
LABEL: empty-search

<<<<<<< SEARCH
=======
replacement
>>>>>>> REPLACE
"""
            )
        ),
    )


def test_empty_replace_is_allowed() -> None:
    specification = parse_edit_specification(
        _current_spec(
            """FILE: src/a.py
LABEL: remove-line

<<<<<<< SEARCH
obsolete()
=======
>>>>>>> REPLACE
"""
        )
    )

    assert (
        specification
        .edits[0]
        .replace_lines
        == ()
    )


def test_lone_cr_in_specification_fails_closed() -> None:
    _assert_error(
        "INPUT_PARSE_ERROR",
        lambda: parse_edit_specification(
            "FILE: src/a.py\r"
        ),
    )


@pytest.mark.parametrize(
    "target",
    [
        "",
        "/absolute/path.py",
        "../outside.py",
        "src/../outside.py",
        "src/./a.py",
        "src//a.py",
        r"src\a.py",
    ],
)
def test_invalid_target_path_fails_closed(
    target: str,
) -> None:
    _assert_error(
        "TARGET_INVALID_PATH",
        lambda: normalize_target_path(
            target
        ),
    )


def test_canonical_target_path_is_preserved() -> None:
    assert (
        normalize_target_path(
            "src/ep_edit/example.py"
        )
        == "src/ep_edit/example.py"
    )
