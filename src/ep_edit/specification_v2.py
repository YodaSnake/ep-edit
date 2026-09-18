from __future__ import annotations

from ep_edit.edit_ref import generate_edit_ref
from ep_edit.errors import DeterministicEditError
from ep_edit.structural_escape import (
    CONTENT_PAYLOAD_MARKERS,
    REPLACE_PAYLOAD_MARKERS,
    SEARCH_PAYLOAD_MARKERS,
    decode_structural_payload_line,
)
from ep_edit.specification import (
    BomDirective,
    EditSpecification,
    FinalNewlineDirective,
    NewlineDirective,
    SearchReplaceEdit,
    WholeFileEdit,
    WholeFileMode,
    _skip_blank_lines,
    _split_spec_lines,
    _validate_target_operation_mix,
    _validate_whole_file_directives,
    normalize_target_path,
)


EDIT_SPEC_VERSION_V2 = 2


def parse_v2_edit_specification(
    text: str,
) -> EditSpecification:
    lines = _split_spec_lines(
        text
    )
    index = _skip_blank_lines(
        lines,
        0,
    )

    if (
        index >= len(lines)
        or lines[index]
        != "EDIT_SPEC_VERSION: 2"
    ):
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                "Edit Specification v2 requires "
                "EDIT_SPEC_VERSION: 2"
            ),
        )

    index += 1
    edits: list[
        SearchReplaceEdit | WholeFileEdit
    ] = []
    edit_refs: set[str] = set()

    while True:
        index = _skip_blank_lines(
            lines,
            index,
        )

        if index >= len(lines):
            break

        file_line = lines[index]

        if not file_line.startswith(
            "FILE:"
        ):
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    "expected FILE at "
                    f"line {index + 1}"
                ),
            )

        target = normalize_target_path(
            file_line.partition(
                ":"
            )[2].strip()
        )

        index += 1
        index = _skip_blank_lines(
            lines,
            index,
        )

        label: str | None = None

        if (
            index < len(lines)
            and lines[index].startswith(
                "LABEL:"
            )
        ):
            label = (
                lines[index]
                .partition(":")[2]
                .strip()
            )

            if not label:
                raise DeterministicEditError(
                    "INPUT_PARSE_ERROR",
                    (
                        f"FILE {target!r} has "
                        "an empty LABEL"
                    ),
                )

            if "\x00" in label:
                raise DeterministicEditError(
                    "UNSUPPORTED_ENCODING",
                    (
                        f"FILE {target!r} LABEL "
                        "must not contain NUL"
                    ),
                )

            index += 1
            index = _skip_blank_lines(
                lines,
                index,
            )

        if (
            index < len(lines)
            and lines[index].startswith(
                "EDIT:"
            )
        ):
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    "EDIT is not allowed in "
                    "Edit Specification v2; "
                    "EditRef is generated "
                    "deterministically"
                ),
            )

        if (
            index < len(lines)
            and lines[index].startswith(
                "MODE:"
            )
        ):
            edit, index = (
                _parse_whole_file_edit(
                    lines,
                    index,
                    target=target,
                    label=label,
                )
            )
        else:
            edit, index = (
                _parse_search_replace_edit(
                    lines,
                    index,
                    target=target,
                    label=label,
                )
            )

        if edit.edit_id in edit_refs:
            raise DeterministicEditError(
                "DUPLICATE_EDIT_REF",
                (
                    "Edit Specification v2 "
                    "contains duplicate "
                    f"generated EditRef {edit.edit_id!r}"
                ),
            )

        edit_refs.add(
            edit.edit_id
        )
        edits.append(
            edit
        )

    if not edits:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                "edit specification must "
                "contain at least one edit"
            ),
        )

    _validate_target_operation_mix(
        edits
    )

    return EditSpecification(
        version=EDIT_SPEC_VERSION_V2,
        edits=tuple(
            edits
        ),
    )


def _parse_search_replace_edit(
    lines: list[str],
    index: int,
    *,
    target: str,
    label: str | None,
) -> tuple[SearchReplaceEdit, int]:
    if (
        index >= len(lines)
        or lines[index]
        != "<<<<<<< SEARCH"
    ):
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"FILE {target!r} must contain "
                "<<<<<<< SEARCH or MODE"
            ),
        )

    index += 1
    search_lines: list[str] = []

    while (
        index < len(lines)
        and lines[index] != "======="
    ):
        if (
            lines[index]
            == ">>>>>>> REPLACE"
        ):
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    f"FILE {target!r} SEARCH "
                    "is missing ======="
                ),
            )

        search_lines.append(
            decode_structural_payload_line(
                lines[index],
                markers=SEARCH_PAYLOAD_MARKERS,
            )
        )
        index += 1

    if index >= len(lines):
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"FILE {target!r} SEARCH "
                "is missing ======="
            ),
        )

    if not search_lines:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"FILE {target!r} SEARCH "
                "must not be empty"
            ),
        )

    index += 1
    replace_lines: list[str] = []

    while (
        index < len(lines)
        and lines[index]
        != ">>>>>>> REPLACE"
    ):
        replace_lines.append(
            decode_structural_payload_line(
                lines[index],
                markers=REPLACE_PAYLOAD_MARKERS,
            )
        )
        index += 1

    if index >= len(lines):
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"FILE {target!r} SEARCH "
                "is missing >>>>>>> REPLACE"
            ),
        )

    index += 1

    edit_ref = generate_edit_ref(
        target=target,
        operation="SEARCH_REPLACE",
        search_lines=search_lines,
        replace_lines=replace_lines,
    )

    return (
        SearchReplaceEdit(
            target=target,
            edit_id=edit_ref,
            search_lines=tuple(
                search_lines
            ),
            replace_lines=tuple(
                replace_lines
            ),
            label=label,
        ),
        index,
    )


