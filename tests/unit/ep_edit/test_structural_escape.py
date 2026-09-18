from __future__ import annotations

from ep_edit.edit_ref import (
    generate_edit_ref,
)
from ep_edit.revision import (
    revise_edit_specification,
)
from ep_edit.specification import (
    parse_edit_specification,
)
from ep_edit.structural_escape import (
    CONTENT_PAYLOAD_MARKERS,
    REPLACE_PAYLOAD_MARKERS,
    REVISION_EDIT_PAYLOAD_MARKERS,
    SEARCH_PAYLOAD_MARKERS,
    decode_structural_payload_line,
    encode_structural_payload_line,
)


_SEARCH_OPEN = "<" * 7 + " SEARCH"
_SEPARATOR = "=" * 7
_REPLACE_CLOSE = ">" * 7 + " REPLACE"
_CONTENT_OPEN = "<" * 7 + " CONTENT"
_CONTENT_CLOSE = ">" * 7 + " CONTENT"
_EDIT_OPEN = "<" * 7 + " EDIT"
_EDIT_CLOSE = ">" * 7 + " EDIT"


def test_structural_escape_round_trips_marker_prefix_depth() -> None:
    marker_sets = (
        SEARCH_PAYLOAD_MARKERS,
        REPLACE_PAYLOAD_MARKERS,
        CONTENT_PAYLOAD_MARKERS,
        REVISION_EDIT_PAYLOAD_MARKERS,
    )

    for markers in marker_sets:
        for marker in markers:
            for prefix_depth in range(
                3
            ):
                semantic = (
                    "\\"
                    * prefix_depth
                    + marker
                )
                encoded = (
                    encode_structural_payload_line(
                        semantic,
                        markers=markers,
                    )
                )

                assert encoded == (
                    "\\"
                    + semantic
                )
                assert (
                    decode_structural_payload_line(
                        encoded,
                        markers=markers,
                    )
                    == semantic
                )


def test_structural_escape_leaves_ordinary_backslashes_unchanged() -> None:
    value = "\\ordinary-text"

    assert (
        encode_structural_payload_line(
            value,
            markers=REPLACE_PAYLOAD_MARKERS,
        )
        == value
    )
    assert (
        decode_structural_payload_line(
            value,
            markers=REPLACE_PAYLOAD_MARKERS,
        )
        == value
    )


def test_v1_search_replace_decodes_reserved_lines() -> None:
    specification = (
        "EDIT_SPEC_VERSION: 1\n\n"
        "FILE: example.txt\n\n"
        "EDIT: escape-v1\n\n"
        f"{_SEARCH_OPEN}\n"
        f"\\{_SEPARATOR}\n"
        f"\\\\{_REPLACE_CLOSE}\n"
        f"{_SEPARATOR}\n"
        f"\\{_REPLACE_CLOSE}\n"
        f"{_REPLACE_CLOSE}\n"
    )

    parsed = parse_edit_specification(
        specification
    )
    edit = parsed.edits[0]

    assert edit.search_lines == (
        _SEPARATOR,
        "\\" + _REPLACE_CLOSE,
    )
    assert edit.replace_lines == (
        _REPLACE_CLOSE,
    )


def test_v1_content_decodes_reserved_lines() -> None:
    specification = (
        "EDIT_SPEC_VERSION: 1\n\n"
        "FILE: example.txt\n\n"
        "EDIT: content-v1\n\n"
        "MODE: CREATE\n\n"
        f"{_CONTENT_OPEN}\n"
        f"\\{_CONTENT_CLOSE}\n"
        f"\\\\{_CONTENT_CLOSE}\n"
        f"{_CONTENT_CLOSE}\n"
    )

    parsed = parse_edit_specification(
        specification
    )
    edit = parsed.edits[0]

    assert edit.content_lines == (
        _CONTENT_CLOSE,
        "\\" + _CONTENT_CLOSE,
    )


def test_v2_search_replace_ref_uses_decoded_semantics() -> None:
    specification = (
        "EDIT_SPEC_VERSION: 2\n\n"
        "FILE: example.txt\n"
        "LABEL: escaped v2 search\n\n"
        f"{_SEARCH_OPEN}\n"
        f"\\{_SEPARATOR}\n"
        f"\\{_REPLACE_CLOSE}\n"
        f"{_SEPARATOR}\n"
        f"\\{_REPLACE_CLOSE}\n"
        f"{_REPLACE_CLOSE}\n"
    )

    parsed = parse_edit_specification(
        specification
    )
    edit = parsed.edits[0]

    assert edit.search_lines == (
        _SEPARATOR,
        _REPLACE_CLOSE,
    )
    assert edit.replace_lines == (
        _REPLACE_CLOSE,
    )

    assert edit.edit_id == (
        generate_edit_ref(
            target="example.txt",
            operation="SEARCH_REPLACE",
            search_lines=(
                _SEPARATOR,
                _REPLACE_CLOSE,
            ),
            replace_lines=(
                _REPLACE_CLOSE,
            ),
        )
    )


