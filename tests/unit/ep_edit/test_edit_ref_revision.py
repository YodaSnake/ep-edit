from __future__ import annotations

import pytest

from ep_edit.edit_ref import (
    is_generated_edit_ref,
)
from ep_edit.errors import DeterministicEditError
from ep_edit.revision import (
    parse_revision_specification,
    revise_edit_specification,
)
from ep_edit.specification import (
    parse_edit_specification,
)


pytestmark = pytest.mark.unit


_EDIT_OPEN = "<" * 7 + " EDIT"
_EDIT_CLOSE = ">" * 7 + " EDIT"
_SEARCH_OPEN = "<" * 7 + " SEARCH"
_REPLACE_SEPARATOR = "=" * 7
_REPLACE_CLOSE = ">" * 7 + " REPLACE"


BASE_SPEC = f"""

FILE: src/a.py
LABEL: original a

{_SEARCH_OPEN}
old_a()
{_REPLACE_SEPARATOR}
new_a()
{_REPLACE_CLOSE}

FILE: src/b.py

{_SEARCH_OPEN}
old_b()
{_REPLACE_SEPARATOR}
new_b()
{_REPLACE_CLOSE}
"""


def _base_refs() -> tuple[str, str]:
    specification = (
        parse_edit_specification(
            BASE_SPEC
        )
    )

    return (
        specification.edits[0].edit_ref,
        specification.edits[1].edit_ref,
    )


def test_base_refs_use_shared_edit_ref_contract() -> None:
    assert all(
        is_generated_edit_ref(
            edit_ref
        )
        for edit_ref in _base_refs()
    )


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


def test_revise_maps_old_ref_to_new_ref() -> None:
    old_ref, _ = _base_refs()

    result = revise_edit_specification(
        BASE_SPEC,
        f"""
REVISE_EDIT: {old_ref}

{_EDIT_OPEN}
FILE: src/a.py
LABEL: revised a

{_SEARCH_OPEN}
old_a()
{_REPLACE_SEPARATOR}
better_a()
{_REPLACE_CLOSE}
{_EDIT_CLOSE}
""",
    )

    revised = (
        parse_edit_specification(
            result.revised_text
        )
    )
    new_ref = (
        revised.edits[0].edit_ref
    )

    assert new_ref != old_ref
    assert (
        result.revised_edit_refs
        == (old_ref,)
    )
    assert (
        result.revised_edit_ref_mappings
        == (
            (
                old_ref,
                new_ref,
            ),
        )
    )
    assert "EDIT:" not in (
        result.revised_text
    )


def test_revision_preserves_url_uri_literals() -> None:
    base_spec = (

        "FILE: src/link.txt\n"
        "LABEL: original URL literal\n\n"
        f"{_SEARCH_OPEN}\n"
        'url = "http://example.invalid/a:b'
        '?x=1&y=2#old"\n'
        f"{_REPLACE_SEPARATOR}\n"
        'url = "https://example.invalid/a:b'
        '?x=1&y=2#first"\n'
        'identity = "urn:test:a6-url-compat"\n'
        f"{_REPLACE_CLOSE}\n"
    )

    old_ref = (
        parse_edit_specification(
            base_spec
        )
        .edits[0]
        .edit_ref
    )

    result = revise_edit_specification(
        base_spec,
        (
            f"REVISE_EDIT: {old_ref}\n\n"
            f"{_EDIT_OPEN}\n"
            "FILE: src/link.txt\n"
            "LABEL: revised URL literal\n\n"
            f"{_SEARCH_OPEN}\n"
            'url = "http://example.invalid/a:b'
            '?x=1&y=2#old"\n'
            f"{_REPLACE_SEPARATOR}\n"
            'url = "https://example.invalid/a:b'
            '?x=1&y=2#revised"\n'
            'identity = "urn:test:a6-url-compat"\n'
            f"{_REPLACE_CLOSE}\n"
            f"{_EDIT_CLOSE}\n"
        ),
    )

    revised = parse_edit_specification(
        result.revised_text
    )
    new_ref = revised.edits[0].edit_ref

    assert new_ref != old_ref
    assert (
        result.revised_edit_ref_mappings
        == (
            (
                old_ref,
                new_ref,
            ),
        )
    )
    assert (
        "https://example.invalid/a:b"
        "?x=1&y=2#revised"
        in result.revised_text
    )
    assert (
        "urn:test:a6-url-compat"
        in result.revised_text
    )