def _parse_whole_file_edit(
    lines: list[str],
    index: int,
    *,
    target: str,
    label: str | None,
) -> tuple[WholeFileEdit, int]:
    raw_mode = (
        lines[index]
        .partition(":")[2]
        .strip()
    )

    try:
        mode = WholeFileMode(
            raw_mode
        )
    except ValueError as exc:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"FILE {target!r} has "
                f"unsupported MODE: {raw_mode}"
            ),
        ) from exc

    index += 1

    if mode is WholeFileMode.DELETE:
        next_index = _skip_blank_lines(
            lines,
            index,
        )

        if (
            next_index < len(lines)
            and not lines[
                next_index
            ].startswith(
                "FILE:"
            )
        ):
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    f"DELETE for FILE {target!r} "
                    "must not contain representation "
                    "directives or CONTENT"
                ),
            )

        edit_ref = generate_edit_ref(
            target=target,
            operation=mode.value,
        )

        return (
            WholeFileEdit(
                target=target,
                edit_id=edit_ref,
                mode=mode,
                content_lines=None,
                newline=None,
                final_newline=None,
                bom=None,
                label=label,
            ),
            index,
        )

    if mode is WholeFileMode.CREATE:
        newline = NewlineDirective.LF
        final_newline = (
            FinalNewlineDirective.YES
        )
        bom = BomDirective.NO
    else:
        newline = (
            NewlineDirective.PRESERVE
        )
        final_newline = (
            FinalNewlineDirective.PRESERVE
        )
        bom = BomDirective.PRESERVE

    seen_directives: set[str] = set()

    while True:
        index = _skip_blank_lines(
            lines,
            index,
        )

        if index >= len(lines):
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    f"FILE {target!r} is missing "
                    "<<<<<<< CONTENT"
                ),
            )

        line = lines[index]

        if line == "<<<<<<< CONTENT":
            break

        if line.startswith(
            "NEWLINE:"
        ):
            _require_new_directive(
                seen_directives,
                "NEWLINE",
                target=target,
            )
            newline = _parse_newline(
                line,
                target=target,
            )

        elif line.startswith(
            "FINAL_NEWLINE:"
        ):
            _require_new_directive(
                seen_directives,
                "FINAL_NEWLINE",
                target=target,
            )
            final_newline = (
                _parse_final_newline(
                    line,
                    target=target,
                )
            )

        elif line.startswith(
            "BOM:"
        ):
            _require_new_directive(
                seen_directives,
                "BOM",
                target=target,
            )
            bom = _parse_bom(
                line,
                target=target,
            )

        else:
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    f"FILE {target!r} expected "
                    "NEWLINE, FINAL_NEWLINE, BOM, "
                    "or <<<<<<< CONTENT at "
                    f"line {index + 1}"
                ),
            )

        index += 1

    index += 1
    content_lines: list[str] = []

    while (
        index < len(lines)
        and lines[index]
        != ">>>>>>> CONTENT"
    ):
        if "\x00" in lines[index]:
            raise DeterministicEditError(
                "UNSUPPORTED_ENCODING",
                (
                    f"FILE {target!r} CONTENT "
                    "must not contain NUL"
                ),
            )

        content_lines.append(
            decode_structural_payload_line(
                lines[index],
                markers=CONTENT_PAYLOAD_MARKERS,
            )
        )
        index += 1

    if index >= len(lines):
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"FILE {target!r} is missing "
                ">>>>>>> CONTENT"
            ),
        )

    index += 1

    edit_ref = generate_edit_ref(
        target=target,
        operation=mode.value,
        content_lines=content_lines,
        newline=newline.value,
        final_newline=(
            final_newline.value
        ),
        bom=bom.value,
    )

    _validate_whole_file_directives(
        mode,
        newline=newline,
        final_newline=final_newline,
        bom=bom,
        edit_id=edit_ref,
    )

    return (
        WholeFileEdit(
            target=target,
            edit_id=edit_ref,
            mode=mode,
            content_lines=tuple(
                content_lines
            ),
            newline=newline,
            final_newline=final_newline,
            bom=bom,
            label=label,
        ),
        index,
    )


def _require_new_directive(
    seen: set[str],
    name: str,
    *,
    target: str,
) -> None:
    if name in seen:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"FILE {target!r} contains "
                f"duplicate {name} directive"
            ),
        )

    seen.add(
        name
    )


def _parse_newline(
    line: str,
    *,
    target: str,
) -> NewlineDirective:
    raw = (
        line.partition(":")[2]
        .strip()
    )

    try:
        return NewlineDirective(
            raw
        )
    except ValueError as exc:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"FILE {target!r} has "
                f"unsupported NEWLINE: {raw}"
            ),
        ) from exc


def _parse_final_newline(
    line: str,
    *,
    target: str,
) -> FinalNewlineDirective:
    raw = (
        line.partition(":")[2]
        .strip()
    )

    try:
        return FinalNewlineDirective(
            raw
        )
    except ValueError as exc:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"FILE {target!r} has "
                "unsupported FINAL_NEWLINE: "
                f"{raw}"
            ),
        ) from exc


def _parse_bom(
    line: str,
    *,
    target: str,
) -> BomDirective:
    raw = (
        line.partition(":")[2]
        .strip()
    )

    try:
        return BomDirective(
            raw
        )
    except ValueError as exc:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"FILE {target!r} has "
                f"unsupported BOM: {raw}"
            ),
        ) from exc
