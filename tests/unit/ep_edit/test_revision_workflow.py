from __future__ import annotations

from pathlib import Path

import pytest

from ep_edit.draft import revise_draft_file
from ep_edit.errors import DeterministicEditError
from ep_edit.revision import (
    parse_revision_specification,
    revise_edit_specification,
)
from ep_edit.specification import parse_edit_specification


pytestmark = pytest.mark.unit


BASE_SPEC = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: update-a

<<<<<<< SEARCH
old_a()
=======
new_a()
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


def test_repeated_revision_across_separate_draft_runs(
    tmp_path: Path,
) -> None:
    draft = (
        tmp_path
        / "edits.txt"
    )
    draft.write_text(
        BASE_SPEC,
        encoding="utf-8",
    )

    first_revision = """REVISION_SPEC_VERSION: 1

REVISE_EDIT: update-a

<<<<<<< EDIT
FILE: src/a.py
EDIT: update-a

<<<<<<< SEARCH
old_a()
=======
better_a()
>>>>>>> REPLACE
>>>>>>> EDIT
"""

    second_revision = """REVISION_SPEC_VERSION: 1

REVISE_EDIT: update-a

<<<<<<< EDIT
FILE: src/a.py
EDIT: update-a

<<<<<<< SEARCH
old_a()
=======
best_a()
>>>>>>> REPLACE
>>>>>>> EDIT
"""

    first_result = revise_draft_file(
        draft,
        first_revision,
    )
    second_result = revise_draft_file(
        draft,
        second_revision,
    )

    assert (
        first_result.revised_edit_ids
        == ("update-a",)
    )
    assert (
        second_result.revised_edit_ids
        == ("update-a",)
    )

    parsed = parse_edit_specification(
        draft.read_text(
            encoding="utf-8"
        )
    )

    assert (
        parsed.edits[0].replace_lines
        == ("best_a()",)
    )


def test_revision_may_change_file_target() -> None:
    result = revise_edit_specification(
        BASE_SPEC,
        """REVISION_SPEC_VERSION: 1

REVISE_EDIT: update-a

<<<<<<< EDIT
FILE: src/renamed_target.py
EDIT: update-a

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    parsed = parse_edit_specification(
        result.revised_text
    )

    assert (
        parsed.edits[0].target
        == "src/renamed_target.py"
    )
    assert (
        parsed.edits[0].edit_id
        == "update-a"
    )


def test_revision_may_change_search_only() -> None:
    result = revise_edit_specification(
        BASE_SPEC,
        """REVISION_SPEC_VERSION: 1

REVISE_EDIT: update-a

<<<<<<< EDIT
FILE: src/a.py
EDIT: update-a

<<<<<<< SEARCH
older_a()
=======
new_a()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    parsed = parse_edit_specification(
        result.revised_text
    )
    edit = parsed.edits[0]

    assert (
        edit.search_lines
        == ("older_a()",)
    )
    assert (
        edit.replace_lines
        == ("new_a()",)
    )


def test_revision_may_change_replace_only() -> None:
    result = revise_edit_specification(
        BASE_SPEC,
        """REVISION_SPEC_VERSION: 1

REVISE_EDIT: update-a

<<<<<<< EDIT
FILE: src/a.py
EDIT: update-a

<<<<<<< SEARCH
old_a()
=======
better_a()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )

    parsed = parse_edit_specification(
        result.revised_text
    )
    edit = parsed.edits[0]

    assert (
        edit.search_lines
        == ("old_a()",)
    )
    assert (
        edit.replace_lines
        == ("better_a()",)
    )


def test_malformed_replacement_block_fails_closed() -> None:
    _assert_error(
        "REVISION_PARSE_ERROR",
        lambda: parse_revision_specification(
            """REVISION_SPEC_VERSION: 1

REVISE_EDIT: update-a

<<<<<<< EDIT
FILE: src/a.py
EDIT: update-a

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> EDIT
"""
        ),
    )
