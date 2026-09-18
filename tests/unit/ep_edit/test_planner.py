from __future__ import annotations

import codecs
import hashlib
from pathlib import Path

import pytest

from ep_edit.errors import DeterministicEditError
from ep_edit.planner import (
    FileMutationOperation,
    plan_edit_text,
)
from ep_edit.revision import revise_edit_specification
from ep_edit.snapshot import NewlineStyle


pytestmark = pytest.mark.unit


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
) -> None:
    file_path = root / target
    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    file_path.write_bytes(raw)


def _spec(
    *,
    target: str = "src/a.py",
    edit_id: str = "edit-a",
    search: str,
    replace: str,
) -> str:
    return (
        "EDIT_SPEC_VERSION: 1\n"
        "\n"
        f"FILE: {target}\n"
        f"EDIT: {edit_id}\n"
        "\n"
        "<<<<<<< SEARCH\n"
        f"{search}"
        "=======\n"
        f"{replace}"
        ">>>>>>> REPLACE\n"
    )


def test_exact_single_edit_builds_file_mutation(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"before()\nold()\nafter()\n",
    )

    plan = plan_edit_text(
        tmp_path,
        _spec(
            search="old()\n",
            replace="new()\n",
        ),
    )

    assert len(plan.files) == 1
    mutation = plan.files[0]

    assert mutation.target == "src/a.py"
    assert (
        mutation.operation
        is FileMutationOperation.REPLACE
    )
    assert mutation.before_exists is True
    assert mutation.after_exists is True
    assert mutation.before_bytes == (
        b"before()\nold()\nafter()\n"
    )
    assert mutation.after_bytes == (
        b"before()\nnew()\nafter()\n"
    )


def test_zero_match_fails_closed(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"actual()\n",
    )

    _assert_error(
        "SEARCH_ZERO_MATCH",
        lambda: plan_edit_text(
            tmp_path,
            _spec(
                search="missing()\n",
                replace="new()\n",
            ),
        ),
    )


def test_multiple_match_fails_closed(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"old()\nold()\n",
    )

    _assert_error(
        "SEARCH_MULTIPLE_MATCH",
        lambda: plan_edit_text(
            tmp_path,
            _spec(
                search="old()\n",
                replace="new()\n",
            ),
        ),
    )


@pytest.mark.parametrize(
    ("raw", "search"),
    [
        (
            b"    old()\n",
            "  old()\n",
        ),
        (
            b"# keep\nold()\n",
            "# changed\nold()\n",
        ),
        (
            b"old()\n\nnext()\n",
            "old()\nnext()\n",
        ),
    ],
)
def test_exact_matching_rejects_semantic_line_mismatch(
    tmp_path: Path,
    raw: bytes,
    search: str,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        raw,
    )

    _assert_error(
        "SEARCH_ZERO_MATCH",
        lambda: plan_edit_text(
            tmp_path,
            _spec(
                search=search,
                replace="new()\n",
            ),
        ),
    )


def test_tabs_and_trailing_spaces_are_preserved(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"\told()  \nkeep() \n",
    )

    plan = plan_edit_text(
        tmp_path,
        _spec(
            search="\told()  \n",
            replace="\tnew()  \n",
        ),
    )

    assert plan.files[0].after_bytes == (
        b"\tnew()  \nkeep() \n"
    )


def test_multiple_independent_edits_use_original_snapshot(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"old_a()\nkeep()\nold_b()\n",
    )

    text = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: edit-a

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE

FILE: src/a.py
EDIT: edit-b

<<<<<<< SEARCH
old_b()
=======
new_b()
>>>>>>> REPLACE
"""

    plan = plan_edit_text(
        tmp_path,
        text,
    )

    assert plan.files[0].after_bytes == (
        b"new_a()\nkeep()\nnew_b()\n"
    )
    assert plan.files[0].edit_ids == (
        "edit-a",
        "edit-b",
    )


def test_edit_cannot_match_content_generated_by_prior_edit(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"old()\n",
    )

    text = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: first

<<<<<<< SEARCH
old()
=======
generated()
>>>>>>> REPLACE

FILE: src/a.py
EDIT: second

<<<<<<< SEARCH
generated()
=======
final()
>>>>>>> REPLACE
"""

    _assert_error(
        "SEARCH_ZERO_MATCH",
        lambda: plan_edit_text(
            tmp_path,
            text,
        ),
    )


def test_overlap_fails_closed(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"a\nb\nc\n",
    )

    text = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: first

<<<<<<< SEARCH
a
b
=======
x
>>>>>>> REPLACE

FILE: src/a.py
EDIT: second