def test_label_only_revision_keeps_ref() -> None:
    old_ref, _ = _base_refs()

    result = revise_edit_specification(
        BASE_SPEC,
        f"""
REVISE_EDIT: {old_ref}

{_EDIT_OPEN}
FILE: src/a.py
LABEL: changed label only

{_SEARCH_OPEN}
old_a()
{_REPLACE_SEPARATOR}
new_a()
{_REPLACE_CLOSE}
{_EDIT_CLOSE}
""",
    )

    assert (
        result.revised_edit_ref_mappings
        == (
            (
                old_ref,
                old_ref,
            ),
        )
    )
    assert (
        "LABEL: changed label only"
        in result.revised_text
    )


def test_remove_uses_ref_selector() -> None:
    _, remove_ref = _base_refs()

    result = revise_edit_specification(
        BASE_SPEC,
        f"""
REMOVE_EDIT: {remove_ref}
""",
    )

    revised = (
        parse_edit_specification(
            result.revised_text
        )
    )

    assert len(
        revised.edits
    ) == 1
    assert (
        result.removed_edit_refs
        == (remove_ref,)
    )


def test_add_derives_identity_from_block() -> None:
    result = revise_edit_specification(
        BASE_SPEC,
        f"""
ADD_EDIT:

{_EDIT_OPEN}
FILE: src/c.py

{_SEARCH_OPEN}
old_c()
{_REPLACE_SEPARATOR}
new_c()
{_REPLACE_CLOSE}
{_EDIT_CLOSE}
""",
    )

    revised = (
        parse_edit_specification(
            result.revised_text
        )
    )

    assert len(
        revised.edits
    ) == 3
    assert len(
        result.added_edit_refs
    ) == 1
    assert (
        result.added_edit_refs[0]
        == revised.edits[2].edit_ref
    )


def test_revision_may_change_target() -> None:
    old_ref, _ = _base_refs()

    result = revise_edit_specification(
        BASE_SPEC,
        f"""
REVISE_EDIT: {old_ref}

{_EDIT_OPEN}
FILE: src/renamed.py

{_SEARCH_OPEN}
old_a()
{_REPLACE_SEPARATOR}
new_a()
{_REPLACE_CLOSE}
{_EDIT_CLOSE}
""",
    )

    revised = (
        parse_edit_specification(
            result.revised_text
        )
    )

    assert (
        revised.edits[0].target
        == "src/renamed.py"
    )
    assert (
        result.revised_edit_ref_mappings[0][0]
        == old_ref
    )
    assert (
        result.revised_edit_ref_mappings[0][1]
        == revised.edits[0].edit_ref
    )



def test_duplicate_selector_fails_closed() -> None:
    old_ref, _ = _base_refs()

    _assert_error(
        "REVISION_DUPLICATE_TARGET",
        lambda: parse_revision_specification(
            f"""
REMOVE_EDIT: {old_ref}

REMOVE_EDIT: {old_ref}
"""
        ),
    )


def test_invalid_selector_format_fails_closed() -> None:
    _assert_error(
        "REVISION_PARSE_ERROR",
        lambda: parse_revision_specification(
            f"""
REMOVE_EDIT: user-authored-name
"""
        ),
    )


def test_add_rejects_authored_identifier() -> None:
    _assert_error(
        "REVISION_PARSE_ERROR",
        lambda: parse_revision_specification(
            f"""
ADD_EDIT: authored-name

{_EDIT_OPEN}
FILE: src/c.py

{_SEARCH_OPEN}
old_c()
{_REPLACE_SEPARATOR}
new_c()
{_REPLACE_CLOSE}
{_EDIT_CLOSE}
"""
        ),
    )


def test_whole_file_block_uses_common_locator() -> None:
    base = f"""

FILE: src/keep.py

{_SEARCH_OPEN}
old()
{_REPLACE_SEPARATOR}
new()
{_REPLACE_CLOSE}

FILE: obsolete.txt
MODE: DELETE
"""

    specification = (
        parse_edit_specification(
            base
        )
    )
    delete_ref = (
        specification.edits[1].edit_ref
    )

    result = revise_edit_specification(
        base,
        f"""
REMOVE_EDIT: {delete_ref}
""",
    )

    revised = (
        parse_edit_specification(
            result.revised_text
        )
    )

    assert len(
        revised.edits
    ) == 1
    assert (
        revised.edits[0].target
        == "src/keep.py"
    )
