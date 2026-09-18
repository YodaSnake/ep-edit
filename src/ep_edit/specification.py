from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

from ep_edit.errors import DeterministicEditError
from ep_edit.structural_escape import (
    CONTENT_PAYLOAD_MARKERS,
    REPLACE_PAYLOAD_MARKERS,
    SEARCH_PAYLOAD_MARKERS,
    decode_structural_payload_line,
)


EDIT_SPEC_VERSION = 1
EDIT_SPEC_VERSION_V2 = 2


@dataclass(frozen=True)
class SearchReplaceEdit:
    target: str
    edit_id: str
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
    edit_id: str
    mode: WholeFileMode
    content_lines: tuple[str, ...] | None
    newline: NewlineDirective | None
    final_newline: FinalNewlineDirective | None
    bom: BomDirective | None
    label: str | None = None


EditOperation = SearchReplaceEdit | WholeFileEdit


@dataclass(frozen=True)
class EditSpecification:
    version: int
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
    version = EDIT_SPEC_VERSION

    if (
        index < len(lines)
        and lines[index].startswith(
            "EDIT_SPEC_VERSION:"
        )
    ):
        raw_version = (
            lines[index]
            .partition(":")[2]
            .strip()
        )

        try:
            version = int(
                raw_version
            )
        except ValueError as exc:
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                "EDIT_SPEC_VERSION must be an integer",
            ) from exc

        if version == EDIT_SPEC_VERSION_V2:
            from ep_edit.specification_v2 import (
                parse_v2_edit_specification,
            )

            return parse_v2_edit_specification(
                text
            )

        if version != EDIT_SPEC_VERSION:
            raise DeterministicEditError(
                "UNSUPPORTED_SPEC_VERSION",
                (
                    "unsupported "
                    f"EDIT_SPEC_VERSION: {version}"
                ),
            )

        index += 1

    edits: list[EditOperation] = []
    edit_ids: set[str] = set()

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
            file_line.partition(":")[2].strip()
        )

        index += 1
        index = _skip_blank_lines(lines, index)

        if (
            index >= len(lines)
            or not lines[index].startswith("EDIT:")
        ):
            raise DeterministicEditError(
                "MISSING_EDIT_ID",
                f"FILE {target!r} must be followed by EDIT",
            )

        edit_id = lines[index].partition(":")[2].strip()

        if not edit_id:
            raise DeterministicEditError(
                "MISSING_EDIT_ID",
                f"FILE {target!r} has an empty EDIT id",
            )

        if edit_id in edit_ids:
            raise DeterministicEditError(
                "DUPLICATE_EDIT_ID",
                f"duplicate EDIT id: {edit_id}",
            )

        edit_ids.add(edit_id)

        index += 1
        index = _skip_blank_lines(lines, index)

        if (
            index < len(lines)
            and lines[index].startswith("MODE:")
        ):
            whole_file_edit, index = _parse_whole_file_edit(
                lines,
                index,
                target=target,
                edit_id=edit_id,
            )
            edits.append(
                whole_file_edit
            )
            continue

        if (
            index >= len(lines)
            or lines[index] != "<<<<<<< SEARCH"
        ):
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                f"EDIT {edit_id!r} must contain <<<<<<< SEARCH",
            )

        index += 1
        search_lines: list[str] = []

        while (
            index < len(lines)
            and lines[index] != "======="
        ):
            if lines[index] == ">>>>>>> REPLACE":
                raise DeterministicEditError(
                    "INPUT_PARSE_ERROR",
                    f"EDIT {edit_id!r} is missing =======",
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
                f"EDIT {edit_id!r} is missing =======",
            )

        if not search_lines:
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                f"EDIT {edit_id!r} SEARCH must not be empty",
            )

        index += 1
        replace_lines: list[str] = []

        while (
            index < len(lines)
            and lines[index] != ">>>>>>> REPLACE"
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
                f"EDIT {edit_id!r} is missing >>>>>>> REPLACE",
            )

        index += 1

        edits.append(
            SearchReplaceEdit(
                target=target,
                edit_id=edit_id,
                search_lines=tuple(search_lines),
                replace_lines=tuple(replace_lines),
            )
        )

    if not edits:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            "edit specification must contain at least one edit",
        )

    _validate_target_operation_mix(
        edits
    )

    return EditSpecification(
        version=version,
        edits=tuple(edits),
    )