<<<<<<< SEARCH
b
c
=======
y
>>>>>>> REPLACE
"""

    _assert_error(
        "EDIT_OVERLAP",
        lambda: plan_edit_text(
            tmp_path,
            text,
        ),
    )


def test_adjacent_ranges_are_allowed(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"a\nb\n",
    )

    text = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: first

<<<<<<< SEARCH
a
=======
x
>>>>>>> REPLACE

FILE: src/a.py
EDIT: second

<<<<<<< SEARCH
b
=======
y
>>>>>>> REPLACE
"""

    plan = plan_edit_text(
        tmp_path,
        text,
    )

    assert plan.files[0].after_bytes == b"x\ny\n"


def test_multi_file_plan_is_target_sorted(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/z.py",
        b"old_z()\n",
    )
    _write(
        tmp_path,
        "src/a.py",
        b"old_a()\n",
    )

    text = """EDIT_SPEC_VERSION: 1

FILE: src/z.py
EDIT: edit-z

<<<<<<< SEARCH
old_z()
=======
new_z()
>>>>>>> REPLACE

FILE: src/a.py
EDIT: edit-a

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE
"""

    plan = plan_edit_text(
        tmp_path,
        text,
    )

    assert [
        mutation.target
        for mutation in plan.files
    ] == [
        "src/a.py",
        "src/z.py",
    ]


def test_edit_order_does_not_change_file_result(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"a\nmiddle\nb\n",
    )

    first = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: edit-a

<<<<<<< SEARCH
a
=======
x
>>>>>>> REPLACE

FILE: src/a.py
EDIT: edit-b

<<<<<<< SEARCH
b
=======
y
>>>>>>> REPLACE
"""

    second = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: edit-b

<<<<<<< SEARCH
b
=======
y
>>>>>>> REPLACE

FILE: src/a.py
EDIT: edit-a

<<<<<<< SEARCH
a
=======
x
>>>>>>> REPLACE
"""

    first_plan = plan_edit_text(
        tmp_path,
        first,
    )
    second_plan = plan_edit_text(
        tmp_path,
        second,
    )

    assert (
        first_plan.files
        == second_plan.files
    )


@pytest.mark.parametrize(
    ("raw", "expected_style"),
    [
        (
            b"old()\nkeep()\n",
            NewlineStyle.LF,
        ),
        (
            b"old()\r\nkeep()\r\n",
            NewlineStyle.CRLF,
        ),
    ],
)
def test_newline_style_is_preserved(
    tmp_path: Path,
    raw: bytes,
    expected_style: NewlineStyle,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        raw,
    )

    plan = plan_edit_text(
        tmp_path,
        _spec(
            search="old()\n",
            replace="new()\n",
        ),
    )
    mutation = plan.files[0]

    assert (
        mutation.newline_style
        is expected_style
    )

    if expected_style is NewlineStyle.CRLF:
        assert mutation.after_bytes == (
            b"new()\r\nkeep()\r\n"
        )
    else:
        assert mutation.after_bytes == (
            b"new()\nkeep()\n"
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            b"old()\n",
            b"new()\n",
        ),
        (
            b"old()",
            b"new()",
        ),
    ],
)
def test_final_newline_state_is_preserved(
    tmp_path: Path,
    raw: bytes,
    expected: bytes,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        raw,
    )

    plan = plan_edit_text(
        tmp_path,
        _spec(
            search="old()\n",
            replace="new()\n",
        ),
    )

    assert (
        plan.files[0].after_bytes
        == expected
    )


def test_utf8_bom_is_preserved(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        codecs.BOM_UTF8 + b"old()\n",
    )

    plan = plan_edit_text(
        tmp_path,
        _spec(
            search="old()\n",
            replace="new()\n",
        ),
    )

    assert (
        plan.files[0].after_bytes
        == codecs.BOM_UTF8 + b"new()\n"
    )


def test_before_and_after_hashes_are_exact(
    tmp_path: Path,
) -> None:
    before = b"old()\n"
    after = b"new()\n"

    _write(
        tmp_path,
        "src/a.py",
        before,
    )

    plan = plan_edit_text(
        tmp_path,
        _spec(
            search="old()\n",
            replace="new()\n",
        ),
    )
    mutation = plan.files[0]

    assert mutation.before_sha256 == (
        hashlib.sha256(before).hexdigest()
    )
    assert mutation.after_sha256 == (
        hashlib.sha256(after).hexdigest()
    )


def test_input_fingerprint_uses_exact_spec_text(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"old()\n",
    )
    text = _spec(
        search="old()\n",
        replace="new()\n",
    )

    plan = plan_edit_text(
        tmp_path,
        text,
    )

    assert plan.input_fingerprint == (
        hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()
    )