def test_v2_content_ref_uses_decoded_semantics() -> None:
    specification = (
        "EDIT_SPEC_VERSION: 2\n\n"
        "FILE: example.txt\n"
        "LABEL: escaped v2 content\n"
        "MODE: CREATE\n\n"
        f"{_CONTENT_OPEN}\n"
        f"\\{_CONTENT_CLOSE}\n"
        f"{_CONTENT_CLOSE}\n"
    )

    parsed = parse_edit_specification(
        specification
    )
    edit = parsed.edits[0]

    assert edit.content_lines == (
        _CONTENT_CLOSE,
    )

    assert edit.edit_id == (
        generate_edit_ref(
            target="example.txt",
            operation="CREATE",
            content_lines=(
                _CONTENT_CLOSE,
            ),
            newline="LF",
            final_newline="YES",
            bom="NO",
        )
    )


def test_revision_v1_outer_escape_and_base_locator_round_trip() -> None:
    base = (
        "EDIT_SPEC_VERSION: 1\n\n"
        "FILE: example.txt\n\n"
        "EDIT: revise-v1\n\n"
        f"{_SEARCH_OPEN}\n"
        "old()\n"
        f"{_SEPARATOR}\n"
        f"\\{_REPLACE_CLOSE}\n"
        f"{_REPLACE_CLOSE}\n"
    )

    result = revise_edit_specification(
        base,
        (
            "REVISION_SPEC_VERSION: 1\n\n"
            "REVISE_EDIT: revise-v1\n\n"
            f"{_EDIT_OPEN}\n"
            "FILE: example.txt\n\n"
            "EDIT: revise-v1\n\n"
            f"{_SEARCH_OPEN}\n"
            "old()\n"
            f"{_SEPARATOR}\n"
            f"\\{_EDIT_CLOSE}\n"
            f"{_REPLACE_CLOSE}\n"
            f"{_EDIT_CLOSE}\n"
        ),
    )

    revised = parse_edit_specification(
        result.revised_text
    )

    assert revised.edits[0].replace_lines == (
        _EDIT_CLOSE,
    )


def test_revision_v2_nested_escape_uses_semantic_ref() -> None:
    base = (
        "EDIT_SPEC_VERSION: 2\n\n"
        "FILE: example.txt\n"
        "LABEL: base escaped marker\n\n"
        f"{_SEARCH_OPEN}\n"
        "old()\n"
        f"{_SEPARATOR}\n"
        f"\\{_REPLACE_CLOSE}\n"
        f"{_REPLACE_CLOSE}\n"
    )

    base_parsed = parse_edit_specification(
        base
    )
    old_ref = (
        base_parsed.edits[0].edit_id
    )

    result = revise_edit_specification(
        base,
        (
            "REVISION_SPEC_VERSION: 2\n\n"
            f"REVISE_EDIT: {old_ref}\n\n"
            f"{_EDIT_OPEN}\n"
            "FILE: example.txt\n"
            "LABEL: nested escapes\n\n"
            f"{_SEARCH_OPEN}\n"
            "old()\n"
            f"{_SEPARATOR}\n"
            f"\\{_REPLACE_CLOSE}\n"
            f"\\{_EDIT_CLOSE}\n"
            f"{_REPLACE_CLOSE}\n"
            f"{_EDIT_CLOSE}\n"
        ),
    )

    revised = parse_edit_specification(
        result.revised_text
    )
    revised_edit = revised.edits[0]

    assert revised_edit.replace_lines == (
        _REPLACE_CLOSE,
        _EDIT_CLOSE,
    )

    expected_ref = generate_edit_ref(
        target="example.txt",
        operation="SEARCH_REPLACE",
        search_lines=(
            "old()",
        ),
        replace_lines=(
            _REPLACE_CLOSE,
            _EDIT_CLOSE,
        ),
    )

    assert revised_edit.edit_id == (
        expected_ref
    )
    assert (
        result.revised_edit_ref_mappings
        == (
            (
                old_ref,
                expected_ref,
            ),
        )
    )
