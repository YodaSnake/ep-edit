from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

from ep_edit.edit_ref import generate_edit_ref
from ep_edit.errors import DeterministicEditError
from ep_edit.structural_escape import (
    CONTENT_PAYLOAD_MARKERS,
    REPLACE_PAYLOAD_MARKERS,
    SEARCH_PAYLOAD_MARKERS,
    decode_structural_payload_line,
)


@dataclass(frozen=True)
class SearchReplaceEdit:
    target: str
    edit_ref: str
    search_lines: tuple[str, ...]
    replace_lines: tuple[str, ...]
    label: str | None = None


class WholeFileMode(str, Enum):
    CREATE = "CREATE"
    REPLACE_FILE = "REPLACE_FILE"
    DELETE = "DELETE"


class NewlineDirective(str, Enum):
    LF = "LF"
    CRLF = "CRLF"
    PRESERVE = "PRESERVE"


class FinalNewlineDirective(str, Enum):
    YES = "YES"
    NO = "NO"
    PRESERVE = "PRESERVE"


class BomDirective(str, Enum):
    YES = "YES"
    NO = "NO"
    PRESERVE = "PRESERVE"


@dataclass(frozen=True)
class WholeFileEdit:
    target: str
    edit_ref: str
    mode: WholeFileMode
    content_lines: tuple[str, ...] | None
    newline: NewlineDirective | None
    final_newline: FinalNewlineDirective | None
    bom: BomDirective | None
    label: str | None = None


EditOperation = SearchReplaceEdit | WholeFileEdit


@dataclass(frozen=True)
class EditSpecification:
    edits: tuple[EditOperation, ...]


def normalize_target_path(
    value: str,
) -> str:
    if not value:
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "target path must not be empty",
        )

    if "\x00" in value:
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "target path must not contain NUL",
        )

    if "\\" in value:
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "target path must use POSIX separators",
        )

    path = PurePosixPath(
        value
    )

    if path.is_absolute():
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "target path must be root-relative",
        )

    if (
        not path.parts
        or any(
            part in {
                "",
                ".",
                "..",
            }
            for part in path.parts
        )
    ):
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "target path must not contain empty, dot, or parent components",
        )

    canonical = path.as_posix()

    if canonical != value:
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "target path must use canonical POSIX form",
        )

    return canonical


def parse_edit_specification(
    text: str,
) -> EditSpecification:
    lines = _split_spec_lines(
        text
    )
    index = _skip_blank_lines(
        lines,
        0,
    )

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
                    "EDIT is not allowed; "
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

        if edit.edit_ref in edit_refs:
            raise DeterministicEditError(
                "DUPLICATE_EDIT_REF",
                (
                    "Edit Specification "
                    "contains duplicate "
                    f"generated EditRef {edit.edit_ref!r}"
                ),
            )

        edit_refs.add(
            edit.edit_ref
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
            edit_ref=edit_ref,
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
                edit_ref=edit_ref,
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
        edit_ref=edit_ref,
    )

    return (
        WholeFileEdit(
            target=target,
            edit_ref=edit_ref,
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


def _validate_whole_file_directives(
    mode: WholeFileMode,
    *,
    newline: NewlineDirective,
    final_newline: FinalNewlineDirective,
    bom: BomDirective,
    edit_ref: str,
) -> None:
    if mode is not WholeFileMode.CREATE:
        return

    if newline is NewlineDirective.PRESERVE:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"CREATE EDIT {edit_ref!r} cannot use "
                "NEWLINE: PRESERVE"
            ),
        )

    if final_newline is FinalNewlineDirective.PRESERVE:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"CREATE EDIT {edit_ref!r} cannot use "
                "FINAL_NEWLINE: PRESERVE"
            ),
        )

    if bom is BomDirective.PRESERVE:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"CREATE EDIT {edit_ref!r} cannot use "
                "BOM: PRESERVE"
            ),
        )


def _validate_target_operation_mix(
    edits: list[EditOperation],
) -> None:
    edits_by_target: dict[
        str,
        list[EditOperation],
    ] = {}

    for edit in edits:
        edits_by_target.setdefault(
            edit.target,
            [],
        ).append(edit)

    for target, target_edits in (
        edits_by_target.items()
    ):
        if (
            len(target_edits) > 1
            and any(
                isinstance(
                    edit,
                    WholeFileEdit,
                )
                for edit in target_edits
            )
        ):
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    "whole-file operation must be "
                    "the sole edit for target "
                    f"{target!r}"
                ),
            )


def _split_spec_lines(
    text: str,
) -> list[str]:
    normalized = text.replace(
        "\r\n",
        "\n",
    )

    if "\r" in normalized:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                "edit specification contains "
                "unsupported lone CR"
            ),
        )

    return normalized.splitlines()


def _skip_blank_lines(
    lines: list[str],
    index: int,
) -> int:
    while (
        index < len(lines)
        and lines[index] == ""
    ):
        index += 1

    return index