def test_changed_range_uses_original_line_indexes(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"first\nold\nlast\n",
    )

    plan = plan_edit_text(
        tmp_path,
        _spec(
            search="old\n",
            replace="new\nextra\n",
        ),
    )
    changed = plan.files[0].changed_ranges[0]

    assert changed.edit_id == "edit-a"
    assert changed.start_line_index == 1
    assert changed.end_line_index == 2
    assert changed.replacement_line_count == 2


def test_individual_noop_is_warned_and_omitted(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"same()\nold()\n",
    )

    text = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: noop

<<<<<<< SEARCH
same()
=======
same()
>>>>>>> REPLACE

FILE: src/a.py
EDIT: change

<<<<<<< SEARCH
old()
=======
new()
>>>>>>> REPLACE
"""

    plan = plan_edit_text(
        tmp_path,
        text,
    )

    assert plan.files[0].edit_ids == (
        "change",
    )
    assert [
        warning.code
        for warning in plan.warnings
    ] == [
        "NO_CHANGE_EDIT",
    ]


def test_all_noop_edits_fail_with_no_change(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"same()\n",
    )

    _assert_error(
        "NO_CHANGE",
        lambda: plan_edit_text(
            tmp_path,
            _spec(
                search="same()\n",
                replace="same()\n",
            ),
        ),
    )


def test_planning_does_not_modify_target(
    tmp_path: Path,
) -> None:
    before = b"old()\n"
    target = tmp_path / "src/a.py"
    _write(
        tmp_path,
        "src/a.py",
        before,
    )

    plan_edit_text(
        tmp_path,
        _spec(
            search="old()\n",
            replace="new()\n",
        ),
    )

    assert target.read_bytes() == before


def test_single_line_no_newline_can_be_replaced(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"old()",
    )

    plan = plan_edit_text(
        tmp_path,
        _spec(
            search="old()\n",
            replace="new()\n",
        ),
    )

    assert plan.files[0].after_bytes == b"new()"


def test_multiline_result_without_established_newline_fails_closed(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"old()",
    )

    _assert_error(
        "UNSUPPORTED_NEWLINE",
        lambda: plan_edit_text(
            tmp_path,
            _spec(
                search="old()\n",
                replace="new()\nextra()\n",
            ),
        ),
    )


def test_revised_specification_is_fully_replanned(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"old_a()\n",
    )
    _write(
        tmp_path,
        "src/b.py",
        b"old_b()\n",
    )

    base = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: keep-a

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE

FILE: src/b.py
EDIT: revise-b

<<<<<<< SEARCH
old_b()
=======
new_b()
>>>>>>> REPLACE
"""

    revision = """REVISION_SPEC_VERSION: 1

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

    revised = revise_edit_specification(
        base,
        revision,
    )

    plan = plan_edit_text(
        tmp_path,
        revised.revised_text,
    )

    assert [
        mutation.after_bytes
        for mutation in plan.files
    ] == [
        b"new_a()\n",
        b"better_b()\n",
    ]


def test_keep_edit_is_rematched_after_revision(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"old_a()\n",
    )
    _write(
        tmp_path,
        "src/b.py",
        b"old_b()\n",
    )

    base = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: keep-a

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE

FILE: src/b.py
EDIT: revise-b

<<<<<<< SEARCH
old_b()
=======
new_b()
>>>>>>> REPLACE
"""

    revision = """REVISION_SPEC_VERSION: 1

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

    revised = revise_edit_specification(
        base,
        revision,
    )

    (tmp_path / "src/a.py").write_bytes(
        b"drifted_a()\n"
    )

    _assert_error(
        "SEARCH_ZERO_MATCH",
        lambda: plan_edit_text(
            tmp_path,
            revised.revised_text,
        ),
    )


def test_revision_changes_plan_fingerprint(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "src/a.py",
        b"old()\n",
    )

    base = _spec(
        search="old()\n",
        replace="new()\n",
    )
    original_plan = plan_edit_text(
        tmp_path,
        base,
    )

    revised = revise_edit_specification(
        base,
        """REVISION_SPEC_VERSION: 1

REVISE_EDIT: edit-a

<<<<<<< EDIT
FILE: src/a.py
EDIT: edit-a

<<<<<<< SEARCH
old()
=======
better()
>>>>>>> REPLACE
>>>>>>> EDIT
""",
    )
    revised_plan = plan_edit_text(
        tmp_path,
        revised.revised_text,
    )

    assert (
        original_plan.input_fingerprint
        != revised_plan.input_fingerprint
    )