def _parse_whole_file_edit(
    lines: list[str],
    index: int,
    *,
    target: str,
    edit_id: str,
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
                f"EDIT {edit_id!r} has unsupported "
                f"MODE: {raw_mode}"
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
            and not lines[next_index].startswith("FILE:")
        ):
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    f"DELETE EDIT {edit_id!r} must not contain "
                    "representation directives or CONTENT"
                ),
            )

        return (
            WholeFileEdit(
                target=target,
                edit_id=edit_id,
                mode=mode,
                content_lines=None,
                newline=None,
                final_newline=None,
                bom=None,
            ),
            index,
        )

    if mode is WholeFileMode.CREATE:
        newline = NewlineDirective.LF
        final_newline = FinalNewlineDirective.YES
        bom = BomDirective.NO
    else:
        newline = NewlineDirective.PRESERVE
        final_newline = FinalNewlineDirective.PRESERVE
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
                f"EDIT {edit_id!r} is missing <<<<<<< CONTENT",
            )

        line = lines[index]

        if line == "<<<<<<< CONTENT":
            break

        if line.startswith("NEWLINE:"):
            _require_new_directive(
                seen_directives,
                "NEWLINE",
                edit_id=edit_id,
            )
            newline = _parse_newline_directive(
                line,
                edit_id=edit_id,
            )
        elif line.startswith("FINAL_NEWLINE:"):
            _require_new_directive(
                seen_directives,
                "FINAL_NEWLINE",
                edit_id=edit_id,
            )
            final_newline = _parse_final_newline_directive(
                line,
                edit_id=edit_id,
            )
        elif line.startswith("BOM:"):
            _require_new_directive(
                seen_directives,
                "BOM",
                edit_id=edit_id,
            )
            bom = _parse_bom_directive(
                line,
                edit_id=edit_id,
            )
        else:
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    f"EDIT {edit_id!r} expected NEWLINE, "
                    "FINAL_NEWLINE, BOM, or <<<<<<< CONTENT "
                    f"at line {index + 1}"
                ),
            )

        index += 1

    _validate_whole_file_directives(
        mode,
        newline=newline,
        final_newline=final_newline,
        bom=bom,
        edit_id=edit_id,
    )

    index += 1
    content_lines: list[str] = []

    while (
        index < len(lines)
        and lines[index] != ">>>>>>> CONTENT"
    ):
        if "\x00" in lines[index]:
            raise DeterministicEditError(
                "UNSUPPORTED_ENCODING",
                (
                    f"EDIT {edit_id!r} CONTENT "
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
            f"EDIT {edit_id!r} is missing >>>>>>> CONTENT",
        )

    index += 1

    return (
        WholeFileEdit(
            target=target,
            edit_id=edit_id,
            mode=mode,
            content_lines=tuple(content_lines),
            newline=newline,
            final_newline=final_newline,
            bom=bom,
        ),
        index,
    )


def _require_new_directive(
    seen: set[str],
    name: str,
    *,
    edit_id: str,
) -> None:
    if name in seen:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"EDIT {edit_id!r} contains duplicate "
                f"{name} directive"
            ),
        )

    seen.add(name)


def _parse_newline_directive(
    line: str,
    *,
    edit_id: str,
) -> NewlineDirective:
    value = line.partition(":")[2].strip()

    try:
        return NewlineDirective(
            value
        )
    except ValueError as exc:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"EDIT {edit_id!r} has unsupported "
                f"NEWLINE: {value}"
            ),
        ) from exc


def _parse_final_newline_directive(
    line: str,
    *,
    edit_id: str,
) -> FinalNewlineDirective:
    value = line.partition(":")[2].strip()

    try:
        return FinalNewlineDirective(
            value
        )
    except ValueError as exc:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"EDIT {edit_id!r} has unsupported "
                f"FINAL_NEWLINE: {value}"
            ),
        ) from exc


def _parse_bom_directive(
    line: str,
    *,
    edit_id: str,
) -> BomDirective:
    value = line.partition(":")[2].strip()

    try:
        return BomDirective(
            value
        )
    except ValueError as exc:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"EDIT {edit_id!r} has unsupported "
                f"BOM: {value}"
            ),
        ) from exc


def _validate_whole_file_directives(
    mode: WholeFileMode,
    *,
    newline: NewlineDirective,
    final_newline: FinalNewlineDirective,
    bom: BomDirective,
    edit_id: str,
) -> None:
    if mode is not WholeFileMode.CREATE:
        return

    if newline is NewlineDirective.PRESERVE:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"CREATE EDIT {edit_id!r} cannot use "
                "NEWLINE: PRESERVE"
            ),
        )

    if final_newline is FinalNewlineDirective.PRESERVE:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"CREATE EDIT {edit_id!r} cannot use "
                "FINAL_NEWLINE: PRESERVE"
            ),
        )

    if bom is BomDirective.PRESERVE:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                f"CREATE EDIT {edit_id!r} cannot use "
                "BOM: PRESERVE"
            ),
        )


def _validate_target_operation_mix(
    edits: list[EditOperation],
) -> None:
    edits_by_target: dict[str, list[EditOperation]] = {}

    for edit in edits:
        edits_by_target.setdefault(
            edit.target,
            [],
        ).append(edit)

    for target, target_edits in edits_by_target.items():
        if (
            len(target_edits) > 1
            and any(
                isinstance(edit, WholeFileEdit)
                for edit in target_edits
            )
        ):
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    "whole-file operation must be the sole edit "
                    f"for target {target!r}"
                ),
            )


def _split_spec_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n")

    if "\r" in normalized:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            "edit specification contains unsupported lone CR",
        )

    return normalized.splitlines()


def _skip_blank_lines(
    lines: list[str],
    index: int,
) -> int:
    while index < len(lines) and lines[index] == "":
        index += 1

    return index
